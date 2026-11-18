"""Diagnostics download: useful contents, nothing secret or identifying."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

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
    assert diag["integration"]["version"] == "0.4.0"
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


async def test_diagnostics_includes_stats_and_intervals(hass: HomeAssistant, coordinator) -> None:
    client = MagicMock()
    client.get_user_stats.return_value = {"cups_total": 812, "email": "someone@example.com"}
    client.get_coffee_backlog.side_effect = RuntimeError("HTTP 404")
    coordinator._client = client
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["stats"]["user_stats"]["cups_total"] == 812
    assert diag["stats"]["user_stats"]["email"] == "**REDACTED**"
    assert diag["stats"]["coffee_backlog"] == {"error": "HTTP 404"}
    client.get_user_stats.assert_called_once_with(THING)
    assert diag["coordinator"]["deep_clean_every"] == 100
    assert diag["coordinator"]["descale_every"] == 500
    coordinator._client = None


async def test_diagnostics_stats_without_client(hass: HomeAssistant, coordinator) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["stats"] == {
        "user_stats": {"error": "not connected"},
        "coffee_backlog": {"error": "not connected"},
    }
