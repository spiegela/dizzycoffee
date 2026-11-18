"""tools/tls_probe.py against real TLS clients on localhost.

A verifying client stands in for a machine that checks the broker's certificate,
a non-verifying one for a machine that doesn't (followed by an MQTT session).
"""
from __future__ import annotations

import importlib.util
import socket
import ssl
import struct
import sys
import time
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "tls_probe", Path(__file__).resolve().parents[1] / "tools" / "tls_probe.py"
)
tls_probe = importlib.util.module_from_spec(_spec)
sys.modules["tls_probe"] = tls_probe  # dataclasses look the module up while it loads
_spec.loader.exec_module(tls_probe)

LEGACY, ATS = tls_probe.DEFAULT_NAMES


@pytest.fixture
def probe(tmp_path, socket_enabled):
    lines: list[str] = []
    p = tls_probe.Probe(str(tmp_path), out=lines.append, handshake_timeout=3)
    (port,) = p.start("127.0.0.1", [0])
    p.port, p.lines = port, lines
    yield p
    p.stop()


def _wait_for(probe, outcome: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stats = probe.peers.get("127.0.0.1")
        if stats and stats.outcomes[outcome]:
            return stats
        time.sleep(0.02)
    raise AssertionError(f"no {outcome!r} recorded; log: {probe.lines}")


def _mqtt_str(s: str) -> bytes:
    return struct.pack(">H", len(s)) + s.encode()


def _packet(first: int, body: bytes) -> bytes:
    return bytes([first]) + tls_probe._encode_varint(len(body)) + body


def _recv_exact(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        assert chunk, f"closed after {buf!r}"
        buf += chunk
    return buf


def test_verifying_client_refuses_the_certificate(probe) -> None:
    ctx = ssl.create_default_context()  # trusts the system roots, like a device trusting Amazon's
    with socket.create_connection(("127.0.0.1", probe.port), timeout=5) as raw:
        with pytest.raises(ssl.SSLCertVerificationError):
            ctx.wrap_socket(raw, server_hostname=ATS)

    stats = _wait_for(probe, "rejected")
    assert "UNKNOWN_CA" in next(iter(stats.reasons))
    assert stats.sni[ATS] == 1
    assert probe.verdict()[0] == "verifies"
    assert any("REFUSED our certificate for " + ATS in line for line in probe.lines)


def test_aws_iot_sdk_hanging_up_counts_as_a_refusal(probe) -> None:
    """AWS's device SDK (awscrt) refuses by closing without an alert."""
    import datetime as dt

    import certifi
    from awsiot import mqtt_connection_builder
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AWS IoT Certificate")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now).not_valid_after(now + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    conn = mqtt_connection_builder.mtls_from_bytes(
        endpoint="localhost",
        port=probe.port,
        cert_bytes=cert.public_bytes(serialization.Encoding.PEM),
        pri_key_bytes=key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
        ca_filepath=certifi.where(),
        client_id="dizzy-probe-test",
        clean_session=True,
        keep_alive_secs=30,
    )
    with pytest.raises(Exception, match="TLS"):
        conn.connect().result(10)

    stats = _wait_for(probe, "rejected")
    assert stats.reasons["closed after receiving our certificate (no alert)"] == 1
    assert probe.verdict()[0] == "verifies"


def test_non_verifying_client_gets_an_mqtt_session_with_only_acks(probe) -> None:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["x-amzn-mqtt-ca"])
    thing = "SPU-TEST-0001"
    with socket.create_connection(("127.0.0.1", probe.port), timeout=5) as raw:
        with ctx.wrap_socket(raw, server_hostname=LEGACY) as s:
            connect = (
                _mqtt_str("MQTT") + bytes([4, 0x82]) + struct.pack(">H", 60)
                + _mqtt_str(thing) + _mqtt_str("?SDK=Test&Version=1")
            )
            s.sendall(_packet(0x10, connect))
            assert _recv_exact(s, 4) == b"\x20\x02\x00\x00"  # CONNACK, accepted

            topics = [f"{thing}/host", f"$aws/things/{thing}/shadow/update/delta"]
            sub = struct.pack(">H", 1) + b"".join(_mqtt_str(t) + b"\x01" for t in topics)
            s.sendall(_packet(0x82, sub))
            assert _recv_exact(s, 6) == b"\x90\x04\x00\x01\x01\x01"  # SUBACK, QoS 1 each

            payload = b'{"state": {"reported": {"connected": "true"}}}'
            pub = _mqtt_str(f"$aws/things/{thing}/shadow/update") + struct.pack(">H", 2) + payload
            s.sendall(_packet(0x32, pub))
            assert _recv_exact(s, 4) == b"\x40\x02\x00\x02"  # PUBACK

            s.sendall(b"\xc0\x00")
            assert _recv_exact(s, 2) == b"\xd0\x00"  # PINGRESP
            s.sendall(b"\xe0\x00")  # DISCONNECT
            s.settimeout(2)
            try:
                rest = s.recv(64)
            except (ssl.SSLError, OSError):
                rest = b""
            assert rest == b""  # nothing else: no commands, no shadow messages

    stats = _wait_for(probe, "accepted")
    deadline = time.monotonic() + 3
    while not stats.published and time.monotonic() < deadline:
        time.sleep(0.02)
    assert stats.sni[LEGACY] == 1
    assert stats.alpn["x-amzn-mqtt-ca"] == 1
    assert stats.client_ids == {thing}
    assert stats.usernames == {"?SDK=Test&Version=1"}
    assert stats.subscriptions == set(topics)
    assert stats.published[f"$aws/things/{thing}/shadow/update"] == 1
    assert probe.verdict()[0] == "does_not_verify"
    report = probe.report()
    assert f"MQTT client id: {thing}" in report
    assert "--wrong-name" in report


def test_plain_mqtt_is_noted_not_misread(probe) -> None:
    with socket.create_connection(("127.0.0.1", probe.port), timeout=5) as raw:
        raw.sendall(b"\x10\x0c\x00\x04MQTT\x04\x02\x00\x3c\x00\x00")
        _wait_for(probe, "not_tls")
    assert probe.verdict()[0] == "no_tls"


def test_no_connections_verdict(tmp_path) -> None:
    p = tls_probe.Probe(str(tmp_path), out=lambda _l: None)
    assert p.verdict()[0] == "no_connection"
    assert "No connections" in p.report()


def test_certificate_names(tmp_path) -> None:
    from cryptography import x509

    def sans(wrong: bool) -> list[str]:
        cert_path, _ = tls_probe.make_certificate(list(tls_probe.DEFAULT_NAMES), wrong, str(tmp_path))
        cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
        return cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)

    assert sans(False) == [LEGACY, ATS]
    assert sans(True) == [tls_probe.WRONG_NAME]


def test_mqtt5_parsing() -> None:
    connect = (
        _mqtt_str("MQTT") + bytes([5, 0xC2]) + struct.pack(">H", 30)
        + b"\x05\x11\x00\x00\x00\x0a"  # properties: session expiry
        + _mqtt_str("SPU-5") + _mqtt_str("user") + _mqtt_str("secret")
    )
    info = tls_probe.parse_connect(connect)
    assert (info.level, info.client_id, info.keepalive, info.clean) == (5, "SPU-5", 30, True)
    assert info.username == "user" and info.password_len == 6

    sub = struct.pack(">H", 7) + b"\x00" + _mqtt_str("a/b") + b"\x01"
    assert tls_probe.parse_subscribe(sub, 5) == (7, [("a/b", 1)])
    assert tls_probe.suback(7, [1], 5) == b"\x90\x04\x00\x07\x00\x01"

    pub = _mqtt_str("t") + struct.pack(">H", 9) + b"\x00" + b"hi"
    assert tls_probe.parse_publish(0x02, pub, 5) == ("t", 1, 9, b"hi")


def test_failure_classification() -> None:
    class Alert(ssl.SSLError):
        pass

    err = Alert(1, "[SSL: TLSV1_ALERT_UNKNOWN_CA] tlsv1 alert unknown ca")
    err.reason = "TLSV1_ALERT_UNKNOWN_CA"
    assert tls_probe.classify_failure(err) == ("rejected", "TLSV1_ALERT_UNKNOWN_CA")
    err = Alert(1, "no shared cipher")
    err.reason = "NO_SHARED_CIPHER"
    assert tls_probe.classify_failure(err) == ("mismatch", "NO_SHARED_CIPHER")
    assert tls_probe.classify_failure(ssl.SSLEOFError())[0] == "hung_up"
    assert tls_probe.classify_failure(ConnectionResetError())[0] == "hung_up"
