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


def test_bin_fill_from_space_left() -> None:
    # Space left counts down from 100 (grounds) / 300 (drip tray) as the bins fill.
    assert attention.waste_fill(SHADOW, "ResidueBinCapacity") == 0.0
    assert attention.waste_fill({"ResidueBinCapacity": "86"}, "ResidueBinCapacity") == 0.14
    assert attention.waste_fill({"DripTrayCapacity": "270"}, "DripTrayCapacity") == 0.1
    assert attention.waste_fill({"DripTrayCapacity": "0"}, "DripTrayCapacity") == 1.0
    assert attention.waste_fill({"DripTrayCapacity": "-5"}, "DripTrayCapacity") == 1.0
    assert attention.waste_fill({}, "DripTrayCapacity") is None
    assert attention.waste_fill({"DripTrayCapacity": "?"}, "DripTrayCapacity") is None
    # Above an empty bin's value doesn't fit the model: unknown, not "0 % full".
    assert attention.waste_fill({"ResidueBinCapacity": "120"}, "ResidueBinCapacity") is None
    assert attention.waste_fill({"OtherCapacity": "5"}, "OtherCapacity") is None


def test_bins_full_and_nearly_full_from_space_left() -> None:
    result = attention.evaluate({**SHADOW, "ResidueBinCapacity": "20", "DripTrayCapacity": "61"})
    assert result.reasons == []
    assert result.warnings == ["grounds_bin_nearly_full"]  # 80 % full; the tray is 79.7 %

    result = attention.evaluate({**SHADOW, "ResidueBinCapacity": "0", "DripTrayCapacity": "30"})
    assert result.reasons == ["grounds_bin_full"]
    assert result.warnings == ["drip_tray_nearly_full"]

    # Removed wins over the counter; the enum's FULL still counts on its own.
    result = attention.evaluate({**SHADOW, "ResidueBin": "REMOVED", "ResidueBinCapacity": "0", "DripTray": "FULL"})
    assert result.reasons == ["grounds_bin_removed", "drip_tray_full"]


async def test_bin_level_sensors(hass: HomeAssistant, coordinator) -> None:
    grounds = "sensor.kitchen_spinn_grounds_bin_level"
    tray = "sensor.kitchen_spinn_drip_tray_level"
    assert hass.states.get(grounds).state == "0"
    assert hass.states.get(grounds).attributes["unit_of_measurement"] == "%"
    assert hass.states.get(tray).state == "0"

    coordinator.async_set_updated_data(
        {**coordinator.data, "ResidueBinCapacity": "86", "DripTrayCapacity": "30"}
    )
    await hass.async_block_till_done()
    assert hass.states.get(grounds).state == "14"
    assert hass.states.get(tray).state == "90"

    # A reading above an empty bin's value is shown as unknown, not as empty.
    coordinator.async_set_updated_data({**coordinator.data, "DripTrayCapacity": "310"})
    await hass.async_block_till_done()
    assert hass.states.get(tray).state == "unknown"
    coordinator.async_set_updated_data({**coordinator.data, "DripTrayCapacity": "30"})
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.kitchen_spinn_needs_attention")
    assert state.attributes["warnings"] == ["drip_tray_nearly_full"]


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
