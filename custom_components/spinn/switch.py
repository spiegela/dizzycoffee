"""Power switch: wake the machine or switch it off (ACTUATES the machine).

On means awake: any ``MachineStatus`` other than asleep / standby
(``INACTIVE``, ``STANDBY``). Turning it on sends ``SWITCH_ON``, off sends
``SWITCH_OFF`` (docs/PROTOCOL.md §5); the state then follows the shadow.

Live-verified 2026-11-18 (docs/PROTOCOL.md §5): ``SWITCH_OFF`` puts the machine
to sleep (``MachineStatus`` ``INACTIVE``) while it stays connected, and
``SWITCH_ON`` wakes it (panel lights back on), so it can be switched back on
remotely.

Unavailable while the machine is offline, since commands are refused then.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ASLEEP_STATUSES, DOMAIN
from .coordinator import SpinnCoordinator
from .entity import SpinnEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinnCoordinator = hass.data[DOMAIN][entry.entry_id]
    _enable_if_disabled_by_us(hass, coordinator)
    async_add_entities([SpinnPowerSwitch(coordinator)])


def _enable_if_disabled_by_us(hass: HomeAssistant, coordinator: SpinnCoordinator) -> None:
    """Enable a Power switch that an earlier build registered as disabled.

    Pre-release builds of 0.4.0 shipped the switch disabled until the power
    opcodes were verified. Changing the default only affects new entities, so
    re-enable ours here. One the user disabled (disabled_by=USER) stays off.
    Like enabling it in the UI, this makes Home Assistant reload the entry once,
    about 30 s later.
    """
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{coordinator.thing}_power")
    if entity_id is None:
        return
    entry = registry.async_get(entity_id)
    if entry is not None and entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
        registry.async_update_entity(entity_id, disabled_by=None)


class SpinnPowerSwitch(SpinnEntity, SwitchEntity):
    """Wake / switch off the machine."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:power"
    entity_description = SwitchEntityDescription(key="power", translation_key="power")

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.thing}_power"

    @property
    def available(self) -> bool:
        connected = str((self.coordinator.data or {}).get("connected", "")).lower()
        return super().available and connected != "false"

    @property
    def is_on(self) -> bool | None:
        status = (self.coordinator.data or {}).get("MachineStatus")
        if not status or status == "UNDEFINED":
            return None
        return status not in ASLEEP_STATUSES

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_power(False)
