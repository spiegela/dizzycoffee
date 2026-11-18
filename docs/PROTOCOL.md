# DizzyCoffee — Spinn Local Control Protocol

Reverse-engineered statically from the official **Spinn 3.6.9** Android app (full `jadx` decompile),
for personal interoperability with a device the author owns.

Everything below is **[C] Confirmed** from decompiled source / Retrofit annotations / Gson
`@SerializedName`, unless tagged **[L] verify live** (a runtime assumption worth a smoke test).
App package `com.spinn.spinncoffee`.

> **[V] Live-verified 2026-11-17** against a real machine with the DizzyCoffee client: email/password
> auth, device + certificate fetch, ATS MQTT mutual-TLS, the shadow read path, **and a client-issued
> brew** (`0505`+`0605` → the machine poured) all work. Corrections from that run are folded in below
> and tagged **[V]**: (1) the usable cert is only on the single-device endpoint; (2) connect to the
> **ATS** IoT endpoint, not the legacy one the app ships; (3) the real `reported` shadow key set;
> (4) the brew sequence and slot-byte semantics (§5).

---

## 1. Architecture

Standard **AWS IoT Core** appliance. Phone authenticates to Spinn's backend (identity = **Login with
Amazon**, or email/password); the backend returns the device record **with an embedded X.509 client
cert**; the phone connects to AWS IoT over **MQTT + mutual TLS** and drives the machine via a
device-scoped command topic plus the **Device Shadow**. No LAN/BLE control path for normal operation
(only Wi-Fi provisioning).

```
login ───▶ POST www.spinn.com/api/auth/login  (email+password)   ─┐
   (or)     POST www.spinn.com/api/auth/amazon (Login-with-Amazon) ─┼─▶ bearer (+ refresh via auth/token)
                                                                    │
GET iot.spinn.com/link/api/devices  ────────────────────────────────┤─▶ Device{ thing_name,
   (bearer)                                                          │        certificate{pem, private_key}, ... }
                                                                     ▼
MQTT 8883 mutual-TLS ─▶ a1gzieuy3t1932-ats.iot.us-east-1.amazonaws.com   [V] use the -ats endpoint
     publish  <thing>/host              = hex command string  (brew/start/stop/clean)
     pub/sub  $aws/things/<thing>/shadow/get[/accepted], /update/documents   = machine state
     sub      <thing>/host (+/bridge,/log)   = JSON events/acks (DeviceError envelope)
```

**Config (`com.spinn.spinncoffee.app.AppConfig`):**
| Const | Value |
|---|---|
| `IOT_AWS_ENDPOINT` (as shipped) | `a1gzieuy3t1932.iot.us-east-1.amazonaws.com` (MQTT 8883) |
| **[V] actually connect to** | `a1gzieuy3t1932-ats.iot.us-east-1.amazonaws.com` (see note below) |
| `API_MP_DOMAIN` (marketplace base) | `https://www.spinn.com/api/` |
| `IOT_ENDPOINT` (iot base) | `https://iot.spinn.com/` |

**[V] Endpoint — use ATS, not the shipped one.** The app ships the *legacy* IoT endpoint
(`a1gzieuy3t1932.iot.…`), whose server certificate chains to an old VeriSign/Symantec root that
modern CA bundles (certifi, current OS trust stores) no longer carry — a client that trusts the
standard roots gets `CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`. The
equivalent **ATS** endpoint (`a1gzieuy3t1932-ats.iot.…`, same account prefix + `-ats`) routes to
the same AWS IoT and accepts the same device cert, but presents an **Amazon Trust Services** server
cert that validates against Amazon Root CA 1. Derive it by inserting `-ats` before `.iot.`.

**[V] The machine itself uses the legacy endpoint.** The TLS probe (§8) saw it ask for
`a1gzieuy3t1932.iot.us-east-1.amazonaws.com` (SNI) on every connection (firmware 2.11.219,
2026-11-18). So its firmware trusts the legacy VeriSign/Symantec root, and it would need a firmware
update from Spinn if AWS ever retired that endpoint. Clients like DizzyCoffee should keep using ATS.

---

## 2. Identity & auth

- **IdPs:** email/password, Login with Amazon, Facebook. (`assets/api_key.txt` is the app's LWA SDK
  key — an Android-signed OAuth client; not needed for the email/password path.)
- **`AuthFunctionsApi`** (base `https://www.spinn.com/api/`):
  - `POST auth/login` — body `LoginBody {email, password}` → `InlineResponseAuth`
  - `POST auth/amazon` — body `AuthBody {token, auth_type}` (LWA access token) → `InlineResponseAuth`
  - `POST auth/facebook` — body `AuthBody` → `InlineResponseAuth`
  - `POST auth/token` — body `Token` (the session token, carrying `refresh_token`) → `InlineResponseAuth`
  - `POST auth/register/{regType}` · `POST auth/logout` · `GET account/is-fb?email=`
  - Bearer injected by `AuthenticationRequestInterceptor` (**[L]** `Authorization: Bearer <access_token>`);
    refresh by `TokenAuthenticator`; extra header `Authorization-Share-Token` for shared devices.
- **Response `InlineResponseAuth` = `{ account: User, token: Token }`.**
  `Token {access_token, refresh_token, token_type, expires_in, date_created, last_login_date}`.
- **MQTT auth = per-user X.509 client cert, embedded in the `Device`:**
  `Device.certificate : AwsCertificate { id, certificate_pem, certificate_private_key }`
  (`@SerializedName("certificate")`).
  **[V]** The live object is richer — `{id, certificate_id, certificate_arn, certificate_pem,
  certificate_private_key, certificate_pfx, device_id, created_at, updated_at, is_guest, …}` — and,
  crucially, **`certificate_pem`/`certificate_private_key` are only returned by the single-device
  endpoint** `GET link/api/devices/{thing_name}`. The list endpoint (`GET link/api/devices`) returns
  only a cert **stub** (ids/arn, no PEM/key). The app writes it to a local BKS keystore
  (`AWSIotKeystoreHelper`, store `devicecrt`, pass `spinnIoT` — a local passphrase, **not** a server
  secret) and calls `mqttManager.connect(keystore, cb)`. A standalone client uses the PEM + private
  key directly (mutual TLS); no keystore needed.
- Cognito classes are bundled but the **cert path is what `DeviceManager.connect()` uses** — no SigV4.

---

## 3. REST API

Base `https://iot.spinn.com/` unless noted. (`Api.init(marketPlaceUrl, iotUrl)` →
`www.spinn.com/api/`, `iot.spinn.com/`.)

**`IotFunctionsApi`** (device plane):
`GET link/api/devices` → `List<Device>` · `GET link/api/devices/{thing_name}` · `.../public-info` ·
`POST link/api/applications` (`RegisterDeviceBody`→Device, linking) · `POST link/api/devices/{tn}/unlink` ·
`PUT link/api/devices/{tn}` (`UpdateDeviceBody`) · `PUT link/api/devices/{tn}/config` (`ConfigDeviceBody`) ·
`POST link/api/devices/{tn}/air-pressure` · `PUT link/api/devices/{tn}/guest` ·
`GET average-consumer/api/coffee-backlog` · `POST log/api/machine-logs` (`CoffeeCommandLogEventBody`) ·
`GET stats/api/user-stats`.

> **[V]** `GET link/api/devices/{thing_name}` is the one to call for control: it returns the full
> record **including the usable certificate** (the list endpoint omits the PEM/key). Auth is
> `Authorization: Bearer <access_token>` — confirmed live.

**`RecipesFunctionsApi`**: `GET recipe/api/recipes` · `GET recipe/api/cookbook` ·
`PUT recipe/api/cookbook/slot` · `.../product` · `.../temporary-slot` · `GET recipe/api/recipes/shared/{id}` ·
POST/DELETE `recipe/api/recipes[/{id}]`. → **cookbook slots are the recipe numbers** the brew commands select.

> **[V] Live-verified 2026-11-17 (read-only GETs).** Both reads live on `iot.spinn.com` and **404 without
> `?thing_name=<thing>`**:
> - `GET recipe/api/cookbook?thing_name=…` → `{id, thing_name, roaster_settings, created_at, updated_at,
>   slots: [{recipe_id, recipe_product_id, status, recipe_params?}, …]}` — 8 slots, matching the
>   shadow's 8-entry `recipes` array.
> - `GET recipe/api/recipes?thing_name=…[&all=true]` → recipe records. Without `all`: the account
>   **library** (stock + the user's custom copies; 21 on the test account). `all=true` adds the
>   `type:"technical"` **Specials** (Affogato, Iced Cappuccino, Cafe Romano, Guillermo, Cafe Barraquito,
>   Pumpkin Spice, Holiday Drink, Espresso Martini, Moonlight Fomo) plus an internal "Drying Recipe"
>   (31 total). Each record has `id, name, slug, type` (`spinn`/`custom`/`technical`), `parent_name`
>   (custom copies), `image_url`, `drink_size` (ml), `shots`, `cooldown_machine` (1 = cold),
>   `special_params {cup_size_ml, release_notes, required_items[{text,img}]}`, a **`slider`** object with
>   the user-editable ranges (`coffee_weight {min,max}` in 0.1 g, `volume_extraction {min,max}` ml,
>   `water_balance {min,max}` %, `coffee_order`/`cooldown_machine` booleans), and ~90 derived brewer
>   parameters. `*_float` fields are the position within the slider range (e.g. Espresso 🚀
>   `coffee_strength_float` = (110−90)/(160−90) = 0.2857).
> - **Milk drinks** (Latte, Cappuccino, Flat White, Cortado, Macchiato, Mocha, Vanilla Latte) are not on
>   the server: the app hard-codes them (`RecipesRepository.milkRecipes`) as a ristretto shot plus
>   frother instructions.
> - `GET recipe/api/recipes/{id}` and the `www.spinn.com/api/` base both 404.
>
> **[C] Slot layout** (`RecipesRepository`, `Cookbook`): the brew byte is the **0-based** cookbook index
> (`Cookbook.indexOf` → `PREPARE_RECIPE`+index), equal to the shadow `RecipeNumber`.
>
> | index | role | app constant |
> |---|---|---|
> | 0–3 | user slots (`Cookbook.userSlots` = first 4; the 4 dots beside the panel's person icon) | — |
> | 4 | tall cup button | `COFFEE_SLOT` |
> | 5 | medium cup button | `LUNGO_SLOT` |
> | 6 | small cup button | `ESPRESSO_SLOT` |
> | 7 | temporary one-off slot | `TEMP_SLOT` |
>
> To brew a recipe that isn't installed, the app `PUT recipe/api/cookbook/temporary-slot`s it, then sends
> `PREPARE_RECIPE` + `07`. (The earlier live brew of byte `05` therefore poured slot 5 = the medium-button
> recipe.)
>
> **Write bodies** (these change the account and sync to the machine; `[V]` = exercised live and reverted):
> - **[V]** `POST recipe/api/recipes` `CreateCustomRecipeBody {thing_name, recipe_slug, name,
>   coffee_strength_float, water_level_float, water_balance_float?, coffee_order?}` — a custom copy of the
>   base recipe `recipe_slug`; the server derives every brewer parameter from the floats (verified: a Lungo
>   copy with `water_level_float` 0.20 → 0.45 came back with volume 86 → 107 ml, `drink_size` 77 → 100).
> - **[C]** `PUT recipe/api/cookbook/slot` `UpdateCookbookBody {thing_name, slot, recipe_id}` (the app sends
>   only these three) — install a recipe into a slot.
> - **[V]** `PUT recipe/api/cookbook/temporary-slot` `{thing_name, recipe_id, water_level_float?,
>   coffee_strength_float?, water_balance_float?, coffee_order?}` — one-off, optionally adjusted; returns
>   `completed` at once and leaves slots 0–6 untouched.
> - **[C]** `POST recipe/api/cookbook/reset` `{thing_name, slot}` · **[V]** `DELETE recipe/api/recipes/{id}` ·
>   `GET recipe/api/products/{product_id}/sliders` (per-coffee slider overrides).

Other interfaces present: `ProductsFunctionsApi, OrderFunctionsApi, UserFunctionsApi,
NotificationsFunctionsApi, RoasterFunctionsApi, MarketplaceFunctionsApi, IotWithoutAuthFunctionsApi`.

---

## 4. AWS IoT MQTT

- **Broker [V]** `a1gzieuy3t1932-ats.iot.us-east-1.amazonaws.com:8883` (ATS; see §1), mutual TLS
  (Amazon Root CA 1 for the server + §2 client cert), client id `"Android"+UUID` (pick your own).
  All pub/sub **QoS 1**. `<thing>` = `Device.thingName`.

| Topic (`%s`←thing) | Dir | Purpose |
|---|---|---|
| `$aws/things/%s/shadow/get` / `…/get/accepted` | pub / sub | shadow snapshot |
| `$aws/things/%s/shadow/update/documents` | sub | live state stream |
| `%s/host` | pub | **commands** (hex) |
| `%s/host` | sub | events / acks (JSON `DeviceError` envelope) |
| `%s/bridge`, `%s/log`, `%s/link` | pub | bridge / logs / linking |

---

## 5. Commands — `%s/host` wire format

`runCustomCommand(device, DeviceCommand cmd, Byte? param)` builds a **hex string** and publishes it to
`<thing>/host`:  `payload = cmd.hex` (+ `param.hex` if present), where `.hex = %02x` of the byte.

**`DeviceCommand` enum (opcode byte):**
| Name | byte | hex | Name | byte | hex |
|---|---|---|---|---|---|
| NONE | 0 | `00` | SELECT_RECIPE | 5 | `05` |
| SWITCH_ON | 1 | `01` | PREPARE_RECIPE | 6 | `06` |
| SWITCH_OFF | 2 | `02` | REBOOT | 7 | `07` |
| START | 3 | `03` | RESET_GRINDER_COUNTER | 8 | `08` |
| STOP | 4 | `04` | HOPPER_FLUSH | 17 | `11` |

Examples (payload is the literal ASCII hex):
- Power on / off → `"01"` / `"02"` · Start / Stop brew → `"03"` / `"04"` · Hopper flush → `"11"`
- **[V] Brew recipe slot 5** (verified live): publish `SELECT_RECIPE`+slot `"0505"`, then
  `PREPARE_RECIPE`+slot `"0605"` → the machine enters `MachineStatus=PREPAREDRINK` and pours. The
  select-then-prepare sequence works, and **the slot byte equals the shadow's `RecipeNumber`** value
  (slot 5 ↔ `RecipeNumber="5"`), so it is not an extra-offset index. `RecipeNumber` indexes the
  shadow `recipes` array (§6).

**[V] Host echo / acks.** Publishing to `<thing>/host` while subscribed to it returns your own
message back first (MQTT self-delivery) — e.g. publishing `"0505"` yields a `"0505"` message. Any
genuine machine event (`DeviceError { code, description, state, type, value }`; `type` starting
`"host"`, firmware events `"ota_state"`) would follow that echo; none was emitted for a normal brew
within a few seconds. Collect the whole window, not just the first message, to separate echo from acks.

---

## 6. Device Shadow / state (for HA sensors)

**[V] Envelope.** `$aws/things/<thing>/shadow/get/accepted` returns the standard document:
`{ "state": { "reported": { … } }, "metadata": {…}, "version": <int>, "timestamp": <epoch> }`.
`update/documents` wraps changes under `{ "current": {…}, "previous": {…} }`. **All reported values
are JSON strings** (e.g. `"750"`, `"true"`), even numbers and booleans — parse accordingly.

**[V] Reported keys observed live (machine idle, 28 keys):**

- **Consumables:** `HopperReservoir` (beans), `WaterTank` + `WaterVolume`, `ResidueBin` +
  `ResidueBinCapacity` (grounds), `DripTray` + `DripTrayCapacity`, `WaterLineStatus`.
  Level enum (from source + live): `EMPTY, EMPTYORREMOVED, FULL, LEVEL0, LEVEL1, LEVEL2, OK, PLACED,
  REMOVED` — note **`LEVEL0`** (seen live) was not in the decompiled enum. `WaterLineStatus` e.g.
  `WL_CONNECTED`.
- **State:** `MachineStatus` `{READY, ACTIVE, STANDBY, CLEANING, EXPELL, PREPAREDRINK, MACHINEERROR,
  RECOVERING, RECOVERY, SPECIALTASK, INACTIVE, UNDEFINED}`; `ResetReason` e.g. `POWERON`.
  **[V] Brew lifecycle (observed live):** idle is `MachineStatus=INACTIVE` (asleep) or `ACTIVE`
  (awake) with `ProcessStatus=UNDEFINED`; during a brew `MachineStatus=PREPAREDRINK` and
  `ProcessStatus` steps through **`WAITFORBREWERFILLSPEED` → `WAITFOREXTRACTIONTIME`** (neither value
  is in the decompiled `ProcessStatuses` enum, which only had the `WAITFOR…` set in §5's source).
  During the pour `WaterVolume` falls, and `GrinderUserCounter`/`FilterCounter`/`DripTrayCapacity`/
  `ResidueBinCapacity` move; **no component-status keys appear** (they stayed absent at 28 keys even
  mid-brew, so `BrewerStatus` et al. are app-derived, not on the wire).
- **Brew bookkeeping:** `RecipeNumber`, `ShotCount`, `ColdbrewCounter`, `CoffeeCountersTtl`,
  `GrinderMasterCounter`, `GrinderUserCounter`, `FilterCounter`, `NoDeepCleanCounter`,
  `NoDescaleCounter`.
- **`recipes`** *(array of strings)* — the on-device cookbook. Each entry is a CSV of ~60 integers
  (one recipe/slot profile); `RecipeNumber` indexes into this table. This is the slot↔recipe source
  for brew commands (see §5). Live example had 8 entries, `RecipeNumber="5"`.
- **Telemetry/health:** `AirPressure`, `WiFiRssi`, `BleRssi`, `DRAM`, `IRAM`, `LiftMagnetPosition`.
  **Conn:** `connected` (`"true"`/`"false"`).
- **Component statuses** (`BrewerStatus, GrinderStatus, RingheaterStatus, SpinnMotorStatus,
  TransportMotorStatus, SpoutMotorStatus, FillingSystemStatus, WaterSystemStatus`) and the derived
  SDK flags (`isBrewing, isCleaning, …`, `brewingBlockers[]`) are defined in the app but were **not**
  present in the idle `reported` doc — they likely appear only while the machine is active. **[L]**

`Device` record also carries maintenance state: `last_cleaning_at`/`after_cleaning_cups_count_shadow`,
`last_descaling_at`/`after_descaling_cups_count_shadow`, `last_water_filter_changing_at`, `air_pressure`,
`serial_number`, `current_host_version`/`current_bridge_version`/`embedded_version`, `mac_sta`/`mac_bt`.

---

## 7. Verify-live checklist (small smoke test, [L] items)

1. ~~`Authorization: Bearer` header shape~~ — **[V] confirmed.**
2. ~~Brew sequence~~ — **[V] confirmed:** `SELECT_RECIPE`+slot then `PREPARE_RECIPE`+slot pours (§5).
3. ~~Slot byte base~~ — **[V] confirmed:** the slot byte equals the shadow `RecipeNumber` value (§5).
4. ~~Reported-shadow JSON envelope~~ — **[V] confirmed** (`state.reported`, all string values; §6).
5. ~~Active-brew shadow keys~~ — **[V] confirmed:** same 28 keys, no component statuses; `MachineStatus`/
   `ProcessStatus`/counters move (§6).

**Every item is now live-verified.** Remaining nice-to-haves: the exact machine ack/event JSON (none
seen for a normal brew beyond the self-echo), and `STOP`/`power`/`flush` behaviour (opcodes confirmed,
effects not individually exercised).

---

## 8. Feasibility

- **Tier 1 (app-free via Spinn cloud): [V] fully live-verified, read *and* write.** auth → `GET
  link/api/devices/{thing}` (thing + cert) → ATS MQTT mutual-TLS → read shadow *and* publish a brew to
  `<thing>/host` — all working end to end against a real machine. The DizzyCoffee client implements
  the whole of Tier 1; command publishing is confirmation-gated.
- **Tier 2 (no cloud) via a DNS redirect: [V] not possible.** The plan depended on the machine not
  verifying its broker's certificate, so that LAN DNS could send it to a local broker emulating the
  `$aws/things/…/shadow/…` + `<thing>/host` topics. Tested 2026-11-18 with
  [`tools/tls_probe.py`](../tools/tls_probe.py) ([TLS-PROBE.md](TLS-PROBE.md)), firmware 2.11.219:
  all 7 connections refused the probe's self-signed certificate with `TLSV1_ALERT_UNKNOWN_CA`. The
  machine verifies the chain against roots built into its firmware, so only a certificate from that
  CA would do, and nobody but Amazon can issue one. No local path exists in firmware for normal use.
  What's left would change the machine itself: firmware that trusts a different CA (needs flash
  access, and is only possible if flash encryption / secure boot aren't enabled), or a provisioning
  step that sets the broker and CA, if the setup flow has one (not seen in the app so far).

---

## 9. Implementation notes (Tier 1)

```python
# auth:  POST https://www.spinn.com/api/auth/login {email,password} -> token{access_token, refresh_token}
#        (refresh via POST auth/token with the stored token)
# device: GET https://iot.spinn.com/link/api/devices/<thing_name>  (Bearer access_token)  [V]
#   -> certificate.certificate_pem, certificate.certificate_private_key  (the list omits these)
# iot (awscrt/awsiotsdk):
mqtt = mqtt_connection_builder.mtls_from_bytes(
    endpoint="a1gzieuy3t1932-ats.iot.us-east-1.amazonaws.com",   # [V] ATS, not the shipped endpoint
    cert_bytes=pem.encode(), pri_key_bytes=private_key.encode(),
    ca_filepath=certifi.where(), client_id="dizzy-"+uuid4().hex)  # [V] certifi has Amazon Root CA 1
mqtt.subscribe(f"$aws/things/{thing}/shadow/update/documents", QoS.AT_LEAST_ONCE, on_shadow)
mqtt.subscribe(f"{thing}/host", QoS.AT_LEAST_ONCE, on_event)
mqtt.publish(f"$aws/things/{thing}/shadow/get", "", QoS.AT_LEAST_ONCE)   # read state (passive)
# mqtt.publish(f"{thing}/host", "0602", QoS.AT_LEAST_ONCE)               # brew slot 2 (ACTIVE — not in CLI)
```

HA shape (future): `custom_components/spinn/` — coordinator over the shadow; `button`/`select` to brew a
cookbook slot, `START`/`STOP`/`HOPPER_FLUSH`; `sensor`s for beans/water/grounds/tank, machine/process
status, shots, maintenance due; `binary_sensor` connected/brewing/error. Or a `home-assistant/pyscript/`
bridge. Secrets: the session token (cert is fetched fresh per session from `link/api/devices`).

> Publishing to `host` or `shadow/update` **actuates the machine** — only with you present and asking.
> Reading the shadow (`shadow/get`, `update/documents`) is passive and safe.
