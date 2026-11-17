"""`dizzy` command line: login, devices, state. Read-only.

Run as:  uv run python -m dizzycoffee <command>
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys

from .api import SpinnClient, SpinnError
from .config import Config

# Shadow keys worth surfacing first (see docs/PROTOCOL.md §6).
STATE_KEYS = [
    "connected", "MachineStatus", "ProcessStatus",
    "HopperReservoir", "WaterTank", "WaterVolume",
    "ResidueBin", "ResidueBinCapacity", "DripTray", "DripTrayCapacity",
    "RecipeNumber", "ShotCount",
]


def _eprint(*a):
    print(*a, file=sys.stderr)


# --------------------------------------------------------------------------
# auth helpers
# --------------------------------------------------------------------------
def _authed_client(cfg: Config) -> SpinnClient:
    token = cfg.read_session()
    if not token or not token.get("access_token"):
        raise SystemExit("Not signed in. Run:  uv run python -m dizzycoffee login")
    return SpinnClient(cfg.mp_base, cfg.iot_base, access_token=token.get("access_token"))


def _get_devices_with_refresh(cfg: Config) -> list[dict]:
    """Fetch devices; on 401 try a single token refresh, then retry."""
    client = _authed_client(cfg)
    try:
        return client.get_devices()
    except SpinnError as e:
        if e.status != 401:
            raise
    token = cfg.read_session() or {}
    _eprint("Access token expired; refreshing…")
    client = SpinnClient(cfg.mp_base, cfg.iot_base)
    new = client.refresh(token)
    cfg.write_session(new)
    return client.get_devices()


def _pick_device(devices: list[dict], thing: str | None) -> dict:
    if not devices:
        raise SystemExit("No machines on this account.")
    if thing:
        for d in devices:
            if d.get("thing_name") == thing:
                return d
        raise SystemExit(f"No machine with thing_name={thing!r}.")
    if len(devices) == 1:
        return devices[0]
    names = ", ".join(d.get("thing_name", "?") for d in devices)
    raise SystemExit(f"Multiple machines; pass --thing <name>. Found: {names}")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_login(cfg: Config, args) -> int:
    client = SpinnClient(cfg.mp_base, cfg.iot_base)
    if args.amazon_token:
        token = client.login_amazon(args.amazon_token)
    else:
        email = args.email or cfg.email or input("Spinn email: ").strip()
        # getpass: the password goes straight to Spinn over HTTPS; it is never stored.
        password = getpass.getpass("Spinn password: ")
        token = client.login_password(email, password)
    if not token.get("access_token"):
        _eprint("Login returned no access token:", json.dumps(token)[:200])
        return 1
    cfg.write_session(token)
    print(f"Signed in. Session saved to {cfg.session_path} (chmod 600).")
    return 0


def cmd_logout(cfg: Config, args) -> int:
    cfg.clear_session()
    print("Local session cleared.")
    return 0


def cmd_devices(cfg: Config, args) -> int:
    devices = _get_devices_with_refresh(cfg)
    if not devices:
        print("No machines on this account.")
        return 0
    for d in devices:
        has_cert = bool((d.get("certificate") or {}).get("certificate_pem"))
        print(f"• {d.get('name') or '(unnamed)'}")
        print(f"    thing_name:  {d.get('thing_name')}")
        print(f"    serial:      {d.get('serial_number')}")
        print(f"    connected:   {d.get('connected')}")
        print(f"    host/bridge: {d.get('current_host_version')} / {d.get('current_bridge_version')}")
        print(f"    certificate: {'present' if has_cert else 'MISSING'}")
    return 0


def _reported(doc: dict) -> dict:
    state = doc.get("state") or {}
    return state.get("reported") or state or doc


def _print_state(doc: dict, raw: bool) -> None:
    rep = _reported(doc)
    for k in STATE_KEYS:
        if k in rep:
            print(f"  {k:20} {rep[k]}")
    extra = {k: v for k, v in rep.items() if k not in STATE_KEYS}
    if extra:
        print(f"  (+{len(extra)} more fields; --raw for all)")
    if raw:
        print(json.dumps(doc, indent=2))


def cmd_state(cfg: Config, args) -> int:
    from .shadow import ReadOnlyShadow  # lazy import (awscrt) so other cmds don't need it

    devices = _get_devices_with_refresh(cfg)
    dev = _pick_device(devices, args.thing)
    cert = dev.get("certificate") or {}
    pem, key = cert.get("certificate_pem"), cert.get("certificate_private_key")
    if not (pem and key):
        raise SystemExit("Selected machine has no embedded certificate; cannot connect.")
    thing = dev["thing_name"]
    sh = ReadOnlyShadow(cfg.iot_endpoint, thing, pem, key)
    print(f"Connecting to {cfg.iot_endpoint} as {thing} (read-only)…")
    sh.connect()
    try:
        if args.watch:
            print("Watching live state. Ctrl-C to stop.\n")
            sh.watch(lambda d: (_print_state(d, args.raw), print("---")))
        else:
            _print_state(sh.get_snapshot(), args.raw)
    except KeyboardInterrupt:
        pass
    finally:
        sh.disconnect()
    return 0


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dizzy", description="Read-only, app-free control for a Spinn coffee maker."
    )
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("login", help="Sign in with your Spinn account (credentials go to Spinn only).")
    pl.add_argument("--email", help="Spinn account email (else prompted / $DIZZY_EMAIL).")
    pl.add_argument("--amazon-token", help="Use a Login-with-Amazon access token instead of password.")
    pl.set_defaults(func=cmd_login)

    po = sub.add_parser("logout", help="Clear the locally stored session token.")
    po.set_defaults(func=cmd_logout)

    pd = sub.add_parser("devices", help="List machines on your account.")
    pd.set_defaults(func=cmd_devices)

    ps = sub.add_parser("state", help="Print your machine's live state (read-only).")
    ps.add_argument("--thing", help="thing_name, if you have more than one machine.")
    ps.add_argument("--watch", action="store_true", help="Stream live updates until Ctrl-C.")
    ps.add_argument("--raw", action="store_true", help="Also dump the full shadow JSON.")
    ps.set_defaults(func=cmd_state)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config.load()
    try:
        return args.func(cfg, args)
    except SpinnError as e:
        _eprint(f"error: {e}")
        if e.body:
            _eprint(e.body)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
