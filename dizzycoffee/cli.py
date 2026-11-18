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


def _get_devices_with_refresh(cfg: Config) -> tuple[SpinnClient, list[dict]]:
    """Return (authed client, devices); on 401 do one token refresh, then retry."""
    client = _authed_client(cfg)
    try:
        return client, client.get_devices()
    except SpinnError as e:
        if e.status != 401:
            raise
    token = cfg.read_session() or {}
    _eprint("Access token expired; refreshing…")
    client = SpinnClient(cfg.mp_base, cfg.iot_base)
    new = client.refresh(token)  # sets client.access_token
    cfg.write_session(new)
    return client, client.get_devices()


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


def _device_for_connect(cfg: Config, thing: str | None) -> tuple[str, str, str]:
    """Resolve (thing_name, cert_pem, private_key) for the selected machine.

    The usable certificate only comes from the single-device endpoint.
    """
    client, devices = _get_devices_with_refresh(cfg)
    dev = _pick_device(devices, thing)
    full = client.get_device(dev["thing_name"])
    cert = full.get("certificate") or {}
    pem, key = cert.get("certificate_pem"), cert.get("certificate_private_key")
    if not (pem and key):
        raise SystemExit("Selected machine has no usable certificate; cannot connect.")
    return full["thing_name"], pem, key


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
    client, devices = _get_devices_with_refresh(cfg)
    if not devices:
        print("No machines on this account.")
        return 0
    for d in devices:
        # The list carries only a cert stub; the full record has the PEM/key.
        full = client.get_device(d["thing_name"])
        cert = full.get("certificate") or {}
        has_cert = bool(cert.get("certificate_pem") and cert.get("certificate_private_key"))
        print(f"• {full.get('name') or '(unnamed)'}")
        print(f"    thing_name:  {full.get('thing_name')}")
        print(f"    serial:      {full.get('serial_number')}")
        print(f"    connected:   {full.get('connected')}")
        print(f"    host/bridge: {full.get('current_host_version')} / {full.get('current_bridge_version')}")
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

    thing, pem, key = _device_for_connect(cfg, args.thing)
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


def cmd_stats(cfg: Config, args) -> int:
    """Print the account's usage stats endpoints as JSON (read-only).

    Their response shapes aren't documented yet (docs/PROTOCOL.md §3); this
    prints exactly what Spinn returns so the fields can be mapped.
    """
    client, devices = _get_devices_with_refresh(cfg)
    thing = _pick_device(devices, args.thing)["thing_name"]
    for label, fetch in (
        ("stats/api/user-stats", client.get_user_stats),
        ("average-consumer/api/coffee-backlog", client.get_coffee_backlog),
    ):
        print(f"== {label}")
        try:
            print(json.dumps(fetch(thing), indent=2, sort_keys=True))
        except SpinnError as e:
            print(f"  error: {e}")
            if e.body:
                print(f"  {e.body}")
    return 0


# --------------------------------------------------------------------------
# commands that ACTUATE the machine (opt-in, confirmation-gated)
# --------------------------------------------------------------------------
def _actuate(cfg: Config, args, steps, desc: str) -> int:
    """Publish one or more command steps to <thing>/host after confirmation.

    steps: list of (DeviceCommand, param|None). --dry-run prints the hex and does
    not connect or publish. Otherwise requires --yes or an interactive 'YES'.
    """
    import time
    from .commands import encode, DeviceCommander

    payloads = [encode(c, p) for c, p in steps]
    if args.dry_run:
        print(f"[dry-run] {desc} — nothing sent")
        for pl in payloads:
            print(f"  would publish: {pl!r}  ->  <thing>/host")
        return 0

    thing, pem, key = _device_for_connect(cfg, args.thing)
    print(f"⚠️  This WILL actuate your physical Spinn ({thing}).")
    print(f"   {desc}")
    for pl in payloads:
        print(f"   publish: {pl!r} -> {thing}/host")
    if not args.yes:
        try:
            if input("   Type YES to proceed: ").strip() != "YES":
                print("Aborted — nothing sent."); return 1
        except EOFError:
            print("Aborted (no TTY; pass --yes to actuate non-interactively)."); return 1

    cmder = DeviceCommander(cfg.iot_endpoint, thing, pem, key)
    cmder.connect()
    try:
        for i, (c, p) in enumerate(steps):
            res = cmder.send(c, p)
            print(f"   sent {res['payload']} | acks: {res['acks'] or '(none within timeout)'}")
            if i + 1 < len(steps):
                time.sleep(1.0)
    finally:
        cmder.disconnect()
    return 0


def cmd_power(cfg: Config, args) -> int:
    from .commands import DeviceCommand
    on = args.state == "on"
    c = DeviceCommand.SWITCH_ON if on else DeviceCommand.SWITCH_OFF
    return _actuate(cfg, args, [(c, None)], f"power {'ON' if on else 'OFF'}")


def cmd_start(cfg: Config, args) -> int:
    from .commands import DeviceCommand
    return _actuate(cfg, args, [(DeviceCommand.START, None)], "START")


def cmd_stop(cfg: Config, args) -> int:
    from .commands import DeviceCommand
    return _actuate(cfg, args, [(DeviceCommand.STOP, None)], "STOP")


def cmd_flush(cfg: Config, args) -> int:
    from .commands import DeviceCommand
    return _actuate(cfg, args, [(DeviceCommand.HOPPER_FLUSH, None)], "HOPPER_FLUSH")


def cmd_brew(cfg: Config, args) -> int:
    from .commands import DeviceCommand
    slot = args.slot
    if args.sequence == "prepare":
        steps = [(DeviceCommand.PREPARE_RECIPE, slot)]
        desc = f"brew: PREPARE_RECIPE slot {slot}"
    else:  # select-prepare (default)
        steps = [(DeviceCommand.SELECT_RECIPE, slot), (DeviceCommand.PREPARE_RECIPE, slot)]
        desc = f"brew: SELECT_RECIPE + PREPARE_RECIPE slot {slot}"
    return _actuate(cfg, args, steps, desc + "  [L] sequence/slot-base unverified")


def cmd_send(cfg: Config, args) -> int:
    # Raw hex escape hatch. Validate here so --dry-run can show it offline.
    try:
        bytes.fromhex(args.hex)
    except ValueError:
        raise SystemExit(f"--hex must be an even-length hex string, got {args.hex!r}")
    payload = args.hex.lower()
    if args.dry_run:
        print(f"[dry-run] raw send — nothing sent\n  would publish: {payload!r}  ->  <thing>/host")
        return 0
    thing, pem, key = _device_for_connect(cfg, args.thing)
    print(f"⚠️  This WILL actuate your physical Spinn ({thing}).")
    print(f"   publish RAW: {payload!r} -> {thing}/host")
    if not args.yes:
        try:
            if input("   Type YES to proceed: ").strip() != "YES":
                print("Aborted — nothing sent."); return 1
        except EOFError:
            print("Aborted (no TTY; pass --yes to actuate non-interactively)."); return 1
    from .commands import DeviceCommander
    cmder = DeviceCommander(cfg.iot_endpoint, thing, pem, key)
    cmder.connect()
    try:
        res = cmder.send_raw(payload)
        print(f"   sent {res['payload']} | acks: {res['acks'] or '(none within timeout)'}")
    finally:
        cmder.disconnect()
    return 0


def _add_actuate_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--thing", help="thing_name, if you have more than one machine.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the hex that WOULD be sent; connect to nothing, actuate nothing.")
    p.add_argument("--yes", action="store_true",
                   help="Skip the interactive confirmation (for scripts). Still actuates!")


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

    pst = sub.add_parser("stats", help="Print your account's coffee stats as JSON (read-only).")
    pst.add_argument("--thing", help="thing_name, if you have more than one machine.")
    pst.set_defaults(func=cmd_stats)

    # --- actuating commands (opt-in; each gated by confirmation / --yes) ---
    pw = sub.add_parser("power", help="[ACTUATES] Switch the machine on or off.")
    pw.add_argument("state", choices=["on", "off"])
    _add_actuate_flags(pw); pw.set_defaults(func=cmd_power)

    pstart = sub.add_parser("start", help="[ACTUATES] Send START.")
    _add_actuate_flags(pstart); pstart.set_defaults(func=cmd_start)

    pstop = sub.add_parser("stop", help="[ACTUATES] Send STOP.")
    _add_actuate_flags(pstop); pstop.set_defaults(func=cmd_stop)

    pf = sub.add_parser("flush", help="[ACTUATES] Hopper flush.")
    _add_actuate_flags(pf); pf.set_defaults(func=cmd_flush)

    pb = sub.add_parser("brew", help="[ACTUATES] Brew a cookbook slot.")
    pb.add_argument("--slot", type=int, required=True,
                    help="Recipe/cookbook slot byte (0- vs 1-based is [L] unverified).")
    pb.add_argument("--sequence", choices=["select-prepare", "prepare"], default="select-prepare",
                    help="select-prepare (default): SELECT then PREPARE; prepare: PREPARE only.")
    _add_actuate_flags(pb); pb.set_defaults(func=cmd_brew)

    psend = sub.add_parser("send", help="[ACTUATES] Publish a raw hex payload to <thing>/host.")
    psend.add_argument("--hex", required=True, help="Even-length hex string, e.g. 0602.")
    _add_actuate_flags(psend); psend.set_defaults(func=cmd_send)

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
