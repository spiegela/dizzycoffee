"""Sensors for the Spinn coffee maker (read from the AWS IoT shadow).

Every shadow value is a JSON string (docs/PROTOCOL.md §6); numeric sensors coerce
via ``value_fn``. Sensors for keys that are only present while the machine is
active simply report ``None`` (unknown) when the key is absent.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import SpinnCoordinator
from .entity import SpinnEntity


def _str(data: dict[str, Any], key: str) -> str | None:
    val = data.get(key)
    if val in (None, ""):
        return None
    return str(val)


def _int(data: dict[str, Any], key: str) -> int | None:
    val = data.get(key)
    if val in (None, ""):
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _timestamp(data: dict[str, Any], key: str) -> datetime | None:
    val = data.get(key)
    if not val:
        return None
    parsed = dt_util.parse_datetime(str(val))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return parsed


@dataclass(frozen=True, kw_only=True)
class SpinnSensorEntityDescription(SensorEntityDescription):
    """Sensor description with a value extractor.

    ``value_fn`` reads the shadow ``reported`` dict by default; with
    ``from_device=True`` it reads the REST device record instead
    (``GET link/api/devices/{thing}`` — maintenance timestamps etc.).
    """

    value_fn: Callable[[dict[str, Any]], Any]
    from_device: bool = False
    # Extra state attributes computed from the coordinator (e.g. the configured
    # maintenance interval on the cups-since counters).
    attrs_fn: Callable[[SpinnCoordinator], dict[str, Any]] | None = None


SENSORS: tuple[SpinnSensorEntityDescription, ...] = (
    # --- state ---
    SpinnSensorEntityDescription(
        key="MachineStatus",
        translation_key="machine_status",
        icon="mdi:coffee-maker",
        value_fn=lambda d: _str(d, "MachineStatus"),
    ),
    SpinnSensorEntityDescription(
        key="ProcessStatus",
        translation_key="process_status",
        icon="mdi:progress-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _str(d, "ProcessStatus"),
    ),
    # --- consumables ---
    SpinnSensorEntityDescription(
        key="HopperReservoir",
        translation_key="beans",
        icon="mdi:coffee",
        value_fn=lambda d: _str(d, "HopperReservoir"),
    ),
    SpinnSensorEntityDescription(
        key="WaterTank",
        translation_key="water_tank",
        icon="mdi:cup-water",
        value_fn=lambda d: _str(d, "WaterTank"),
    ),
    SpinnSensorEntityDescription(
        key="WaterVolume",
        translation_key="water_volume",
        icon="mdi:water",
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _int(d, "WaterVolume"),
    ),
    SpinnSensorEntityDescription(
        key="WaterLineStatus",
        translation_key="water_line_status",
        icon="mdi:pipe",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _str(d, "WaterLineStatus"),
    ),
    SpinnSensorEntityDescription(
        key="ResidueBin",
        translation_key="grounds_bin",
        icon="mdi:delete",
        value_fn=lambda d: _str(d, "ResidueBin"),
    ),
    SpinnSensorEntityDescription(
        key="ResidueBinCapacity",
        translation_key="grounds_bin_capacity",
        icon="mdi:delete-variant",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(d, "ResidueBinCapacity"),
    ),
    SpinnSensorEntityDescription(
        key="DripTray",
        translation_key="drip_tray",
        icon="mdi:tray",
        value_fn=lambda d: _str(d, "DripTray"),
    ),
    SpinnSensorEntityDescription(
        key="DripTrayCapacity",
        translation_key="drip_tray_capacity",
        icon="mdi:tray-alert",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(d, "DripTrayCapacity"),
    ),
    # --- brew bookkeeping ---
    SpinnSensorEntityDescription(
        key="RecipeNumber",
        translation_key="recipe_number",
        icon="mdi:numeric",
        value_fn=lambda d: _int(d, "RecipeNumber"),
    ),
    SpinnSensorEntityDescription(
        key="ShotCount",
        translation_key="shot_count",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _int(d, "ShotCount"),
    ),
    # --- maintenance counters ---
    SpinnSensorEntityDescription(
        key="GrinderUserCounter",
        translation_key="grinder_user_counter",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(d, "GrinderUserCounter"),
    ),
    SpinnSensorEntityDescription(
        key="GrinderMasterCounter",
        translation_key="grinder_master_counter",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(d, "GrinderMasterCounter"),
    ),
    SpinnSensorEntityDescription(
        key="FilterCounter",
        translation_key="filter_counter",
        icon="mdi:air-filter",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(d, "FilterCounter"),
    ),
    SpinnSensorEntityDescription(
        key="NoDeepCleanCounter",
        translation_key="no_deep_clean_counter",
        icon="mdi:spray-bottle",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(d, "NoDeepCleanCounter"),
        attrs_fn=lambda c: {"interval": c.deep_clean_every},
    ),
    SpinnSensorEntityDescription(
        key="NoDescaleCounter",
        translation_key="no_descale_counter",
        icon="mdi:water-percent",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(d, "NoDescaleCounter"),
        attrs_fn=lambda c: {"interval": c.descale_every},
    ),
    SpinnSensorEntityDescription(
        key="ColdbrewCounter",
        translation_key="coldbrew_counter",
        icon="mdi:snowflake",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(d, "ColdbrewCounter"),
    ),
    # --- telemetry / health ---
    SpinnSensorEntityDescription(
        key="WiFiRssi",
        translation_key="wifi_rssi",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _int(d, "WiFiRssi"),
    ),
    SpinnSensorEntityDescription(
        key="AirPressure",
        translation_key="air_pressure",
        icon="mdi:gauge",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _int(d, "AirPressure"),
    ),
    # --- maintenance history (REST device record, docs/PROTOCOL.md §6) ---
    SpinnSensorEntityDescription(
        key="last_cleaning_at",
        translation_key="last_cleaning",
        icon="mdi:spray-bottle",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        from_device=True,
        value_fn=lambda d: _timestamp(d, "last_cleaning_at"),
    ),
    SpinnSensorEntityDescription(
        key="last_descaling_at",
        translation_key="last_descaling",
        icon="mdi:water-percent",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        from_device=True,
        value_fn=lambda d: _timestamp(d, "last_descaling_at"),
    ),
    SpinnSensorEntityDescription(
        key="last_water_filter_changing_at",
        translation_key="last_filter_change",
        icon="mdi:air-filter",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        from_device=True,
        value_fn=lambda d: _timestamp(d, "last_water_filter_changing_at"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinnCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        *(SpinnSensor(coordinator, desc) for desc in SENSORS),
        SpinnRecipeCatalogSensor(coordinator),
        SpinnServingsSensor(coordinator),
    ])


class SpinnRecipeCatalogSensor(SpinnEntity, SensorEntity):
    """Every recipe the machine can make (state = count; list in attributes).

    Feeds the recipe editor card: library + custom recipes + specials (server)
    and the app's milk guides. The big attributes are excluded from the recorder.
    """

    _attr_icon = "mdi:book-open-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"recipes", "cookbook"})
    entity_description = SensorEntityDescription(key="recipe_catalog", translation_key="recipe_catalog")

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.thing}_recipe_catalog"

    @property
    def native_value(self) -> int | None:
        return len(self.coordinator.catalog) if self.coordinator.catalog else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "recipes": self.coordinator.catalog,
            "cookbook": [
                {k: c.get(k) for k in ("slot", "role", "recipe_id", "name")}
                for c in self.coordinator.cookbook
            ],
        }


class SpinnServingsSensor(SpinnEntity, SensorEntity):
    """Drinks made on the Spinn account (``stats/api/user-stats``).

    State: total servings. Attributes: ``top_recipe`` and ``recipes`` (each
    recipe's count, most brewed first; kept out of the recorder). Account-wide,
    so with two machines on one account both show the same totals. Re-read
    every 15 min and after each brew.
    """

    _attr_icon = "mdi:coffee"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "servings"
    _unrecorded_attributes = frozenset({"recipes"})
    entity_description = SensorEntityDescription(key="servings", translation_key="servings")

    def __init__(self, coordinator: SpinnCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.thing}_servings"

    @property
    def native_value(self) -> int | None:
        stats = self.coordinator.stats
        return stats["servings"] if stats else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        stats = self.coordinator.stats
        if not stats:
            return None
        return {"top_recipe": stats["top_recipe"], "recipes": stats["recipes"]}


class SpinnSensor(SpinnEntity, SensorEntity):
    """A single shadow-backed sensor."""

    entity_description: SpinnSensorEntityDescription

    def __init__(
        self, coordinator: SpinnCoordinator, description: SpinnSensorEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.thing}_{description.key}"

    @property
    def native_value(self) -> Any:
        desc = self.entity_description
        source = self.coordinator.device if desc.from_device else self.coordinator.data
        return desc.value_fn(source or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator) if fn else None
