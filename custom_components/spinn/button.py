"""Buttons — the explicit write path (ACTUATE the machine).

Every press here publishes to ``<thing>/host`` via
``dizzycoffee.commands.DeviceCommander``. This is the ONLY platform that
actuates; sensors/binary_sensors/select are read-only or local-only.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SpinnCoordinator
from .entity import SpinnEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinnCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            SpinnBrewButton(coordinator),
            SpinnStartButton(coordinator),
            SpinnStopButton(coordinator),
            SpinnFlushButton(coordinator),
        ]
    )


class _SpinnButton(SpinnEntity, ButtonEntity):
    def __init__(self, coordinator: SpinnCoordinator, key: str, translation_key: str) -> None:
        super().__init__(coordinator)
        self.entity_description = ButtonEntityDescription(
            key=key, translation_key=translation_key
        )
        self._attr_unique_id = f"{coordinator.thing}_{key}"


class SpinnBrewButton(_SpinnButton):
    """Brew the currently-selected cookbook slot (SELECT + PREPARE)."""

    _attr_icon = "mdi:coffee-maker"

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator, "brew", "brew")

    def _resolve_slot(self) -> int:
        slot = self.coordinator.selected_slot
        if slot is None:
            rn = (self.coordinator.data or {}).get("RecipeNumber")
            try:
                slot = int(float(rn)) if rn not in (None, "") else None
            except (TypeError, ValueError):
                slot = None
        if slot is None:
            raise HomeAssistantError(
                "No recipe slot selected. Pick one with the Recipe Slot selector first."
            )
        return slot

    async def async_press(self) -> None:
        slot = self._resolve_slot()
        _LOGGER.debug("Brewing Spinn recipe slot %s", slot)
        await self.coordinator.async_brew(slot)


class SpinnStartButton(_SpinnButton):
    _attr_icon = "mdi:play"

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator, "start", "start")

    async def async_press(self) -> None:
        await self.coordinator.async_start()


class SpinnStopButton(_SpinnButton):
    _attr_icon = "mdi:stop"

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator, "stop", "stop")

    async def async_press(self) -> None:
        await self.coordinator.async_stop()


class SpinnFlushButton(_SpinnButton):
    _attr_icon = "mdi:water-sync"

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator, "hopper_flush", "hopper_flush")

    async def async_press(self) -> None:
        await self.coordinator.async_flush()
