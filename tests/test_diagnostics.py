"""Diagnostics download: useful contents, nothing secret or identifying."""
from __future__ import annotations

import json

from homeassistant.core import HomeAssistant

from custom_components.spinn.const import DOMAIN
from custom_components.spinn.diagnostics import async_get_config_entry_diagnostics

from .conftest import THING


async def test_diagnostics_redacts_secrets(hass: HomeAssistant, coordinator) -> None:
    coordinator.async_set_updated_data({**coordinator.data, "WaterTank": "EMPTY"})
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    diag = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diag)

    for secret in (
        THING,
        "PEMSECRET",
        "KEYSECRET",
        "test-access-token",
        "test-refresh-token",
        "someone@example.com",
        "SPN-SERIAL-0001",
        "aa:bb:cc:dd:ee:ff",
    ):
        assert secret not in dumped, f"{secret!r} leaked into diagnostics"

    # Still useful: machine state, device details, cookbook, what needs attention.
    assert diag["integration"]["version"] == "0.3.0"
    assert diag["integration"]["dizzycoffee"]["importable"] is True
    assert diag["shadow"]["MachineStatus"] == "ACTIVE"
    assert diag["shadow"]["WiFiRssi"] == "-61"
    assert diag["device"]["name"] == "Kitchen Spinn"
    assert diag["device"]["current_host_version"] == "1.2.3"
    assert diag["device"]["topic"] == "**THING**/host"
    assert diag["entry"]["data"]["device_name"] == "Kitchen Spinn"
    assert [c["name"] for c in diag["cookbook"]] == ["Coffee", "Lungo", "Lungo"]
    assert diag["attention"]["reasons"] == ["water_tank_empty"]
    assert diag["coordinator"]["last_update_success"] is True
