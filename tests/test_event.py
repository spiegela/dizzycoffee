"""The Brew event entity fires on MachineStatus transitions."""
from __future__ import annotations

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .conftest import entity_id


async def _status(hass: HomeAssistant, coordinator, status: str, **extra: str) -> None:
    coordinator.async_set_updated_data({**coordinator.data, "MachineStatus": status, **extra})
    await hass.async_block_till_done()


async def test_started_then_finished(hass: HomeAssistant, coordinator) -> None:
    eid = entity_id(hass, "event", "brew_event")
    assert eid == "event.kitchen_spinn_brew"  # the id the README's example uses
    assert hass.states.get(eid).state == STATE_UNKNOWN
    assert hass.states.get(eid).attributes["event_types"] == ["started", "finished", "failed"]

    await _status(hass, coordinator, "PREPAREDRINK", RecipeNumber="4")
    state = hass.states.get(eid)
    assert state.attributes["event_type"] == "started"
    assert state.attributes["slot"] == 4
    assert state.attributes["recipe"] == "Coffee"
    assert state.attributes["recipe_id"] == "r-coffee"
    started_at = state.state

    # Non-status updates mid-brew don't fire anything.
    coordinator.async_set_updated_data({**coordinator.data, "WaterVolume": "600"})
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == started_at

    await _status(hass, coordinator, "ACTIVE")
    state = hass.states.get(eid)
    assert state.attributes["event_type"] == "finished"
    assert state.attributes["slot"] == 4
    assert state.attributes["recipe"] == "Coffee"
    assert state.attributes["duration_s"] >= 0


async def test_failed(hass: HomeAssistant, coordinator) -> None:
    eid = entity_id(hass, "event", "brew_event")
    await _status(hass, coordinator, "PREPAREDRINK")
    await _status(hass, coordinator, "MACHINEERROR")
    state = hass.states.get(eid)
    assert state.attributes["event_type"] == "failed"
    assert state.attributes["slot"] == 5
    assert state.attributes["recipe"] == "Lungo"


async def test_other_transitions_are_quiet(hass: HomeAssistant, coordinator) -> None:
    eid = entity_id(hass, "event", "brew_event")
    for status in ("INACTIVE", "ACTIVE", "CLEANING", "ACTIVE", "MACHINEERROR", "ACTIVE"):
        await _status(hass, coordinator, status)
    assert hass.states.get(eid).state == STATE_UNKNOWN


async def test_restart_mid_brew_fires_finished_only(hass: HomeAssistant, setup_spinn) -> None:
    coordinator = await setup_spinn(MachineStatus="PREPAREDRINK", RecipeNumber="4")
    eid = entity_id(hass, "event", "brew_event")
    assert hass.states.get(eid).state == STATE_UNKNOWN  # no "started" for a brew already under way

    await _status(hass, coordinator, "ACTIVE")
    state = hass.states.get(eid)
    assert state.attributes["event_type"] == "finished"
    assert state.attributes["slot"] == 4
    assert "duration_s" not in state.attributes  # start wasn't seen
