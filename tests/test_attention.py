"""The Needs attention rules (pure functions) and the binary sensor built on them."""
from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.spinn import attention

from .conftest import SHADOW, entity_id


def test_healthy_machine_needs_nothing() -> None:
    result = attention.evaluate(SHADOW)
    assert result.reasons == []
    assert result.warnings == []
    assert not result.needed


def test_empty_full_and_removed() -> None:
    result = attention.evaluate(
        {
            **SHADOW,
            "WaterTank": "EMPTY",
            "HopperReservoir": "EMPTYORREMOVED",
            "ResidueBin": "FULL",
            "DripTray": "REMOVED",
        }
    )
    assert result.reasons == [
        "water_tank_empty",
        "beans_empty",
        "grounds_bin_full",
        "drip_tray_removed",
    ]
    assert result.needed


def test_low_levels_are_warnings_only() -> None:
    result = attention.evaluate(
        {**SHADOW, "WaterTank": "LEVEL0", "HopperReservoir": "level0", "DripTray": "LEVEL2"}
    )
    assert result.reasons == []
    assert result.warnings == ["water_tank_low", "beans_low", "drip_tray_nearly_full"]
    assert not result.needed


def test_maintenance_due_at_threshold() -> None:
    result = attention.evaluate({**SHADOW, "NoDeepCleanCounter": "100", "NoDescaleCounter": "499"})
    assert result.reasons == ["deep_clean_due"]
    result = attention.evaluate(
        {**SHADOW, "NoDescaleCounter": "20"}, descale_every=20, deep_clean_every=0
    )
    assert result.reasons == ["descale_due"]


def test_machine_error_and_missing_values() -> None:
    assert attention.evaluate({"MachineStatus": "MACHINEERROR"}).reasons == ["machine_error"]
    assert attention.evaluate({}).reasons == []
    assert attention.evaluate(None).reasons == []
    assert attention.evaluate({"NoDescaleCounter": "n/a"}).reasons == []


def test_describe() -> None:
    assert attention.describe([]) == ""
    assert attention.describe(["water_tank_empty"]) == "the water tank is empty"
    assert (
        attention.describe(["water_tank_empty", "drip_tray_full", "descale_due"])
        == "the water tank is empty, the drip tray is full and descaling is due"
    )
    assert attention.describe(["something_new"]) == "something new"


async def test_binary_sensor(hass: HomeAssistant, coordinator) -> None:
    eid = entity_id(hass, "binary_sensor", "needs_attention")
    assert eid == "binary_sensor.kitchen_spinn_needs_attention"
    state = hass.states.get(eid)
    assert state.state == STATE_OFF
    assert state.attributes["reasons"] == []
    assert state.attributes["device_class"] == "problem"

    coordinator.async_set_updated_data(
        {**coordinator.data, "WaterTank": "EMPTY", "DripTray": "FULL", "HopperReservoir": "LEVEL0"}
    )
    await hass.async_block_till_done()
    state = hass.states.get(eid)
    assert state.state == STATE_ON
    assert state.attributes["reasons"] == ["water_tank_empty", "drip_tray_full"]
    assert state.attributes["warnings"] == ["beans_low"]
