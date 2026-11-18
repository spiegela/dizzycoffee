"""The Power switch: enabled, state from MachineStatus, guarded commands."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.spinn.const import DOMAIN

from .conftest import THING

POWER = "switch.kitchen_spinn_power"


async def _set(hass: HomeAssistant, coordinator, **changes: str) -> None:
    coordinator.async_set_updated_data({**coordinator.data, **changes})
    await hass.async_block_till_done()


async def _call(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        "switch", service, {"entity_id": POWER}, blocking=True
    )


async def test_enabled_by_default(hass: HomeAssistant, coordinator) -> None:
    entry = er.async_get(hass).async_get(POWER)
    assert entry is not None and entry.disabled_by is None
    assert hass.states.get(POWER).state == STATE_ON


async def test_reenables_switch_an_earlier_build_disabled(hass: HomeAssistant, setup_spinn) -> None:
    def before(entry) -> None:
        er.async_get(hass).async_get_or_create(
            "switch", DOMAIN, f"{THING}_power", config_entry=entry,
            suggested_object_id="kitchen_spinn_power",
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        )

    await setup_spinn(before=before)
    assert er.async_get(hass).async_get(POWER).disabled_by is None
    assert hass.states.get(POWER).state == STATE_ON


async def test_leaves_user_disabled_switch_alone(hass: HomeAssistant, setup_spinn) -> None:
    def before(entry) -> None:
        er.async_get(hass).async_get_or_create(
            "switch", DOMAIN, f"{THING}_power", config_entry=entry,
            suggested_object_id="kitchen_spinn_power",
            disabled_by=er.RegistryEntryDisabler.USER,
        )

    await setup_spinn(before=before)
    assert er.async_get(hass).async_get(POWER).disabled_by is er.RegistryEntryDisabler.USER
    assert hass.states.get(POWER) is None


async def test_state_follows_machine_status(hass: HomeAssistant, coordinator) -> None:
    eid = POWER
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
    hass: HomeAssistant, coordinator
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
    hass: HomeAssistant, coordinator
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
