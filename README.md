# DizzyCoffee

Local, app-free control for the **Spinn** bean-to-cup coffee maker — so you can read its
state and brew from your own tools (e.g. [Home Assistant](https://www.home-assistant.io/))
instead of the vendor's phone app.

[![Support on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/spiegela)

> **Status:** **live-verified end to end** against a real machine — sign-in, device + certificate
> fetch, AWS IoT mutual-TLS, reading the shadow, **and brewing** (a client-issued `SELECT`+`PREPARE`
> made the machine pour) all work ([`docs/PROTOCOL.md`](docs/PROTOCOL.md)). Commands are
> confirmation-gated; use `--dry-run` to preview the exact bytes.

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

> **Verified:** `brew` (`SELECT_RECIPE` then `PREPARE_RECIPE`) pours, and `--slot N` maps to the
> shadow's `RecipeNumber N`. `--sequence prepare` sends `PREPARE_RECIPE` alone if you want to try it.
> `power`/`start`/`stop`/`flush` opcodes are confirmed from the app but their individual effects
> aren't separately exercised yet. Details in [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Home Assistant integration

A native custom integration lives in [`custom_components/spinn/`](custom_components/spinn/).
It reuses this repo's live-verified client (`dizzycoffee`) rather than reimplementing the
protocol: config-flow sign-in → device + certificate fetch → an AWS IoT **shadow push**
subscription (`cloud_push`) with a periodic re-read as a fallback.

**Entities**

- **Sensors:** beans, water tank + volume, grounds bin (+ capacity), drip tray (+ capacity),
  machine/process status, shot count, Wi-Fi/air-pressure, and the maintenance counters
  (grinder, filter, cups-since-deep-clean, cups-since-descale, cold-brew).
- **Binary sensors:** connected, brewing (`MachineStatus == PREPAREDRINK`), error
  (`MachineStatus == MACHINEERROR`).
- **Buttons (these actuate your machine):** Brew, Start, Stop, Hopper flush.
- **Select:** Recipe slot — a *local* picker for which cookbook slot the **Brew** button
  uses (changing it sends nothing; only the button actuates).

Credentials are exchanged once for a session **token** (access + refresh) stored in the
config entry — your password is never stored. The per-machine certificate is fetched fresh
from `GET link/api/devices/{thing}` on each refresh cycle, never written to disk.

### Install via HACS

1. In HACS → **⋮** → *Custom repositories*, add `https://github.com/spiegela/dizzycoffee`
   with category **Integration**.
2. Install **Spinn Coffee Maker**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Spinn**, and sign in with your Spinn
   account. If the account has more than one machine, you'll be asked to pick one.

> **Bundled client — nothing extra to install.** The integration ships a verbatim copy of the
> `dizzycoffee` client under
> [`custom_components/spinn/_vendor/`](custom_components/spinn/_vendor/), so HACS installs
> (including Home Assistant OS) work out of the box; its dependencies (`awsiotsdk`, `certifi`,
> `requests`) install automatically from the manifest. If a real `dizzycoffee` is already
> importable in your HA environment (e.g. a development checkout) it is preferred, and the
> bundled copy is used only as a fallback. See the
> [`_vendor/` README](custom_components/spinn/_vendor/README.md) for how to re-sync the copy
> after changing the client.

> Publishing to `<thing>/host` **actuates the machine**. The Brew/Start/Stop/Flush buttons do
> exactly that — treat them like pressing the machine's own buttons.

## Credits

Protocol recovered by static analysis of the official Android app for personal interoperability.
Inspired by the community "Project Spunn" discussion, which stayed private.

## Support

If DizzyCoffee freed your Spinn from the app, a coffee is always appreciated — no pressure, the
project stays free and open either way.

[![Support on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/spiegela)

## License

MIT — see [`LICENSE`](LICENSE).
