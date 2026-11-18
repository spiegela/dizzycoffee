"""Setup and unload create and remove every platform's entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.spinn.const import DOMAIN


async def test_setup_and_unload(hass: HomeAssistant, coordinator) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED

    platforms = {e.domain for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert platforms == {"sensor", "binary_sensor", "button", "select", "event", "switch"}

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
