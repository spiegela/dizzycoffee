"""Brew event: fires when a drink starts, finishes, or fails.

Derived from ``MachineStatus`` transitions in the shadow (docs/PROTOCOL.md §6:
``PREPAREDRINK`` while pouring), so it fires for brews started anywhere: the
machine's own buttons, the Spinn app, or Home Assistant.

* ``started``  — status changed to ``PREPAREDRINK``
* ``finished`` — status left ``PREPAREDRINK`` for anything but an error
  (pressing Stop mid-brew also lands here)
* ``failed``   — status went from ``PREPAREDRINK`` to ``MACHINEERROR``

Event data: ``slot``, ``recipe``, ``recipe_id`` and, for finished / failed,
``duration_s`` (when the start was seen).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import SpinnCoordinator
from .entity import SpinnEntity

BREWING = "PREPAREDRINK"
ERROR = "MACHINEERROR"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinnCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SpinnBrewEvent(coordinator)])


def _slot(data: dict[str, Any]) -> int | None:
    val = data.get("RecipeNumber")
    if val in (None, ""):
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


class SpinnBrewEvent(SpinnEntity, EventEntity):
    """Fires ``started`` / ``finished`` / ``failed`` as drinks are made."""

    _attr_icon = "mdi:coffee-outline"
    _attr_event_types = ["started", "finished", "failed"]
    entity_description = EventEntityDescription(key="brew_event", translation_key="brew")

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.thing}_brew_event"
        # Seed from the current state so a restart mid-brew doesn't fire
        # "started"; it still fires "finished" when that brew ends.
        data = coordinator.data or {}
        self._status: str | None = data.get("MachineStatus") or None
        self._slot: int | None = _slot(data) if self._status == BREWING else None
        self._started_at: datetime | None = None

    def _recipe_data(self, slot: int | None) -> dict[str, Any]:
        item = self.coordinator.slot_recipe(slot) or {}
        return {"slot": slot, "recipe": item.get("name"), "recipe_id": item.get("recipe_id")}

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        status = data.get("MachineStatus") or None
        prev = self._status
        if status is not None:
            self._status = status

        if status is not None and prev is not None and status != prev:
            if status == BREWING:
                self._slot = _slot(data)
                self._started_at = dt_util.utcnow()
                self._trigger_event("started", self._recipe_data(self._slot))
            elif prev == BREWING:
                event_data = self._recipe_data(self._slot)
                if self._started_at is not None:
                    event_data["duration_s"] = round(
                        (dt_util.utcnow() - self._started_at).total_seconds()
                    )
                self._trigger_event("failed" if status == ERROR else "finished", event_data)
                self._slot = None
                self._started_at = None

        super()._handle_coordinator_update()
