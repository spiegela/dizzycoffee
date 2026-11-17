# DizzyCoffee

Local, app-free control for the **Spinn** bean-to-cup coffee maker — so you can read its
state and brew from your own tools (e.g. [Home Assistant](https://www.home-assistant.io/))
instead of the vendor's phone app.

[![Support on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/spiegela)

> **Status:** the **read path is live-verified** against a real machine — sign-in, device +
> certificate fetch, AWS IoT mutual-TLS, and reading the device shadow all work
> ([`docs/PROTOCOL.md`](docs/PROTOCOL.md)). Commands (brew/start/stop/…) are implemented but
> **confirmation-gated and not yet verified on hardware** — use `--dry-run` to see exactly what
> would be sent, and expect to confirm the brew sequence / slot numbering on your own machine.

## What this is

Spinn machines are AWS IoT Core appliances. The phone app signs you in, fetches a per-user
X.509 client certificate for *your* machine, and talks to it over MQTT (mutual TLS). DizzyCoffee
does the same handshake from Python, with **your own account**, so nothing here depends on any
third-party cloud but Spinn's (the same one the app already uses). A fully-local, no-Spinn-cloud
mode is described in the protocol doc as a future tier.

Everything is driven by **your** credentials and **your** machine's certificate, fetched fresh
each session. No secrets are committed to this repo.

## Why

Right-to-repair / interoperability for a device you own. The vendor ships no local API, no Home
Assistant integration, and no documented protocol. This project documents the protocol and
provides a clean-room-style client so the machine you bought keeps working on your terms.

This is **not** affiliated with or endorsed by Spinn. "Spinn" is used only to name the device
this software interoperates with (nominative use).

## Layout

```
docs/PROTOCOL.md     Reverse-engineered protocol: auth, REST, MQTT, command wire format, shadow schema
dizzycoffee/         Python package
  config.py          Loads your credentials/config from env + local files (never the repo)
  api.py             Spinn REST client: login, token refresh, fetch device + certificate
  shadow.py          Read-only AWS IoT shadow reader (mutual TLS); prints live machine state
  cli.py             `dizzy` command-line entry point
config.example.toml  Copy to config.toml (gitignored) and fill in, or use env vars
```

## Quick start (read-only)

Requires [`uv`](https://docs.astral.sh/uv/). All deps are pulled on demand; nothing to install.

```bash
# 1. Sign in with YOUR Spinn account (credentials go straight to Spinn, stored locally only)
uv run python -m dizzycoffee login

# 2. List the machines on your account (and confirm the certificate came through)
uv run python -m dizzycoffee devices

# 3. Print your machine's live state (consumables, status, shot count…)
uv run python -m dizzycoffee state
```

The login step writes a session token to `~/.config/dizzycoffee/session.json` (outside this
repo). The device certificate is fetched fresh each run and never written to disk.

### Read vs. command paths

`state` and `devices` only **read** (`shadow/get`, `shadow/update/documents`) and cannot actuate the
machine — the read and command paths live in separate modules (`shadow.py` vs `commands.py`).

## Commands (opt-in — these actuate your machine)

Every command below publishes to the device's command topic and **physically drives the machine**.
Each one is gated: it prints what it will send and waits for you to type `YES` (or pass `--yes` for
scripts). Use `--dry-run` first to see the exact hex without connecting to anything.

```bash
# See the wire bytes for a brew of cookbook slot 2 — sends nothing:
uv run python -m dizzycoffee brew --slot 2 --dry-run

# Actually brew slot 2 (prompts for confirmation; stand at the machine):
uv run python -m dizzycoffee brew --slot 2

uv run python -m dizzycoffee power on|off     # switch on / off
uv run python -m dizzycoffee start | stop     # start / stop
uv run python -m dizzycoffee flush            # hopper flush
uv run python -m dizzycoffee send --hex 0602  # raw escape hatch
```

> **Unverified bits.** The opcode table is confirmed from the app, but the exact brew sequence
> (`brew` defaults to `SELECT_RECIPE` then `PREPARE_RECIPE`; try `--sequence prepare` for
> `PREPARE_RECIPE` alone) and whether the `--slot` byte is 0- or 1-based still need confirming on a
> real machine. See the `[L]` items in [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Credits

Protocol recovered by static analysis of the official Android app for personal interoperability.
Inspired by the community "Project Spunn" discussion, which stayed private.

## Support

If DizzyCoffee freed your Spinn from the app, a coffee is always appreciated — no pressure, the
project stays free and open either way.

[![Support on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/spiegela)

## License

MIT — see [`LICENSE`](LICENSE).
