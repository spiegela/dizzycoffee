"""Base entity for the Spinn integration."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import SpinnCoordinator


class SpinnEntity(CoordinatorEntity[SpinnCoordinator]):
    """Common device info + availability for all Spinn entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = _device_info(coordinator)

    @property
    def available(self) -> bool:
        """Available while the coordinator is updating successfully."""
        return super().available and bool(self.coordinator.data)


def _device_info(coordinator: SpinnCoordinator) -> DeviceInfo:
    dev: dict[str, Any] = coordinator.device or {}
    name = dev.get("name") or "Spinn"
    sw = dev.get("current_host_version") or dev.get("embedded_version")
    model = dev.get("model") or "Spinn Coffee Maker"
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.thing)},
        manufacturer=MANUFACTURER,
        name=name,
        model=model,
        serial_number=dev.get("serial_number"),
        sw_version=str(sw) if sw else None,
    )
