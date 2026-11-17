"""Data update coordinator for the Spinn coffee maker.

Wraps the live-verified ``dizzycoffee`` package:

* REST auth + device/cert fetch   -> ``dizzycoffee.api.SpinnClient``
* AWS IoT mutual-TLS connection    -> ``dizzycoffee.connection.build``
* read-only shadow snapshot        -> same ``shadow/get`` protocol as
  ``dizzycoffee.shadow.ReadOnlyShadow``
* opt-in command publishing        -> ``dizzycoffee.commands.DeviceCommander``

Design notes
------------
The ``dizzycoffee`` package is synchronous/blocking (``requests`` + the awscrt
``.result()`` futures), so every call into it runs in Home Assistant's executor
via ``hass.async_add_executor_job``. Shadow pushes arrive on an awscrt I/O
thread; they are marshalled back onto the event loop with
``hass.loop.call_soon_threadsafe`` before touching coordinator state.

The write path (``async_brew`` / ``async_start`` / ``async_stop`` /
``async_flush``) is kept explicit — only the ``button`` platform calls it. Every
other code path here is read-only.

All library imports are lazy (inside methods) so this module imports cleanly for
structural checks even when ``dizzycoffee`` isn't yet importable; a missing
library surfaces as a clear setup error instead of breaking discovery.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_THING_NAME,
    CONF_TOKEN,
    DEFAULT_IOT_BASE,
    DEFAULT_IOT_ENDPOINT,
    DEFAULT_MP_BASE,
    DOMAIN,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# awscrt QoS 1, imported lazily where needed.
_CONNECT_TIMEOUT = 15.0


def extract_reported(doc: dict[str, Any]) -> dict[str, Any]:
    """Pull the ``reported`` state dict out of either shadow envelope.

    * ``shadow/get/accepted``        -> ``{"state": {"reported": {...}}, ...}``
    * ``shadow/update/documents``    -> ``{"current": {"state": {"reported": {...}}}, "previous": {...}}``

    All values are JSON strings per docs/PROTOCOL.md §6; we return them as-is and
    let the entities coerce. Returns ``{}`` if nothing usable is present.
    """
    if not isinstance(doc, dict):
        return {}
    if "current" in doc:  # update/documents envelope
        doc = doc.get("current") or {}
    state = doc.get("state") or {}
    reported = state.get("reported")
    if isinstance(reported, dict):
        return reported
    # Tolerate a bare reported dict or a flat document.
    if isinstance(state, dict) and state:
        return state
    return {}


class _ShadowStream:
    """One persistent AWS IoT connection: pushes shadow updates + answers reads.

    Built with ``dizzycoffee.connection.build`` (the package's shared mutual-TLS
    builder — same thing ``ReadOnlyShadow`` uses). Subscribes to
    ``shadow/update/documents`` (push) and ``shadow/get/accepted`` (snapshot
    replies). It never publishes to ``<thing>/host``; the only publish is the
    passive empty ``shadow/get``.
    """

    def __init__(
        self,
        endpoint: str,
        thing: str,
        cert_pem: str,
        private_key_pem: str,
        on_reported: Callable[[dict[str, Any]], None],
    ) -> None:
        self._endpoint = endpoint
        self._thing = thing
        self._cert = cert_pem
        self._key = private_key_pem
        self._on_reported = on_reported
        self._conn = None
        self._snapshots: "queue.Queue[dict]" = queue.Queue()
        self._lock = threading.Lock()
        self.connected = False

    @property
    def _base(self) -> str:
        return f"$aws/things/{self._thing}/shadow"

    def _on_documents(self, topic, payload, **_kw) -> None:  # awscrt thread
        try:
            doc = json.loads(payload.decode() or "{}")
        except Exception:  # noqa: BLE001 - never let a bad frame kill the callback
            return
        reported = extract_reported(doc)
        if reported:
            self._on_reported(reported)

    def _on_get_accepted(self, topic, payload, **_kw) -> None:  # awscrt thread
        try:
            self._snapshots.put(json.loads(payload.decode() or "{}"))
        except Exception:  # noqa: BLE001
            self._snapshots.put({})

    def connect(self, timeout: float = _CONNECT_TIMEOUT) -> None:
        """Connect and (re)subscribe. Blocking — call from the executor."""
        from awscrt import mqtt  # lazy
        from dizzycoffee import connection

        qos1 = mqtt.QoS.AT_LEAST_ONCE
        self._conn = connection.build(self._endpoint, self._cert, self._key)
        self._conn.connect().result(timeout)
        self._conn.subscribe(f"{self._base}/get/accepted", qos1, self._on_get_accepted)[0].result(timeout)
        self._conn.subscribe(f"{self._base}/update/documents", qos1, self._on_documents)[0].result(timeout)
        self.connected = True

    def get_snapshot(self, timeout: float = _CONNECT_TIMEOUT) -> dict[str, Any]:
        """Publish an empty ``shadow/get`` and return the reply. Blocking."""
        from awscrt import mqtt  # lazy

        if self._conn is None:
            raise RuntimeError("shadow stream not connected")
        qos1 = mqtt.QoS.AT_LEAST_ONCE
        # Drain any stale snapshot so we match our own request.
        with self._lock:
            while not self._snapshots.empty():
                try:
                    self._snapshots.get_nowait()
                except queue.Empty:
                    break
            self._conn.publish(f"{self._base}/get", b"", qos1)[0].result(timeout)
            return self._snapshots.get(timeout=timeout)

    def disconnect(self, timeout: float = 10.0) -> None:
        self.connected = False
        if self._conn is not None:
            try:
                self._conn.disconnect().result(timeout)
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            finally:
                self._conn = None


class SpinnCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keeps the parsed shadow ``reported`` dict fresh (push + poll fallback)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
            config_entry=entry,
        )
        self.entry = entry
        self.thing: str = entry.data[CONF_THING_NAME]
        self.endpoint: str = DEFAULT_IOT_ENDPOINT

        self._client = None  # dizzycoffee.api.SpinnClient
        self._stream: _ShadowStream | None = None
        self._cert: str | None = None
        self._key: str | None = None

        # Full device record from GET link/api/devices/{thing} (name, serial,
        # firmware versions, maintenance timestamps).
        self.device: dict[str, Any] = {}
        # Local-only recipe slot picked in HA for the Brew button (no actuation).
        self.selected_slot: int | None = None

    # ------------------------------------------------------------------ reads
    async def _async_update_data(self) -> dict[str, Any]:
        reported, new_token = await self.hass.async_add_executor_job(self._refresh_blocking)
        if new_token:
            # Persist the rotated session token (loop-thread call).
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_TOKEN: new_token}
            )
        # Merge onto prior state so a partial document never drops keys.
        merged = {**(self.data or {}), **reported}
        return merged

    def _build_client(self, token: dict[str, Any]):
        from dizzycoffee.api import SpinnClient  # lazy

        return SpinnClient(DEFAULT_MP_BASE, DEFAULT_IOT_BASE, access_token=token.get("access_token"))

    def _refresh_blocking(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Blocking refresh: (re)auth as needed, fetch device+cert, read shadow.

        Returns ``(reported_dict, rotated_token_or_None)``.
        """
        try:
            from dizzycoffee.api import SpinnError  # lazy
        except ImportError as err:  # library not importable in this environment
            raise UpdateFailed(
                "The 'dizzycoffee' library is not importable. Install it into the "
                "Home Assistant environment (see the integration README)."
            ) from err

        token = dict(self.entry.data[CONF_TOKEN])
        new_token: dict[str, Any] | None = None

        if self._client is None:
            self._client = self._build_client(token)

        # Fetch the full device record (the only endpoint carrying the usable
        # cert, per docs/PROTOCOL.md §2). On 401, refresh once via auth/token.
        try:
            full = self._client.get_device(self.thing)
        except SpinnError as err:
            if getattr(err, "status", None) != 401:
                raise UpdateFailed(f"Spinn device fetch failed: {err}") from err
            _LOGGER.debug("Access token expired; refreshing via auth/token")
            try:
                refreshed = self._build_client(token)
                new_token = refreshed.refresh(token)
                full = refreshed.get_device(self.thing)
                self._client = refreshed
            except SpinnError as err2:
                raise ConfigEntryAuthFailed(
                    "Spinn re-authentication failed; please sign in again."
                ) from err2

        self.device = full
        cert = full.get("certificate") or {}
        pem = cert.get("certificate_pem")
        key = cert.get("certificate_private_key")
        if not (pem and key):
            raise UpdateFailed(
                "Device record has no usable certificate (certificate_pem / "
                "certificate_private_key missing)."
            )

        cert_changed = pem != self._cert or key != self._key
        self._cert, self._key = pem, key

        # (Re)establish the push stream if needed.
        if self._stream is None or not self._stream.connected or cert_changed:
            if self._stream is not None:
                self._stream.disconnect()
            self._stream = _ShadowStream(
                self.endpoint, self.thing, pem, key, self._push_reported
            )
            self._stream.connect()

        # Fallback / priming read. If it fails, rebuild the stream once.
        try:
            doc = self._stream.get_snapshot()
        except Exception as err:  # noqa: BLE001 - reconnect-and-retry
            _LOGGER.debug("shadow snapshot failed (%s); reconnecting", err)
            self._stream.disconnect()
            self._stream = _ShadowStream(
                self.endpoint, self.thing, pem, key, self._push_reported
            )
            self._stream.connect()
            doc = self._stream.get_snapshot()

        return extract_reported(doc), new_token

    # ------------------------------------------------------------------ push
    def _push_reported(self, reported: dict[str, Any]) -> None:  # awscrt thread
        """Marshal a pushed shadow update onto the event loop."""
        self.hass.loop.call_soon_threadsafe(self._apply_push, reported)

    def _apply_push(self, reported: dict[str, Any]) -> None:  # loop thread
        if not reported:
            return
        self.async_set_updated_data({**(self.data or {}), **reported})

    # --------------------------------------------------------------- commands
    async def async_brew(self, slot: int) -> None:
        """Brew a cookbook slot: SELECT_RECIPE+slot then PREPARE_RECIPE+slot.

        docs/PROTOCOL.md §5 [V]: this exact sequence poured a real cup and the
        slot byte equals the shadow's ``RecipeNumber``.
        """
        from dizzycoffee.commands import DeviceCommand  # lazy

        await self._run_commands(
            [(DeviceCommand.SELECT_RECIPE, int(slot)), (DeviceCommand.PREPARE_RECIPE, int(slot))]
        )

    async def async_start(self) -> None:
        from dizzycoffee.commands import DeviceCommand  # lazy

        await self._run_commands([(DeviceCommand.START, None)])

    async def async_stop(self) -> None:
        from dizzycoffee.commands import DeviceCommand  # lazy

        await self._run_commands([(DeviceCommand.STOP, None)])

    async def async_flush(self) -> None:
        from dizzycoffee.commands import DeviceCommand  # lazy

        await self._run_commands([(DeviceCommand.HOPPER_FLUSH, None)])

    async def _run_commands(self, steps: list[tuple[Any, int | None]]) -> None:
        if not (self._cert and self._key):
            raise HomeAssistantError("Spinn is not connected yet; try again shortly.")
        await self.hass.async_add_executor_job(self._send_blocking, steps)
        # Reflect the new machine state promptly.
        await self.async_request_refresh()

    def _send_blocking(self, steps: list[tuple[Any, int | None]]) -> None:
        """ACTUATES THE MACHINE. Opens a short-lived command connection."""
        from dizzycoffee.commands import DeviceCommander  # lazy

        assert self._cert and self._key
        with DeviceCommander(self.endpoint, self.thing, self._cert, self._key) as cmder:
            for i, (cmd, param) in enumerate(steps):
                cmder.send(cmd, param)
                if i + 1 < len(steps):
                    time.sleep(1.0)  # mirror the CLI's inter-step pause

    # -------------------------------------------------------------- lifecycle
    async def async_shutdown_stream(self) -> None:
        """Disconnect the push stream (called on unload)."""
        if self._stream is not None:
            stream, self._stream = self._stream, None
            await self.hass.async_add_executor_job(stream.disconnect)
