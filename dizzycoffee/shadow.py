"""Read-only AWS IoT Device Shadow reader (mutual TLS).

This module is **read-only by construction**. The only thing it ever publishes
is an empty message to `$aws/things/<thing>/shadow/get`, which asks the broker
to send back the current shadow document — it does not touch the machine. There
is deliberately no method here that publishes to `<thing>/host` (the command
topic); actuating the machine lives nowhere in this client. See docs/PROTOCOL.md §4, §6.
"""
from __future__ import annotations

import json
import queue
from typing import Any, Callable

from awscrt import mqtt

from . import connection

QOS1 = mqtt.QoS.AT_LEAST_ONCE


class ReadOnlyShadow:
    def __init__(self, endpoint: str, thing_name: str, cert_pem: str, private_key_pem: str):
        self.endpoint = endpoint
        self.thing = thing_name
        self._cert = cert_pem
        self._key = private_key_pem
        self._conn = None

    # --- topic helpers ------------------------------------------------------
    @property
    def _shadow_base(self) -> str:
        return f"$aws/things/{self.thing}/shadow"

    # --- lifecycle ----------------------------------------------------------
    def connect(self, timeout: float = 15.0) -> None:
        self._conn = connection.build(self.endpoint, self._cert, self._key)
        self._conn.connect().result(timeout)

    def disconnect(self, timeout: float = 10.0) -> None:
        if self._conn is not None:
            try:
                self._conn.disconnect().result(timeout)
            finally:
                self._conn = None

    def __enter__(self) -> "ReadOnlyShadow":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()

    # --- reads --------------------------------------------------------------
    def get_snapshot(self, timeout: float = 15.0) -> dict[str, Any]:
        """Ask for and return the current shadow document (passive)."""
        assert self._conn is not None, "call connect() first"
        inbox: "queue.Queue[tuple[str, dict]]" = queue.Queue()

        def _on_msg(topic, payload, **_kw):
            try:
                inbox.put((topic, json.loads(payload.decode() or "{}")))
            except Exception:
                inbox.put((topic, {"_raw": payload.decode(errors="replace")}))

        for suffix in ("get/accepted", "get/rejected"):
            self._conn.subscribe(f"{self._shadow_base}/{suffix}", QOS1, _on_msg)[0].result(timeout)

        # Empty publish to shadow/get -> broker replies with the document. Passive.
        self._conn.publish(f"{self._shadow_base}/get", b"", QOS1)[0].result(timeout)

        topic, doc = inbox.get(timeout=timeout)
        if topic.endswith("rejected"):
            raise RuntimeError(f"shadow/get rejected: {doc}")
        return doc

    def watch(self, on_update: Callable[[dict], None], include_events: bool = True,
              timeout: float = 15.0) -> None:
        """Subscribe to the live shadow stream and call on_update(doc) per message.

        Also subscribes (read) to `<thing>/host` to observe acks/events. Never publishes
        there. Blocks until KeyboardInterrupt.
        """
        assert self._conn is not None, "call connect() first"

        def _on_shadow(topic, payload, **_kw):
            try:
                on_update(json.loads(payload.decode() or "{}"))
            except Exception:
                pass

        self._conn.subscribe(f"{self._shadow_base}/update/documents", QOS1, _on_shadow)[0].result(timeout)
        if include_events:
            def _on_event(topic, payload, **_kw):
                txt = payload.decode(errors="replace")
                print(f"[event {topic}] {txt}")
            self._conn.subscribe(f"{self.thing}/host", QOS1, _on_event)[0].result(timeout)

        # Prime with a current snapshot too.
        try:
            on_update(self.get_snapshot(timeout))
        except Exception:
            pass

        import threading
        threading.Event().wait()  # block; Ctrl-C to stop
