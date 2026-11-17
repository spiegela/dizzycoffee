"""The Spinn coffee maker integration.

Local-ish, app-free control of a Spinn bean-to-cup machine via the
live-verified ``dizzycoffee`` protocol client (auth -> device/cert fetch ->
AWS IoT shadow). Read is passive; the write path is exposed only as buttons.
"""
from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CARD_VERSION,
    DOMAIN,
    FRONTEND_SCRIPT,
    FRONTEND_URL_BASE,
    PLATFORMS,
)
from .vendor import ensure_dizzycoffee

# Make the bundled `dizzycoffee` client importable before anything uses it.
# Importing a submodule (e.g. config_flow) imports this package first, so this
# runs ahead of every lazy `import dizzycoffee` in the integration.
ensure_dizzycoffee()

from .coordinator import SpinnCoordinator  # noqa: E402  (after ensure_dizzycoffee)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Spinn from a config entry."""
    # Serve/register the Lovelace cards early so they're available even if the
    # first refresh has to retry (e.g. the machine is briefly unreachable).
    await _async_register_frontend(hass)

    coordinator = SpinnCoordinator(hass, entry)

    # First refresh does the auth + device/cert fetch + initial shadow read. A
    # failure raises ConfigEntryAuthFailed (-> reauth) or ConfigEntryNotReady.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and register the Lovelace cards bundled under frontend/.

    Serves frontend/ at FRONTEND_URL_BASE and adds the card module to the
    frontend so `custom:spinn-machine-card` / `custom:spinn-recipe-card` are
    available on every dashboard — no manual resource step. Best-effort: a
    failure here never blocks the integration (cards can still be added as a
    Lovelace resource manually). Runs once per HA process.
    """
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("_frontend_registered"):
        return
    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig

        frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_BASE, frontend_dir, False)]
        )
        add_extra_js_url(hass, f"{FRONTEND_URL_BASE}/{FRONTEND_SCRIPT}?v={CARD_VERSION}")
        data["_frontend_registered"] = True
        _LOGGER.debug("Registered Spinn Lovelace cards at %s", FRONTEND_URL_BASE)
    except Exception:  # noqa: BLE001 - frontend is a nicety, not required
        _LOGGER.warning(
            "Could not auto-register the Spinn Lovelace cards; add %s/%s as a "
            "dashboard resource manually if you want them.",
            FRONTEND_URL_BASE,
            FRONTEND_SCRIPT,
            exc_info=True,
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: SpinnCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None:
        await coordinator.async_shutdown_stream()
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options/data change."""
    await hass.config_entries.async_reload(entry.entry_id)
