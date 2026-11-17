"""Recipe-slot selector.

This is a LOCAL picker: choosing a slot only records which slot the Brew button
will use — it does NOT actuate the machine (the write path stays on buttons).
Options are derived from the shadow ``recipes`` array; the current value defaults
to the machine's ``RecipeNumber``.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SpinnCoordinator
from .entity import SpinnEntity

# Brewable cookbook slots 0..6 (slot 7 is the app's temporary one-off slot).
_BREWABLE = 7


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinnCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SpinnRecipeSelect(coordinator)])


class SpinnRecipeSelect(SpinnEntity, SelectEntity):
    """Pick which cookbook slot the Brew button targets."""

    _attr_icon = "mdi:format-list-numbered"
    entity_description = SelectEntityDescription(
        key="recipe_slot", translation_key="recipe_slot"
    )

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.thing}_recipe_slot"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # The installed cookbook (slot -> name/size), used by the Lovelace cards.
        # Options stay as slot numbers so existing automations keep working.
        cb = self.coordinator.cookbook
        current = self.current_option
        return {
            "recipe_name": self.coordinator.slot_name(int(current)) if current else None,
            "recipes": [
                {k: item.get(k) for k in ("slot", "role", "recipe_id", "name", "slug", "type", "drink_size", "shots", "cold")}
                for item in cb
            ],
        }

    @property
    def options(self) -> list[str]:
        # Slot byte = 0-based cookbook index = shadow RecipeNumber. Slots 0-6 are
        # installed recipes (0-3 user, 4/5/6 tall/medium/small buttons); slot 7 is
        # the app's temporary one-off slot and isn't offered here. We always include
        # the machine's current RecipeNumber so the list covers the active slot.
        n = min(len(self.coordinator.cookbook), _BREWABLE) if self.coordinator.cookbook else _BREWABLE
        slots = {str(i) for i in range(0, n)}
        rn = (self.coordinator.data or {}).get("RecipeNumber")
        if rn not in (None, ""):
            try:
                slots.add(str(int(float(rn))))
            except (TypeError, ValueError):
                pass
        return sorted(slots, key=lambda s: int(s))

    @property
    def current_option(self) -> str | None:
        if self.coordinator.selected_slot is not None:
            return str(self.coordinator.selected_slot)
        rn = (self.coordinator.data or {}).get("RecipeNumber")
        if rn in (None, ""):
            return None
        try:
            return str(int(float(rn)))
        except (TypeError, ValueError):
            return None

    async def async_select_option(self, option: str) -> None:
        # Local only — records the choice for the Brew button; no MQTT publish.
        self.coordinator.selected_slot = int(option)
        self.async_write_ha_state()
