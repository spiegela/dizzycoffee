"""Shared AWS IoT MQTT connection builder (mutual TLS).

Used by both the read-only shadow reader and the (opt-in) command sender so the
TLS/endpoint handling lives in one place. Building a connection does not publish
anything on its own.
"""
from __future__ import annotations

import uuid

import certifi
from awsiot import mqtt_connection_builder


def build(endpoint: str, cert_pem: str, private_key_pem: str, *, client_prefix: str = "dizzy-"):
    """Return a configured (not yet connected) awscrt mqtt connection.

    Server cert (Amazon Trust Services on the ATS endpoint) is validated against
    the certifi CA bundle — portable across macOS/Linux/Home Assistant.
    """
    client_id = client_prefix + uuid.uuid4().hex[:12]
    return mqtt_connection_builder.mtls_from_bytes(
        endpoint=endpoint,
        port=8883,
        cert_bytes=cert_pem.encode(),
        pri_key_bytes=private_key_pem.encode(),
        ca_filepath=certifi.where(),
        client_id=client_id,
        clean_session=True,
        keep_alive_secs=30,
    )
