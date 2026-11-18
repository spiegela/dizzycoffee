"""Command guards (offline / busy) and brew confirmation.

``_send_blocking`` (the MQTT publish that actuates the machine) is always
mocked; a side effect stands in for the machine by pushing a shadow update.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.spinn.const import DOMAIN

from .conftest import COOKBOOK, THING, entity_id

COORD = "custom_components.spinn.coordinator"


def _machine_goes(hass: HomeAssistant, coordinator, **changes: Any):
    """A _send_blocking stand-in: the machine reacts by pushing a shadow update."""

    def _send(steps):
        hass.loop.call_soon_threadsafe(
            coordinator.async_set_updated_data, {**coordinator.data, **changes}
        )

    return _send


async def _press(hass: HomeAssistant, key: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id(hass, "button", key)}, blocking=True
    )


async def test_brew_returns_once_machine_pours(hass: HomeAssistant, coordinator) -> None:
    with patch.object(
        coordinator, "_send_blocking", side_effect=_machine_goes(hass, coordinator, MachineStatus="PREPAREDRINK")
    ) as send:
        await _press(hass, "brew")

    steps = send.call_args.args[0]
    assert [(int(cmd), slot) for cmd, slot in steps] == [(5, 5), (6, 5)]  # SELECT, PREPARE slot 5


async def test_brew_refused_when_offline(hass: HomeAssistant, coordinator) -> None:
    coordinator.async_set_updated_data({**coordinator.data, "connected": "false"})
    with patch.object(coordinator, "_send_blocking") as send:
        with pytest.raises(HomeAssistantError, match="offline"):
            await _press(hass, "brew")
    send.assert_not_called()


@pytest.mark.parametrize(("status", "word"), [("PREPAREDRINK", "brewing"), ("CLEANING", "cleaning")])
async def test_brew_and_flush_refused_when_busy(
    hass: HomeAssistant, coordinator, status: str, word: str
) -> None:
    coordinator.async_set_updated_data({**coordinator.data, "MachineStatus": status})
    with patch.object(coordinator, "_send_blocking") as send:
        with pytest.raises(HomeAssistantError, match=word):
            await _press(hass, "brew")
        with pytest.raises(HomeAssistantError, match=word):
            await _press(hass, "hopper_flush")
    send.assert_not_called()


async def test_stop_allowed_while_busy_but_not_offline(hass: HomeAssistant, coordinator) -> None:
    coordinator.async_set_updated_data({**coordinator.data, "MachineStatus": "PREPAREDRINK"})
    with patch.object(coordinator, "_send_blocking") as send:
        await _press(hass, "stop")
    assert int(send.call_args.args[0][0][0]) == 4  # STOP

    coordinator.async_set_updated_data({**coordinator.data, "connected": "false"})
    with patch.object(coordinator, "_send_blocking") as send:
        with pytest.raises(HomeAssistantError, match="offline"):
            await _press(hass, "stop")
    send.assert_not_called()


async def test_brew_that_never_starts_raises_with_hint(hass: HomeAssistant, coordinator) -> None:
    coordinator.async_set_updated_data(
        {**coordinator.data, "WaterTank": "EMPTY", "DripTray": "FULL"}
    )
    with (
        patch(f"{COORD}.BREW_CONFIRM_TIMEOUT", 0.3),
        patch(f"{COORD}.BREW_POLL_INTERVAL", 0.05),
        patch.object(coordinator, "_send_blocking"),
    ):
        with pytest.raises(HomeAssistantError) as err:
            await _press(hass, "brew")
    msg = str(err.value)
    assert "didn't start brewing" in msg
    assert "the water tank is empty and the drip tray is full" in msg


async def test_brew_that_errors_raises(hass: HomeAssistant, coordinator) -> None:
    with patch.object(
        coordinator, "_send_blocking", side_effect=_machine_goes(hass, coordinator, MachineStatus="MACHINEERROR")
    ):
        with pytest.raises(HomeAssistantError, match="reported an error"):
            await _press(hass, "brew")


async def test_brew_confirmed_by_poll_when_push_is_missed(hass: HomeAssistant, coordinator) -> None:
    stream = MagicMock(connected=True)
    stream.get_snapshot.return_value = {"state": {"reported": {"MachineStatus": "PREPAREDRINK"}}}
    coordinator._stream = stream
    with (
        patch(f"{COORD}.BREW_POLL_INTERVAL", 0.05),
        patch.object(coordinator, "_send_blocking"),
    ):
        await _press(hass, "brew")
    assert stream.get_snapshot.called
    assert coordinator.data["MachineStatus"] == "PREPAREDRINK"
    coordinator._stream = None


async def test_brew_recipe_refused_offline_before_touching_cookbook(
    hass: HomeAssistant, coordinator
) -> None:
    client = MagicMock()
    coordinator._client = client
    coordinator.async_set_updated_data({**coordinator.data, "connected": "false"})
    with pytest.raises(HomeAssistantError, match="offline"):
        await hass.services.async_call(
            DOMAIN, "brew_recipe", {"recipe_id": "r-lungo"}, blocking=True
        )
    client.set_temporary_slot.assert_not_called()


async def test_brew_recipe_stages_temp_slot_and_brews(hass: HomeAssistant, coordinator) -> None:
    lungo = {"id": "r-lungo", "slug": "lungo", "type": "spinn", "name": "Lungo", "slider": {}}
    client = MagicMock()
    client.get_recipes.return_value = [lungo]
    client.get_installed_recipes.return_value = [dict(c) for c in COOKBOOK]
    coordinator._client = client
    coordinator._library = {"r-lungo": lungo}

    with (
        patch(f"{COORD}._TEMP_SLOT_SETTLE", 0),
        patch.object(
            coordinator, "_send_blocking", side_effect=_machine_goes(hass, coordinator, MachineStatus="PREPAREDRINK")
        ) as send,
    ):
        await hass.services.async_call(
            DOMAIN, "brew_recipe", {"recipe_id": "r-lungo"}, blocking=True
        )

    client.set_temporary_slot.assert_called_once_with(THING, "r-lungo")
    assert [(int(cmd), slot) for cmd, slot in send.call_args.args[0]] == [(5, 7), (6, 7)]


# --- transport: shared connection, fallback, serialisation -------------------


def _shared_stream(conn: MagicMock) -> MagicMock:
    stream = MagicMock(connected=True, connection=conn)
    stream.get_snapshot.return_value = {}
    return stream


def _fake_conn(on_publish=None) -> MagicMock:
    conn = MagicMock()

    def _publish(topic, payload, qos):
        if on_publish:
            on_publish(topic, payload)
        return (MagicMock(), 1)

    conn.publish.side_effect = _publish
    return conn


async def test_brew_publishes_over_push_connection(hass: HomeAssistant, coordinator) -> None:
    sent: list[tuple[str, bytes]] = []

    def _on_publish(topic, payload):
        sent.append((topic, payload))
        if payload == b"0605":  # PREPARE: the machine starts pouring
            hass.loop.call_soon_threadsafe(
                coordinator.async_set_updated_data, {**coordinator.data, "MachineStatus": "PREPAREDRINK"}
            )

    conn = _fake_conn(_on_publish)
    coordinator._stream = _shared_stream(conn)
    with (
        patch(f"{COORD}.COMMAND_STEP_GAP", 0),
        patch("dizzycoffee.connection.build") as build,
    ):
        await _press(hass, "brew")

    assert sent == [(f"{THING}/host", b"0505"), (f"{THING}/host", b"0605")]
    build.assert_not_called()  # no second connection
    conn.disconnect.assert_not_called()  # the push stream's connection stays up
    conn.subscribe.assert_not_called()  # no ack subscription on the shared connection
    coordinator._stream = None


async def test_failed_publish_tears_down_shared_connection(hass: HomeAssistant, coordinator) -> None:
    conn = MagicMock()
    conn.publish.side_effect = RuntimeError("AWS_ERROR_MQTT_TIMEOUT")
    stream = _shared_stream(conn)
    coordinator._stream = stream
    with pytest.raises(HomeAssistantError, match="Couldn't send the command.*AWS_ERROR_MQTT_TIMEOUT"):
        await _press(hass, "stop")
    stream.disconnect.assert_called_once()
    coordinator._stream = None


async def test_interrupted_stream_falls_back_to_fresh_connection(
    hass: HomeAssistant, coordinator
) -> None:
    stream = MagicMock(connected=False, connection=None)  # interrupted
    coordinator._stream = stream
    conn = _fake_conn()
    with (
        patch(f"{COORD}.COMMAND_STEP_GAP", 1.0),  # ack window 0 s keeps the test fast
        patch("dizzycoffee.connection.build", return_value=conn) as build,
    ):
        await _press(hass, "stop")

    build.assert_called_once()
    conn.connect.assert_called_once()
    assert conn.publish.call_args.args[:2] == (f"{THING}/host", b"04")
    conn.disconnect.assert_called_once()
    coordinator._stream = None


async def test_double_tap_brews_once(hass: HomeAssistant, coordinator) -> None:
    with patch.object(
        coordinator, "_send_blocking", side_effect=_machine_goes(hass, coordinator, MachineStatus="PREPAREDRINK")
    ) as send:
        results = await asyncio.gather(
            _press(hass, "brew"), _press(hass, "brew"), return_exceptions=True
        )

    assert send.call_count == 1
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], HomeAssistantError)
    assert "brewing" in str(errors[0])


async def test_stop_does_not_wait_behind_a_brew(hass: HomeAssistant, coordinator) -> None:
    sent = asyncio.Event()

    def _send(steps):
        hass.loop.call_soon_threadsafe(sent.set)

    with (
        patch(f"{COORD}.BREW_CONFIRM_TIMEOUT", 30),
        patch(f"{COORD}.BREW_POLL_INTERVAL", 0.05),
        patch.object(coordinator, "_send_blocking", side_effect=_send) as send,
    ):
        brew = hass.async_create_task(_press(hass, "brew"))
        await sent.wait()  # brew sent; now waiting for the machine to pour
        await asyncio.wait_for(_press(hass, "stop"), 5)  # goes straight through
        assert not brew.done()
        assert int(send.call_args.args[0][0][0]) == 4  # STOP

        coordinator.async_set_updated_data({**coordinator.data, "MachineStatus": "PREPAREDRINK"})
        await asyncio.wait_for(brew, 5)
