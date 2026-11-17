"""Constants for the Spinn coffee maker integration.

The integration is a thin Home Assistant wrapper over the live-verified
``dizzycoffee`` package (REST auth + device/cert fetch, AWS IoT shadow read,
and the opt-in command path). See ``docs/PROTOCOL.md`` for the protocol and the
``[V]`` live-verified facts this integration relies on.
"""
from __future__ import annotations

DOMAIN = "spinn"

PLATFORMS: list[str] = ["sensor", "binary_sensor", "button", "select"]

# Config-entry keys.
CONF_EMAIL = "email"
CONF_PASSWORD = "password"  # only used transiently in the flow; never stored
CONF_TOKEN = "token"  # the Spinn session token dict (access_token + refresh_token)
CONF_THING_NAME = "thing_name"
CONF_DEVICE_NAME = "device_name"

# Backend endpoints — mirror ``dizzycoffee.config`` defaults so this module does
# not have to import the library at import time (keeps the integration importable
# for structural checks even when the library isn't on the path yet). See
# docs/PROTOCOL.md §1: we deliberately use the ATS IoT endpoint, not the legacy
# one the app ships (its server cert chains to a root modern trust stores dropped).
DEFAULT_MP_BASE = "https://www.spinn.com/api/"
DEFAULT_IOT_BASE = "https://iot.spinn.com/"
DEFAULT_IOT_ENDPOINT = "a1gzieuy3t1932-ats.iot.us-east-1.amazonaws.com"

MANUFACTURER = "Spinn"

# Fallback poll interval (seconds). Normal operation is push via the AWS IoT
# shadow ``update/documents`` stream; this is a safety-net re-read that also
# refreshes the device record (and rotates the fetched certificate).
UPDATE_INTERVAL_SECONDS = 120

# Lovelace dashboard cards (served by the integration; see frontend/).
CARD_VERSION = "0.3.0"
FRONTEND_URL_BASE = f"/{DOMAIN}_cards"
FRONTEND_SCRIPT = "spinn-card.js"
