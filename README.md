# DizzyCoffee

Local, app-free control for the **Spinn** bean-to-cup coffee maker — so you can read its
state and brew from your own tools (e.g. [Home Assistant](https://www.home-assistant.io/))
instead of the vendor's phone app.

> **Status:** early. The protocol is fully reverse-engineered and documented
> ([`docs/PROTOCOL.md`](docs/PROTOCOL.md)); a **read-only** Python client is included. Writing
> commands (brew/start/stop) is specified but intentionally not wired into the CLI yet.

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

### Read-only by design

`state` and `devices` only **read** (`shadow/get`, `shadow/update/documents`). This client does
not publish to the command topic, so it cannot brew, start, stop, or otherwise actuate the
machine. Command support is documented in `docs/PROTOCOL.md` and will be added behind an explicit,
opt-in flag.

## Credits

Protocol recovered by static analysis of the official Android app for personal interoperability.
Inspired by the community "Project Spunn" discussion, which stayed private.

## License

MIT — see [`LICENSE`](LICENSE).
