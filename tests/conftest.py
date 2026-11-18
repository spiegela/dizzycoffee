"""Shared fixtures: a Spinn config entry set up with Spinn's cloud stubbed out.

``SpinnCoordinator._refresh_blocking`` (sign-in, device + certificate fetch,
shadow read) is replaced with canned data, so no test touches the network or
the machine. Tests drive state changes with ``coordinator.async_set_updated_data``,
the same call a pushed shadow update ends in.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.spinn.const import (
    CONF_DEVICE_NAME,
    CONF_EMAIL,
    CONF_THING_NAME,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.spinn.coordinator import SpinnCoordinator

pytest_plugins = "pytest_homeassistant_custom_component"

THING = "spinn-thing-0123456789abcdef"

# An idle, healthy machine, as a live one reports it right after the hopper is
# filled and both bins emptied (all shadow values are strings, as on the wire).
SHADOW: dict[str, Any] = {
    "MachineStatus": "ACTIVE",
    "ProcessStatus": "UNDEFINED",
    "connected": "true",
    "HopperReservoir": "LEVEL2",
    "WaterTank": "FULL",
    "WaterVolume": "750",
    "WaterLineStatus": "WL_CONNECTED",
    "ResidueBin": "PLACED",
    "ResidueBinCapacity": "100",  # space left; counts down as the bin fills
    "DripTray": "PLACED",
    "DripTrayCapacity": "300",
    "RecipeNumber": "5",
    "ShotCount": "1234",
    "NoDeepCleanCounter": "12",
    "NoDescaleCounter": "40",
    "FilterCounter": "88",
    "WiFiRssi": "-61",
    "recipes": ["1,2,3", "4,5,6"],
}

DEVICE: dict[str, Any] = {
    "id": 42,
    "name": "Kitchen Spinn",
    "thing_name": THING,
    "serial_number": "SPN-SERIAL-0001",
    "mac_sta": "aa:bb:cc:dd:ee:ff",
    "mac_bt": "aa:bb:cc:dd:ee:fe",
    "current_host_version": "1.2.3",
    "certificate": {
        "certificate_pem": "-----BEGIN CERTIFICATE-----PEMSECRET",
        "certificate_private_key": "-----BEGIN PRIVATE KEY-----KEYSECRET",
        "certificate_arn": f"arn:aws:iot:us-east-1:000000000000:cert/{THING}",
    },
    "owner": {"email": "someone@example.com"},
    "topic": f"{THING}/host",
    "last_cleaning_at": "2026-11-01T08:00:00Z",
}

COOKBOOK: list[dict[str, Any]] = [
    {"slot": 4, "role": "tall", "recipe_id": "r-coffee", "name": "Coffee", "slug": "coffee",
     "type": "spinn", "drink_size": 240, "shots": 1, "cold": False},
    {"slot": 5, "role": "medium", "recipe_id": "r-lungo", "name": "Lungo", "slug": "lungo",
     "type": "spinn", "drink_size": 110, "shots": 1, "cold": False},
    {"slot": 7, "role": "temp", "recipe_id": "r-lungo", "name": "Lungo", "slug": "lungo",
     "type": "spinn", "drink_size": 110, "shots": 1, "cold": False},
]

ENTRY_DATA = {
    CONF_EMAIL: "someone@example.com",
    CONF_TOKEN: {"access_token": "test-access-token", "refresh_token": "test-refresh-token"},
    CONF_THING_NAME: THING,
    CONF_DEVICE_NAME: "Kitchen Spinn",
}

SetupSpinn = Callable[..., Awaitable[SpinnCoordinator]]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/spinn in every test."""
    yield


@pytest.fixture
async def setup_spinn(hass: HomeAssistant):
    """Factory: set up the integration with optional shadow overrides."""
    patches: list[Any] = []

    async def _setup(
        *, before: Callable[[MockConfigEntry], None] | None = None, **shadow_overrides: Any
    ) -> SpinnCoordinator:
        """``before(entry)`` runs after the entry exists, before setup (e.g. to seed the registry)."""
        shadow = {**SHADOW, **shadow_overrides}

        def _refresh(self: SpinnCoordinator):
            self.device = dict(DEVICE)
            self.cookbook = [dict(item) for item in COOKBOOK]
            self._cert = self._key = "test"
            return dict(shadow), None

        for p in (
            patch.object(SpinnCoordinator, "_refresh_blocking", _refresh),
            patch("custom_components.spinn._async_register_frontend"),
        ):
            p.start()
            patches.append(p)

        entry = MockConfigEntry(
            domain=DOMAIN, unique_id=THING, title="Kitchen Spinn", data=dict(ENTRY_DATA)
        )
        entry.add_to_hass(hass)
        if before is not None:
            before(entry)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return hass.data[DOMAIN][entry.entry_id]

    yield _setup
    for p in reversed(patches):
        p.stop()


@pytest.fixture
async def coordinator(setup_spinn: SetupSpinn) -> SpinnCoordinator:
    """An idle, online machine."""
    return await setup_spinn()


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Entity id for a Spinn entity by its unique-id key."""
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{THING}_{key}")
    assert eid, f"no {platform} entity for {key}"
    return eid
