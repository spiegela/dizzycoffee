"""Power switch: wake the machine or switch it off (ACTUATES the machine).

On means awake: any ``MachineStatus`` other than asleep / standby
(``INACTIVE``, ``STANDBY``). Turning it on sends ``SWITCH_ON``, off sends
``SWITCH_OFF`` (docs/PROTOCOL.md §5); the state then follows the shadow.

Disabled by default: the opcodes are confirmed from the app, but what they do
on the machine hasn't been live-verified yet. In particular, if ``SWITCH_OFF``
turned the machine fully off (Wi-Fi included), it couldn't be switched back on
remotely. Enable it from the device page once that has been checked.

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
    async_add_entities([SpinnPowerSwitch(coordinator)])


class SpinnPowerSwitch(SpinnEntity, SwitchEntity):
    """Wake / switch off the machine."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:power"
    _attr_entity_registry_enabled_default = False
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
