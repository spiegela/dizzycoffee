"""Device commands — the ACTUATING path (publishes to `<thing>/host`).

Separate from shadow.py on purpose: shadow.py is read-only; everything that can
physically drive the machine lives here. Importing or constructing these does not
actuate anything — only `DeviceCommander.send()` (and its wrappers) publish, and
the CLI gates every one behind an explicit confirmation.

Wire format (docs/PROTOCOL.md §5): publish an ASCII hex string to `<thing>/host`,
`"%02x" % opcode` optionally followed by `"%02x" % param` (e.g. a recipe slot).
The opcode table is [C] confirmed from the decompiled app; the exact brew sequence
and whether the slot byte is 0- or 1-based are [L] not yet verified live.
"""
from __future__ import annotations

import enum
import json
import queue
from typing import Optional

from awscrt import mqtt

from . import connection

QOS1 = mqtt.QoS.AT_LEAST_ONCE


class DeviceCommand(enum.IntEnum):
    """Opcode bytes from com.spinn.devicesdk.model.awsiot.DeviceCommand."""
    NONE = 0
    SWITCH_ON = 1
    SWITCH_OFF = 2
    START = 3
    STOP = 4
    SELECT_RECIPE = 5
    PREPARE_RECIPE = 6
    REBOOT = 7
    RESET_GRINDER_COUNTER = 8
    HOPPER_FLUSH = 17


def encode(cmd: DeviceCommand, param: Optional[int] = None) -> str:
    """Build the hex payload for `<thing>/host`. Pure; actuates nothing."""
    payload = f"{int(cmd):02x}"
    if param is not None:
        if not 0 <= int(param) <= 0xFF:
            raise ValueError(f"param out of byte range: {param}")
        payload += f"{int(param):02x}"
    return payload


class DeviceCommander:
    """Connects and publishes commands to `<thing>/host`. Actuates the machine."""

    def __init__(self, endpoint: str, thing_name: str, cert_pem: str, private_key_pem: str):
        self.endpoint = endpoint
        self.thing = thing_name
        self._cert = cert_pem
        self._key = private_key_pem
        self._conn = None
        self._owns_conn = True

    @classmethod
    def from_connection(cls, conn, thing_name: str) -> "DeviceCommander":
        """Publish over an existing, already-connected MQTT connection.

        Saves a TLS handshake per command when the caller already holds a
        connection with the same certificate (e.g. a shadow subscription). The
        connection stays the caller's: connect()/disconnect() leave it alone.
        """
        cmder = cls("", thing_name, "", "")
        cmder._conn = conn
        cmder._owns_conn = False
        return cmder

    @property
    def _topic(self) -> str:
        return f"{self.thing}/host"

    def connect(self, timeout: float = 15.0) -> None:
        if not self._owns_conn:
            return
        self._conn = connection.build(self.endpoint, self._cert, self._key)
        self._conn.connect().result(timeout)

    def disconnect(self, timeout: float = 10.0) -> None:
        if not self._owns_conn:
            return
        if self._conn is not None:
            try:
                self._conn.disconnect().result(timeout)
            finally:
                self._conn = None

    def __enter__(self) -> "DeviceCommander":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()

    def _publish(self, payload: str, await_ack: float) -> dict:
        """Publish a hex payload to `<thing>/host`. ACTUATES THE MACHINE.

        Returns {"payload": <hex>, "acks": [...]} — any JSON the machine emits on
        `<thing>/host` within `await_ack` seconds (ack shape is [L] unconfirmed).
        """
        assert self._conn is not None, "call connect() first"
        acks: "queue.Queue[dict]" = queue.Queue()
        if await_ack:
            def _on_ack(topic, payload, **_kw):
                try:
                    acks.put(json.loads(payload.decode() or "{}"))
                except Exception:
                    acks.put({"_raw": payload.decode(errors="replace")})
            self._conn.subscribe(self._topic, QOS1, _on_ack)[0].result(10)

        self._conn.publish(self._topic, payload.encode(), QOS1)[0].result(10)

        # Collect everything the host topic emits in the window. The first message
        # is usually the broker echoing our own publish back (we're subscribed to
        # the same topic); genuine machine events/acks, if any, follow.
        collected = []
        if await_ack:
            import time
            deadline = time.monotonic() + await_ack
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    collected.append(acks.get(timeout=remaining))
                except queue.Empty:
                    break
        return {"payload": payload, "acks": collected}

    def send(self, cmd: DeviceCommand, param: Optional[int] = None,
             *, await_ack: float = 3.0) -> dict:
        """Encode and publish one command. ACTUATES THE MACHINE."""
        return self._publish(encode(cmd, param), await_ack)

    def send_raw(self, payload_hex: str, *, await_ack: float = 3.0) -> dict:
        """Publish a raw hex payload verbatim (escape hatch). ACTUATES THE MACHINE."""
        bytes.fromhex(payload_hex)  # validate: even-length, valid hex
        return self._publish(payload_hex.lower(), await_ack)

    # --- convenience wrappers (each ACTUATES) -------------------------------
    def power_on(self, **kw):  return self.send(DeviceCommand.SWITCH_ON, **kw)
    def power_off(self, **kw): return self.send(DeviceCommand.SWITCH_OFF, **kw)
    def start(self, **kw):     return self.send(DeviceCommand.START, **kw)
    def stop(self, **kw):      return self.send(DeviceCommand.STOP, **kw)
    def hopper_flush(self, **kw): return self.send(DeviceCommand.HOPPER_FLUSH, **kw)
    def select_recipe(self, slot: int, **kw): return self.send(DeviceCommand.SELECT_RECIPE, slot, **kw)
    def prepare_recipe(self, slot: int, **kw): return self.send(DeviceCommand.PREPARE_RECIPE, slot, **kw)
