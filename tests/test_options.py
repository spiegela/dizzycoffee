"""Options flow (maintenance intervals) and entry updates that must not reload."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.spinn.const import CONF_TOKEN, DOMAIN


async def test_options_flow_sets_intervals_live(hass: HomeAssistant, coordinator) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    attention = "binary_sensor.kitchen_spinn_needs_attention"
    deep = "sensor.kitchen_spinn_cups_since_deep_clean"
    descale = "sensor.kitchen_spinn_cups_since_descale"

    # Defaults before any options are saved (counters are 12 and 40).
    assert hass.states.get(deep).attributes["interval"] == 100
    assert hass.states.get(descale).attributes["interval"] == 500
    assert hass.states.get(attention).state == STATE_OFF

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults == {"deep_clean_every": 100, "descale_every": 500}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"deep_clean_every": 10.0, "descale_every": 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options == {"deep_clean_every": 10, "descale_every": 0}
    assert hass.data[DOMAIN][entry.entry_id] is coordinator  # not reloaded
    assert hass.states.get(deep).attributes["interval"] == 10
    assert hass.states.get(descale).attributes["interval"] == 0
    state = hass.states.get(attention)
    assert state.state == STATE_ON
    assert state.attributes["reasons"] == ["deep_clean_due"]

    # The form now starts from the saved values.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults == {"deep_clean_every": 10, "descale_every": 0}


async def test_token_rotation_does_not_reload(hass: HomeAssistant, coordinator) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_TOKEN: {"access_token": "new", "refresh_token": "new"}}
    )
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN][entry.entry_id] is coordinator
