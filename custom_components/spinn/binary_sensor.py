"""Binary sensors: connectivity, brewing, cleaning, error, and needs attention."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import attention
from .const import DOMAIN
from .coordinator import SpinnCoordinator
from .entity import SpinnEntity


@dataclass(frozen=True, kw_only=True)
class SpinnBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor description with an is_on extractor."""

    is_on_fn: Callable[[dict[str, Any]], bool | None]


def _connected(data: dict[str, Any]) -> bool | None:
    val = data.get("connected")
    if val in (None, ""):
        return None
    return str(val).lower() == "true"


BINARY_SENSORS: tuple[SpinnBinarySensorEntityDescription, ...] = (
    SpinnBinarySensorEntityDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_connected,
    ),
    SpinnBinarySensorEntityDescription(
        key="brewing",
        translation_key="brewing",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:coffee-to-go",
        # docs/PROTOCOL.md §6 [V]: MachineStatus == PREPAREDRINK during a pour.
        is_on_fn=lambda d: (d.get("MachineStatus") == "PREPAREDRINK") if d.get("MachineStatus") else None,
    ),
    SpinnBinarySensorEntityDescription(
        key="cleaning",
        translation_key="cleaning",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:spray-bottle",
        # CLEANING = rinse/clean cycle; EXPELL = puck/grounds expulsion.
        is_on_fn=lambda d: (d.get("MachineStatus") in ("CLEANING", "EXPELL")) if d.get("MachineStatus") else None,
    ),
    SpinnBinarySensorEntityDescription(
        key="error",
        translation_key="error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda d: (d.get("MachineStatus") == "MACHINEERROR") if d.get("MachineStatus") else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinnCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            *(SpinnBinarySensor(coordinator, desc) for desc in BINARY_SENSORS),
            SpinnAttentionBinarySensor(coordinator),
        ]
    )


class SpinnBinarySensor(SpinnEntity, BinarySensorEntity):
    """A single shadow-backed binary sensor."""

    entity_description: SpinnBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: SpinnCoordinator,
        description: SpinnBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.thing}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.coordinator.data or {})


class SpinnAttentionBinarySensor(SpinnEntity, BinarySensorEntity):
    """On when something needs doing: refill, empty, put back, clean, or an error.

    Attributes: ``reasons`` (what turned it on) and ``warnings`` (low / nearly
    full heads-ups that don't), as stable keys; see attention.py.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    entity_description = BinarySensorEntityDescription(
        key="needs_attention", translation_key="needs_attention"
    )

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.thing}_needs_attention"

    @property
    def is_on(self) -> bool:
        return attention.evaluate(self.coordinator.data).needed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = attention.evaluate(self.coordinator.data)
        return {"reasons": result.reasons, "warnings": result.warnings}
