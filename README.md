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
  api.py             Spinn REST client: login, token refresh, device + certificate, cookbook + recipes
  recipes.py         Recipe catalog, slot layout, and slider maths (grams/ml ↔ the app's 0–1 values)
  connection.py      AWS IoT mutual-TLS connection
  shadow.py          Read-only AWS IoT shadow reader; prints live machine state
  commands.py        Opt-in command path (brew, power, start/stop, flush)
  cli.py             `dizzy` command-line entry point
custom_components/spinn/  Home Assistant integration + dashboard cards
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
# See the wire bytes for a brew of slot 4 (the tall cup button) — sends nothing:
uv run python -m dizzycoffee brew --slot 4 --dry-run

# Actually brew slot 4 (prompts for confirmation; stand at the machine):
uv run python -m dizzycoffee brew --slot 4

uv run python -m dizzycoffee power on|off     # switch on / off
uv run python -m dizzycoffee start | stop     # start / stop
uv run python -m dizzycoffee flush            # hopper flush
uv run python -m dizzycoffee send --hex 0602  # raw escape hatch
```

> **Verified:** `brew` (`SELECT_RECIPE` then `PREPARE_RECIPE`) pours, and `--slot N` maps to the
> shadow's `RecipeNumber N` (slots 0–3 are the user dots, 4/5/6 the tall/medium/small cup buttons;
> see [Cookbook slots](#cookbook-slots)). `--sequence prepare` sends `PREPARE_RECIPE` alone if you want to try it.
> `power`/`start`/`stop`/`flush` opcodes are confirmed from the app but their individual effects
> aren't separately exercised yet. Details in [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Home Assistant integration

A native custom integration lives in [`custom_components/spinn/`](custom_components/spinn/).
It reuses this repo's live-verified client (`dizzycoffee`) rather than reimplementing the
protocol: config-flow sign-in → device + certificate fetch → an AWS IoT **shadow push**
subscription (`cloud_push`) with a periodic re-read as a fallback.

<table>
  <tr>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/machine-light.png" width="280" alt="Spinn Machine card, light theme, ready"></td>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/editor-light.png" width="280" alt="Spinn Recipe Editor card adjusting a custom Americano"></td>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/recipes-dark.png" width="280" alt="Spinn Recipes card, dark theme"></td>
  </tr>
</table>

### Features

- **Live machine state, pushed** — status, brewing/cleaning/error, consumable levels, counters,
  and the installed cookbook update within a second or two of the machine changing.
- **Brew from Home Assistant** — any cookbook slot, or **any recipe at all** (specials, milk
  drinks, unsaved tweaks) through the machine's temporary slot, without touching your cookbook.
  A brew only reports success once the machine is actually pouring; otherwise you get an error
  saying why (offline, busy, empty tank, full drip tray, …).
- **Automation hooks** — a **Brew** event (started / finished / failed, for brews started
  anywhere) and a single **Needs attention** sensor that lists what to refill, empty or clean.
- **Recipe editor** — every recipe on your account with its real adjustable ranges; save
  your own versions and install them on the machine's buttons.
- **Maintenance at a glance** — cups since deep clean / descale, filter uses, and when each was
  last done.
- **Three theme-aware dashboard cards**, registered automatically.
- **Diagnostics download** with tokens, certificate, serial and MAC addresses removed, for
  bug reports.
- **No password stored** — sign-in is exchanged for a session token; the device certificate is
  fetched fresh each cycle and never written to disk.

### Entities

Entity ids are `<domain>.<device>_<name>`, e.g. `sensor.kitchen_spinn_beans`. Items marked
*diagnostic* sit in the device page's Diagnostic section.

**Sensors**

| Entity | What it reports |
|---|---|
| Machine status | `READY`, `PREPAREDRINK`, `CLEANING`, `EXPELL`, `MACHINEERROR`, … (enum) |
| Process status | Current step while brewing or cleaning (enum), *diagnostic* |
| Beans | Hopper fill level |
| Water tank | Tank fill level |
| Water volume | Water in the tank (ml) |
| Water line status | Plumbed-in water line state, *diagnostic* |
| Grounds bin · Grounds bin capacity | Grounds bin fill, and its capacity *(diagnostic)* |
| Drip tray · Drip tray capacity | Drip tray fill, and its capacity *(diagnostic)* |
| Recipe number | Slot of the recipe last selected on the machine |
| Shot count | Lifetime shots brewed |
| Cups since deep clean · Cups since descale | Maintenance counters, *diagnostic* |
| Filter counter | Uses since the water filter was changed, *diagnostic* |
| Grinder user counter · Grinder master counter | Grinder counters, *diagnostic* |
| Cold brew counter | Cold brews made, *diagnostic* |
| Last cleaning · Last descaling · Last filter change | Timestamps, *diagnostic* |
| Wi-Fi signal · Air pressure | dBm / sensor reading, *diagnostic*, disabled by default |
| Recipe catalog | Count of recipes; attributes `recipes` (every recipe with its values and adjustable ranges) and `cookbook` (what's in each slot). Used by the recipe editor; not recorded to history. |

**Binary sensors**

| Entity | On when |
|---|---|
| Connected | The machine is online to Spinn's cloud, *diagnostic* |
| Brewing | `MachineStatus` is `PREPAREDRINK` |
| Cleaning | `MachineStatus` is `CLEANING` or `EXPELL` (rinse / flush) |
| Error | `MachineStatus` is `MACHINEERROR` |
| Needs attention | Something needs doing: water or beans empty, grounds bin or drip tray full or out, deep clean or descale due, or a machine error. Attribute `reasons` lists what turned it on; `warnings` lists heads-ups that don't (water/beans low, bin/tray nearly full). |

`reasons`: `machine_error`, `water_tank_empty`, `beans_empty`, `grounds_bin_full`,
`grounds_bin_removed`, `drip_tray_full`, `drip_tray_removed`, `deep_clean_due` (100 cups since the
last deep clean), `descale_due` (500 cups). `warnings`: `water_tank_low`, `beans_low`,
`grounds_bin_nearly_full`, `drip_tray_nearly_full`. The rules match the machine card's status
icons.

**Event**

| Entity | Fires |
|---|---|
| Brew | `started` when the machine begins pouring, `finished` when it stops (including after **Stop**), `failed` if it goes from pouring to an error. Brews started from the machine's buttons or the Spinn app count too. Event data: `slot`, `recipe`, `recipe_id`, and `duration_s` on finished / failed. |

```yaml
# e.g. tell me when my coffee's ready
triggers:
  - trigger: state
    entity_id: event.kitchen_spinn_brew
    attribute: event_type
    to: finished
actions:
  - action: notify.mobile_app_phone
    data:
      message: "{{ trigger.to_state.attributes.recipe or 'Coffee' }} is ready ☕"
```

**Buttons** — *these actuate your machine*

| Entity | Does |
|---|---|
| Brew | Brews the slot chosen in **Recipe slot** |
| Start · Stop | Start / stop the current operation |
| Hopper flush | Runs a hopper flush |

Commands are refused, with an error saying why, while the shadow reports the machine **offline**
(otherwise the cloud would accept a brew for a switched-off machine and nothing would happen).
**Brew** and **Hopper flush** are also refused while the machine is busy (brewing, cleaning,
rinsing, recovering); **Stop** always goes through while it's online. **Brew** waits for the
machine to report that it's pouring: if it reports an error, or hasn't started within 60 s, the
press fails with whatever the machine says needs attention ("the water tank is empty").

**Select**

| Entity | Does |
|---|---|
| Recipe slot | Picks which cookbook slot **Brew** pours. Local only: changing it sends nothing. Attributes list each slot's recipe. |

### Cookbook slots

Every machine has 8 slots. The number is what the Brew button, the select and the services use,
and it equals the shadow's `RecipeNumber`:

| Slot | On the machine |
|---|---|
| 0–3 | The four user dots next to the person icon |
| 4 | Tall cup button |
| 5 | Medium cup button |
| 6 | Small cup button |
| 7 | Temporary slot, used for one-off brews (not user-assignable) |

### Services

All four take an optional `device_id`, needed only if you have more than one Spinn. Recipe ids
come from the **Recipe catalog** sensor's `recipes` attribute (they're specific to your account).

| Service | Does | Fields |
|---|---|---|
| `spinn.brew_recipe` | **Brews** any recipe once via the temporary slot. *Actuates the machine.* Same checks as the Brew button: refused when offline or busy (before anything is staged), and returns only once the machine is pouring. | `recipe_id`, optional `strength_g`, `size_ml`, `balance_pct`, `coffee_first` |
| `spinn.save_recipe` | Saves an adjusted copy as your own recipe, optionally installing it. Returns `{id, name, slot}`. | `base_recipe_id`, `name`, optional `slot` (0–6) + the same values |
| `spinn.install_recipe` | Puts an existing recipe into a slot | `recipe_id`, `slot` (0–6) |
| `spinn.delete_recipe` | Deletes one of your custom recipes (refused if it's installed in a slot) | `recipe_id` |

Values outside a recipe's range are clamped to it. Specials and milk drinks are fixed (brew-only);
milk drinks pour their ristretto base and leave the milk to you.

```yaml
# e.g. a morning automation
action: spinn.brew_recipe
data:
  recipe_id: o2MjNtPRAnC8PA1e1z068   # your Americano's id, from the Recipe catalog sensor
  strength_g: 15
  size_ml: 240
```

### Install

**Home Assistant 2026.11 and later (Marketplace):**

1. **Settings → Marketplace → Add from link**, enter `spiegela/dizzycoffee`, and choose type
   **Integration** if asked. (Custom repositories need a one-time GitHub sign-in.)
2. Install **Spinn Coffee Maker**. Setup starts straight away; sign in with your Spinn account,
   and pick a machine if the account has more than one.

**Older versions (HACS):** HACS → **⋮** → *Custom repositories*, add
`https://github.com/spiegela/dizzycoffee` as an **Integration**, install **Spinn Coffee Maker**,
restart, then **Settings → Devices & Services → Add Integration → Spinn**.

> **Bundled client — nothing extra to install.** The integration ships a verbatim copy of the
> `dizzycoffee` client under
> [`custom_components/spinn/_vendor/`](custom_components/spinn/_vendor/), so Marketplace and HACS installs
> (including Home Assistant OS) work out of the box; `awsiotsdk` installs automatically from the
> manifest, and `requests` / `certifi` already come with Home Assistant. If a real `dizzycoffee` is already
> importable in your HA environment (e.g. a development checkout) it is preferred, and the
> bundled copy is used only as a fallback. See the
> [`_vendor/` README](custom_components/spinn/_vendor/README.md) for how to re-sync the copy
> after changing the client.

### Dashboard cards

The integration ships three theme-aware Lovelace cards (in
[`custom_components/spinn/frontend/`](custom_components/spinn/frontend/)) and **registers
them automatically** — no manual resource step. Edit a dashboard → **Add card** → search
"Spinn". Each card finds the first Spinn device's entities on its own.

#### Spinn Machine — `custom:spinn-machine-card`

<table>
  <tr>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/machine-light.png" width="260" alt="Ready"></td>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/machine-dark-brewing.png" width="260" alt="Brewing, dark theme"></td>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/machine-attention.png" width="260" alt="Needs attention: water empty, drip tray full, maintenance due"></td>
  </tr>
  <tr><td align="center">Ready</td><td align="center">Brewing (dark theme)</td><td align="center">Needs attention</td></tr>
</table>

An illustration of the machine that tracks it live: the hopper's beans drop with the level, the
status icons light up when water, drip tray or grounds need you, the glass fills while brewing,
and the spinn ring sweeps green while it works. Beside it are level bars and the shot count.
Below: one **Brew** button (it becomes **Stop** while busy), favorite chips, and a
**Maintenance** section with deep-clean / descale / filter progress, a Hopper flush button,
and water-line, Wi-Fi and firmware details. The cup buttons drawn on the machine are tappable
and brew whatever is in those slots.

```yaml
type: custom:spinn-machine-card
name: Kitchen Spinn        # optional title (default: the device name, prefixed with "Spinn" if it lacks it)
favorites: [0, 1, 2, 3]    # slots to show as chips (names/icons come from the cookbook)
# favorites:               # or spell them out
#   - { slot: 4, name: Morning mug, icon: mug }
# machine_buttons: { small: 6, medium: 5, tall: 4 }   # default: from the cookbook; false = off
# deep_clean_every: 100    # cups between deep cleans, for the progress bar (default 100)
# descale_every: 500       # cups between descales (default 500)
# maintenance: false       # hide the maintenance section
# confirm: true            # ask before each brew
# prefix: kitchen_spinn    # entity slug, if auto-detect guesses wrong
```

#### Spinn Recipes — `custom:spinn-recipe-card`

<table>
  <tr>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/recipes-light.png" width="300" alt="Recipes card, light"></td>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/recipes-dark.png" width="300" alt="Recipes card, dark"></td>
  </tr>
</table>

A grid of what's installed on the machine; tap a tile to brew it. With no options it shows the
seven slots from your cookbook, with names, sizes and which button each sits on.

```yaml
type: custom:spinn-recipe-card
# title: Spinn Recipes     # default
# recipes: [4, 5, 6]                                       # just these slots
# recipes:
#   - { slot: 0, name: Crema Americano, icon: americano }  # or override names/icons
# confirm: true
```

#### Spinn Recipe Editor — `custom:spinn-recipe-editor-card`

<table>
  <tr>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/editor-light.png" width="260" alt="Adjusting a custom recipe"></td>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/editor-dark-special.png" width="260" alt="A special recipe with its ingredient list"></td>
    <td><img src="https://raw.githubusercontent.com/spiegela/dizzycoffee/main/docs/images/editor-light-milk.png" width="260" alt="A milk drink guide"></td>
  </tr>
  <tr><td align="center">Your recipe</td><td align="center">Specials</td><td align="center">Milk drinks</td></tr>
</table>

Every recipe the Spinn app offers: the stock coffees, your own, the specials (with their
ingredient lists) and the milk drinks. Filter by type, pick one, and adjust **strength**,
**size**, **water balance** and **pour order** within that recipe's real ranges; the cup
preview follows along. Then:

- **Brew once** — pours it now, adjusted, without changing your cookbook (`spinn.brew_recipe`).
- **Save as…** — keeps it as your own recipe, optionally straight onto a slot (`spinn.save_recipe`).
- **Put in slot…** — installs a recipe onto a user dot or cup button (`spinn.install_recipe`).
- **Delete** — removes one of your custom recipes, after a confirmation step.

```yaml
type: custom:spinn-recipe-editor-card
# title: Spinn Recipe Editor   # default
# filter: custom           # start on: all | coffee | custom | special | milk
# confirm: true            # ask before Brew once
```

Every recipe is drawn as its own illustration (picked from the recipe's Spinn slug), with an
accent colour behind each tile; in the editor the picture follows strength, size and pour order.
To choose a drawing yourself, set `icon` on a favorite or recipe tile: `espresso`, `ristretto`,
`espressoplus`, `doppio`, `lungo`, `americano`, `coffee`, `mug`, `xlbold`, `carafe`,
`travelmug`, `tumbler`, `pourover`, `water`, `coldbrew`, `nitro`, `coldespresso`, `latte`,
`vanillalatte`, `cappuccino`, `flatwhite`, `cortado`, `macchiato`, `mocha`, `affogato`,
`barraquito`, `romano`, `martini`, `guillermo`, `holiday`, `icedcappuccino`, `moonlight`,
`pumpkin`. Any entity can be overridden in YAML by its key (e.g. `beans: sensor.my_beans`).

If you ever disable auto-registration, add the module manually as a dashboard resource:
`/spinn_cards/spinn-card.js` (JavaScript module).

### Diagnostics

**Settings → Devices & Services → Spinn → ⋮ → Download diagnostics** saves a JSON file with
the machine's live state, the device record, the installed cookbook, the recipe catalog, the
connection status and what **Needs attention** sees. The session token, email, device
certificate and key, serial number, MAC addresses, Wi-Fi details and the machine's thing name
are removed, so it's safe to attach to an issue.

> Publishing to `<thing>/host` **actuates the machine**. The Brew/Start/Stop/Flush buttons, the
> recipe tiles, the machine's drawn cup buttons, **Brew once** and `spinn.brew_recipe` all do
> exactly that — treat them like pressing the machine's own buttons. Saving, installing and
> deleting recipes change your Spinn account's cookbook but never start a brew.

## Development

Tests run against Home Assistant's own test harness, with Spinn's cloud stubbed out, so they never
touch the network or a machine:

```bash
uv venv --python 3.14
uv pip install -r requirements_test.txt
.venv/bin/python -m pytest
```

CI (`.github/workflows/ci.yml`) runs these tests, Home Assistant's **hassfest** validation and
the **HACS** validation on every push and pull request. The tests also check that the bundled
client in `custom_components/spinn/_vendor/` still matches `dizzycoffee/`.

## Credits

Protocol recovered by static analysis of the official Android app for personal interoperability.
Inspired by the community "Project Spunn" discussion, which stayed private.

## Support

If DizzyCoffee freed your Spinn from the app, a coffee is always appreciated — no pressure, the
project stays free and open either way.

[![Support on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/spiegela)

## License

MIT — see [`LICENSE`](LICENSE).
