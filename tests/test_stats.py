"""Usage stats: parsing the live response shape, the Servings sensor, refresh timing."""
from __future__ import annotations

from unittest.mock import MagicMock

from dizzycoffee.api import SpinnError

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from custom_components.spinn.stats import parse_user_stats

from .conftest import THING

# Trimmed from a live stats/api/user-stats response (ids shortened). As live,
# servings_count is the sum of the recipe_counts.
USER_STATS = {
    "created_at": "2023-12-01T12:30:19.377Z",
    "id": "stats-id",
    "schema_user_id": "user-id",
    "servings_count": 1937,
    "stats": {
        "a": {"host_version": "2.10", "id": "a", "name": "Coffee", "recipe_count": 829,
              "slug": "coffee", "type": "spinn"},
        "b": {"host_version": None, "id": "b", "name": "J mug", "recipe_count": 1068,
              "slug": "mug", "type": "custom"},
        "c": {"host_version": "2.10", "id": "c", "name": "Lungo", "recipe_count": 32,
              "slug": "lungo", "type": "spinn"},
        "d": {"host_version": None, "id": "d", "name": "Spinn AI Espresso \U0001f680",
              "recipe_count": 2, "slug": "espresso-plus", "type": "custom"},
        "e": {"host_version": "2.5.0", "id": "e", "name": "Hot water", "recipe_count": 6,
              "slug": "hot-water", "type": "spinn"},
    },
    "updated_at": "2026-11-18T13:02:50.277Z",
}


def test_parse_user_stats() -> None:
    parsed = parse_user_stats(USER_STATS)
    assert parsed["servings"] == 1937
    assert parsed["top_recipe"] == "J mug"
    assert parsed["updated_at"] == "2026-11-18T13:02:50.277Z"
    assert [(r["name"], r["count"]) for r in parsed["recipes"]] == [
        ("J mug", 1068),
        ("Coffee", 829),
        ("Lungo", 32),
        ("Hot water", 6),
        ("Spinn AI Espresso \U0001f680", 2),
    ]
    assert parsed["recipes"][0] == {"name": "J mug", "slug": "mug", "type": "custom", "count": 1068}


def test_parse_user_stats_edge_cases() -> None:
    assert parse_user_stats(None) is None
    assert parse_user_stats([]) is None
    assert parse_user_stats({"stats": {}}) is None  # nothing to report
    # No total: fall back to the sum of the recipe counts.
    body = {"stats": {"a": {"name": "A", "recipe_count": 3}, "b": {"name": "B", "recipe_count": "4"}}}
    assert parse_user_stats(body)["servings"] == 7
    # Junk entries are skipped.
    body = {"servings_count": 5, "stats": {"a": "junk", "b": {"name": "B"}}}
    assert parse_user_stats(body) == {"servings": 5, "updated_at": None, "top_recipe": None, "recipes": []}


async def test_servings_sensor(hass: HomeAssistant, coordinator) -> None:
    eid = "sensor.kitchen_spinn_servings"
    assert hass.states.get(eid).state == STATE_UNKNOWN  # not fetched yet

    coordinator.stats = parse_user_stats(USER_STATS)
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    state = hass.states.get(eid)
    assert state.state == "1937"
    assert state.attributes["state_class"] == "total_increasing"
    assert state.attributes["unit_of_measurement"] == "servings"
    assert state.attributes["top_recipe"] == "J mug"
    assert state.attributes["recipes"][1] == {"name": "Coffee", "slug": "coffee", "type": "spinn", "count": 829}


async def test_stats_refresh_timing(hass: HomeAssistant, coordinator) -> None:
    client = MagicMock()
    client.get_user_stats.return_value = USER_STATS
    coordinator._client = client
    fetch = coordinator._refresh_stats_blocking

    await hass.async_add_executor_job(fetch, SpinnError)  # never fetched: due now
    assert client.get_user_stats.call_count == 1
    client.get_user_stats.assert_called_with(THING)
    assert coordinator.stats["servings"] == 1937

    await hass.async_add_executor_job(fetch, SpinnError)  # within the TTL: skipped
    assert client.get_user_stats.call_count == 1

    # A brew finishing makes them due again.
    coordinator.async_set_updated_data({**coordinator.data, "MachineStatus": "PREPAREDRINK"})
    coordinator._apply_push({"MachineStatus": "ACTIVE"})
    await hass.async_add_executor_job(fetch, SpinnError)
    assert client.get_user_stats.call_count == 2

    # A failure keeps the old stats and waits out the TTL before retrying.
    coordinator._stats_at = None
    client.get_user_stats.side_effect = SpinnError("HTTP 500", status=500)
    await hass.async_add_executor_job(fetch, SpinnError)
    await hass.async_add_executor_job(fetch, SpinnError)
    assert client.get_user_stats.call_count == 3
    assert coordinator.stats["servings"] == 1937
    coordinator._client = None
