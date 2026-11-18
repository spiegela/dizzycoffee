# Changelog

Versions are the Home Assistant integration's (`custom_components/spinn/manifest.json`). The Lovelace
cards carry their own `CARD_VERSION`, which changes whenever the card file does so browsers reload it.

## 0.4.0 (2026-11-18)

Integration 0.4.0, cards 0.3.6. Needs Home Assistant 2024.11 or newer (was 2024.8).

### Brewing and commands
- **Brews are confirmed.** A brew waits for the machine to report it's preparing the drink. If the
  machine reports an error or hasn't started within 60 s, you get an error that says what needs
  attention (e.g. "the water tank is empty").
- Commands are refused while the machine is offline. Previously a brew to a switched-off machine
  "succeeded" and did nothing. Brew and hopper flush are also refused while it's busy (brewing,
  cleaning, rinsing, recovering); Stop always goes through.
- A double-tapped Brew pours once.
- Commands go over the live push connection when it's up, so presses respond faster.
- **Power switch** (`switch.<device>_power`): puts the machine to sleep and wakes it. Verified on a
  machine; it stays connected while asleep. Enabled by default.

### New entities and options
- `event.<device>_brew`: started / finished / failed, for brews started anywhere (app, buttons,
  Home Assistant), with recipe, slot and duration.
- `binary_sensor.<device>_needs_attention`: water or beans empty, bin or tray full or missing,
  deep clean or descale due, machine error. Reasons and warnings are attributes.
- `sensor.<device>_servings`: total drinks made, with your most-brewed recipes as attributes.
- **Grounds bin level** and **Drip tray level** sensors: real % full, worked out from the machine's
  space-left counters. "Nearly full" warns at 80 %.
- **Maintenance options** (Configure on the integration): cups between deep cleans and descales
  (default 100 / 500, 0 turns the reminder off).
- **Diagnostics download**, with tokens, email, certificate, serial, MACs and Wi-Fi details redacted.

### Cards
- **Recipes card tabs:** On machine / All / Coffee / Mine / Specials / Milk. Recipes that aren't on
  the machine brew once through the temporary slot, leaving your cookbook alone. New options:
  `tab:` (starting tab) and `tabs: false` (the old single grid).
- Default titles say "Spinn", so the cards are easy to find in the card picker.
- Bin bars show real fill levels. The hopper scale is recalibrated: LEVEL2 is full.
- Water shows in your units (e.g. fl. oz in US units). Previously it showed the raw value with "ml"
  added.
- "N drinks made" replaces the misleading ShotCount, which isn't a lifetime total. The ShotCount
  sensor moves to diagnostic.
- The cards find entities through the entity registry, so a device renamed after setup no longer
  hides newer sensors. They also no longer pick up another integration's machine-status sensor.
- If an older copy of the cards is still loaded (e.g. a leftover dashboard resource), the console
  says which resource to remove.

### Fixes
- Session-token refreshes no longer reload the whole integration.
- The manifest declares `http` (hassfest). It no longer re-lists packages Home Assistant already
  provides.
- CLI: `state --watch` prints each changed value instead of "+4 more fields".
  `config.example.toml` shows the endpoint the client actually uses.

### Project
- Tests run on Home Assistant's own test harness with Spinn's cloud stubbed out (61 tests). CI runs
  pytest, hassfest and HACS validation.
- `scripts/deploy-to-ha.sh` deploys a checkout to Home Assistant over SSH or Kubernetes.
- The README has a contributor guide; `docs/PROTOCOL.md` documents stats, power and bin levels.

## 0.3.1 (2026-11-17)

First release: the Home Assistant integration (`custom_components/spinn`) and its theme-aware
Lovelace cards (machine, recipe browser, recipe editor), with the bundled DizzyCoffee client.
