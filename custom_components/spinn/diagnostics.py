"""Diagnostics download (Settings → Devices & Services → Spinn → ⋮ → Download diagnostics).

What's in it: the live shadow (machine state), the REST device record, the
installed cookbook, the recipe catalog summary, connection status, what the
Needs attention sensor sees, and a live read of the account's usage stats
endpoints (whose response shapes aren't documented yet). Enough to debug
someone else's machine or firmware variant from an issue report.

What's taken out: the session token, email, the device certificate and private
key, serial number, MAC addresses, Wi-Fi details, and the machine's thing name
(also scrubbed from inside other values, e.g. topics). The device record's
fields aren't fully documented, so redaction matches key *patterns*
(anything mentioning token, cert, private, email, serial, ...), not just known
keys. The shadow's keys are all known machine readings, so only the thing name
is scrubbed there.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CARD_VERSION, CONF_THING_NAME, DOMAIN
from .coordinator import SpinnCoordinator

REDACTED = "**REDACTED**"
THING = "**THING**"

# Exact keys (lower-cased) to redact wherever they appear.
_REDACT_KEYS = {
    "thing_name",
    "thingname",
    "ip",
    "ip_address",
    "ssid",
    "bssid",
    "latitude",
    "longitude",
    "address",
    "phone",
    "owner",
    "owner_id",
    "user_id",
    "account_id",
}
# Substrings: any key containing one of these (lower-cased) is redacted.
_REDACT_PARTS = (
    "token",
    "cert",
    "private",
    "password",
    "secret",
    "email",
    "serial",
    "mac_",
    "wifi_",
    "share",
)

def _should_redact(key: Any) -> bool:
    k = str(key).lower()
    return k in _REDACT_KEYS or any(part in k for part in _REDACT_PARTS)


def _redact(obj: Any, thing: str, *, keys: bool = True) -> Any:
    """Recursively redact sensitive keys and scrub the thing name from values."""
    if isinstance(obj, dict):
        return {
            k: (REDACTED if keys and _should_redact(k) and v not in (None, "") else _redact(v, thing, keys=keys))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(v, thing, keys=keys) for v in obj]
    if isinstance(obj, str) and thing and thing in obj:
        return obj.replace(thing, THING)
    return obj


def _dizzycoffee_source() -> dict[str, Any]:
    try:
        import dizzycoffee  # lazy; made importable by vendor.ensure_dizzycoffee
    except ImportError:
        return {"importable": False}
    path = getattr(dizzycoffee, "__file__", "") or ""
    return {
        "importable": True,
        "source": "bundled" if "_vendor" in path else "installed",
        "version": getattr(dizzycoffee, "__version__", None),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator: SpinnCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    thing = entry.data.get(CONF_THING_NAME, "")
    integration = await async_get_integration(hass, DOMAIN)

    result: dict[str, Any] = {
        "integration": {
            "version": str(integration.version) if integration.version else None,
            "card_version": CARD_VERSION,
            "dizzycoffee": _dizzycoffee_source(),
        },
        "entry": {
            "title": _redact(entry.title, thing),
            "data": _redact(dict(entry.data), thing),
        },
    }
    if coordinator is None:
        result["coordinator"] = None
        return result

    stream = getattr(coordinator, "_stream", None)
    last_exc = coordinator.last_exception
    seen = coordinator.current_attention()
    result["coordinator"] = {
        "last_update_success": coordinator.last_update_success,
        "last_exception": _redact(repr(last_exc), thing) if last_exc else None,
        "push_stream_connected": bool(stream and stream.connected),
        "update_interval_s": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
        "selected_slot": coordinator.selected_slot,
        "deep_clean_every": coordinator.deep_clean_every,
        "descale_every": coordinator.descale_every,
    }
    result["attention"] = {"reasons": seen.reasons, "warnings": seen.warnings}
    result["shadow"] = _redact(dict(coordinator.data or {}), thing, keys=False)
    result["device"] = _redact(dict(coordinator.device or {}), thing)
    result["cookbook"] = _redact(list(coordinator.cookbook), thing)
    result["catalog"] = _redact(list(coordinator.catalog), thing)
    result["stats"] = _redact(await coordinator.async_fetch_stats(), thing)
    return result
