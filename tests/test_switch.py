"""The Power switch: disabled by default, state from MachineStatus, guarded commands."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.spinn.const import DOMAIN
from custom_components.spinn.switch import SpinnPowerSwitch

from .conftest import THING


@pytest.fixture
def power_enabled():
    """Enable the (default-disabled) Power switch for a test."""
    with patch.object(SpinnPowerSwitch, "_attr_entity_registry_enabled_default", True):
        yield


async def _set(hass: HomeAssistant, coordinator, **changes: str) -> None:
    coordinator.async_set_updated_data({**coordinator.data, **changes})
    await hass.async_block_till_done()


async def _call(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        "switch", service, {"entity_id": "switch.kitchen_spinn_power"}, blocking=True
    )


async def test_disabled_by_default(hass: HomeAssistant, coordinator) -> None:
    entry = er.async_get(hass).async_get(
        er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{THING}_power")
    )
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("switch.kitchen_spinn_power") is None


async def test_state_follows_machine_status(hass: HomeAssistant, power_enabled, coordinator) -> None:
    eid = "switch.kitchen_spinn_power"
    assert hass.states.get(eid).state == STATE_ON  # ACTIVE

    for status, expected in (
        ("INACTIVE", STATE_OFF),
        ("STANDBY", STATE_OFF),
        ("PREPAREDRINK", STATE_ON),
        ("UNDEFINED", STATE_UNKNOWN),
    ):
        await _set(hass, coordinator, MachineStatus=status)
        assert hass.states.get(eid).state == expected, status

    await _set(hass, coordinator, MachineStatus="ACTIVE", connected="false")
    assert hass.states.get(eid).state == STATE_UNAVAILABLE


async def test_turn_on_and_off_send_power_opcodes(
    hass: HomeAssistant, power_enabled, coordinator
) -> None:
    await _set(hass, coordinator, MachineStatus="INACTIVE")
    with patch.object(coordinator, "_send_blocking") as send:
        await _call(hass, "turn_on")
    assert [(int(c), p) for c, p in send.call_args.args[0]] == [(1, None)]  # SWITCH_ON

    await _set(hass, coordinator, MachineStatus="ACTIVE")
    with patch.object(coordinator, "_send_blocking") as send:
        await _call(hass, "turn_off")
    assert [(int(c), p) for c, p in send.call_args.args[0]] == [(2, None)]  # SWITCH_OFF


async def test_turn_off_refused_while_brewing(
    hass: HomeAssistant, power_enabled, coordinator
) -> None:
    await _set(hass, coordinator, MachineStatus="PREPAREDRINK")
    with patch.object(coordinator, "_send_blocking") as send:
        with pytest.raises(HomeAssistantError, match="brewing; wait for it to finish before you switch it off"):
            await _call(hass, "turn_off")
        await _call(hass, "turn_on")  # waking a busy machine is harmless
    assert send.call_count == 1


async def test_power_refused_offline(hass: HomeAssistant, coordinator) -> None:
    # The entity is unavailable offline; the coordinator guard backs that up.
    await _set(hass, coordinator, connected="false")
    with patch.object(coordinator, "_send_blocking") as send:
        with pytest.raises(HomeAssistantError, match="offline"):
            await coordinator.async_power(True)
    send.assert_not_called()
