"""The dizzycoffee client pieces the integration relies on (no network, no HA)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from dizzycoffee import cli, connection
from dizzycoffee.api import SpinnClient, SpinnError
from dizzycoffee.commands import DeviceCommand, DeviceCommander

from custom_components.spinn.coordinator import _ShadowStream


def _client() -> SpinnClient:
    return SpinnClient("https://mp.example/api/", "https://iot.example/", access_token="t")


# --- stats endpoints ---------------------------------------------------------


def test_stats_tries_thing_name_first() -> None:
    client = _client()
    with patch.object(client, "_request", return_value={"cups": 3}) as req:
        assert client.get_user_stats("thing-1") == {"cups": 3}
    req.assert_called_once_with(
        "GET", "https://iot.example/stats/api/user-stats", params={"thing_name": "thing-1"}, auth=True
    )


@pytest.mark.parametrize("status", [400, 404])
def test_stats_drops_thing_name_when_rejected(status: int) -> None:
    client = _client()
    calls = []

    def _request(method, url, **kw):
        calls.append(kw)
        if "params" in kw:
            raise SpinnError("nope", status=status)
        return {"avg": 2}

    with patch.object(client, "_request", side_effect=_request):
        assert client.get_coffee_backlog("thing-1") == {"avg": 2}
    assert calls == [{"params": {"thing_name": "thing-1"}, "auth": True}, {"auth": True}]


def test_stats_other_errors_propagate() -> None:
    client = _client()
    with patch.object(client, "_request", side_effect=SpinnError("down", status=500)):
        with pytest.raises(SpinnError):
            client.get_user_stats("thing-1")


def test_cli_stats_prints_both_endpoints(capsys) -> None:
    client = MagicMock()
    client.get_user_stats.return_value = {"cups_total": 812}
    client.get_coffee_backlog.side_effect = SpinnError("x -> HTTP 404", status=404, body="not found")
    with patch.object(cli, "_get_devices_with_refresh", return_value=(client, [{"thing_name": "thing-1"}])):
        assert cli.main(["stats"]) == 0
    out = capsys.readouterr().out
    assert "== stats/api/user-stats" in out
    assert json.dumps({"cups_total": 812}, indent=2) in out
    assert "== average-consumer/api/coffee-backlog" in out
    assert "error: x -> HTTP 404" in out
    client.get_user_stats.assert_called_once_with("thing-1")


# --- MQTT plumbing -----------------------------------------------------------


def test_build_passes_connection_callbacks() -> None:
    def interrupted(*a, **kw): ...
    def resumed(*a, **kw): ...

    with patch.object(connection.mqtt_connection_builder, "mtls_from_bytes") as mtls:
        connection.build("ep", "cert", "key", on_interrupted=interrupted, on_resumed=resumed)
        assert mtls.call_args.kwargs["on_connection_interrupted"] is interrupted
        assert mtls.call_args.kwargs["on_connection_resumed"] is resumed

        connection.build("ep", "cert", "key")
        assert "on_connection_interrupted" not in mtls.call_args.kwargs


def test_commander_over_existing_connection() -> None:
    conn = MagicMock()
    conn.publish.return_value = (MagicMock(), 1)
    with patch.object(connection, "build") as build:
        with DeviceCommander.from_connection(conn, "thing-1") as cmder:
            cmder.send(DeviceCommand.SELECT_RECIPE, 4, await_ack=0)
        build.assert_not_called()
    conn.connect.assert_not_called()
    conn.disconnect.assert_not_called()
    assert conn.publish.call_args.args[:2] == ("thing-1/host", b"0504")


def test_stream_tracks_interruptions() -> None:
    stream = _ShadowStream("ep", "thing-1", "cert", "key", lambda r: None)
    stream._conn = MagicMock()
    stream.connected = True
    assert stream.connection is stream._conn

    stream._on_interrupted(stream._conn, error="AWS_IO_SOCKET_CLOSED")
    assert stream.connected is False
    assert stream.connection is None

    # Clean session: subscriptions are gone, so stay down until rebuilt.
    stream._on_resumed(stream._conn, return_code=0, session_present=False)
    assert stream.connection is None

    stream._on_resumed(stream._conn, return_code=0, session_present=True)
    assert stream.connection is stream._conn
