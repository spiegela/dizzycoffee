#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["cryptography>=42"]
# ///
"""Does the Spinn check its broker's TLS certificate?  (steps: docs/TLS-PROBE.md)

Running without Spinn's cloud (docs/PROTOCOL.md §8) hinges on one fact: whether
the machine verifies the server certificate when it connects to AWS IoT. Point
the machine's IoT hostname at this computer with a DNS override, power-cycle the
machine, and this listener reports what happens:

* The machine refuses our self-signed certificate: it verifies, so a DNS
  redirect to a local broker can't work.
* The handshake completes: it doesn't verify. The probe then plays a minimal
  broker and logs the MQTT session (client id, subscriptions, published topics):
  what a local broker would have to serve.

It only ever sends protocol acknowledgements (CONNACK, SUBACK, UNSUBACK, PUBACK,
PUBREC, PUBCOMP, PINGRESP): never a command, never a shadow message.

    uv run tools/tls_probe.py                  # listen on 8883 and 443
    uv run tools/tls_probe.py --port 8883      # one port
    uv run tools/tls_probe.py --wrong-name     # after a completed handshake: does it check hostnames?
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import os
import signal
import socket
import ssl
import struct
import sys
import tempfile
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

# The AWS IoT endpoint the app ships, and its ATS equivalent (docs/PROTOCOL.md §1).
DEFAULT_NAMES = (
    "a1gzieuy3t1932.iot.us-east-1.amazonaws.com",
    "a1gzieuy3t1932-ats.iot.us-east-1.amazonaws.com",
)
WRONG_NAME = "dizzycoffee-tls-probe.invalid"
# AWS IoT's ALPN id for MQTT on port 443, plus plain "mqtt".
ALPN = ["x-amzn-mqtt-ca", "mqtt"]

# TLS alerts a client sends when it won't accept the server's certificate.
CERT_REJECTIONS = (
    "UNKNOWN_CA",
    "BAD_CERTIFICATE",
    "CERTIFICATE_UNKNOWN",
    "UNSUPPORTED_CERTIFICATE",
    "CERTIFICATE_EXPIRED",
    "CERTIFICATE_REVOKED",
    "ACCESS_DENIED",
)
MAX_PACKET = 256 * 1024  # AWS IoT caps messages at 128 KB


# --------------------------------------------------------------- certificate
def make_certificate(names: list[str], wrong_name: bool, directory: str) -> tuple[str, str]:
    """Write a throwaway self-signed RSA certificate + key; return their paths.

    RSA 2048 because that's what AWS IoT's endpoints present, so a device that
    only offers RSA cipher suites can still complete the handshake.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    dns = [WRONG_NAME] if wrong_name else list(names)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, dns[0]),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DizzyCoffee TLS probe (untrusted)"),
        ]
    )
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in dns]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = os.path.join(directory, "probe-cert.pem")
    key_path = os.path.join(directory, "probe-key.pem")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    return cert_path, key_path


def classify_failure(err: BaseException) -> tuple[str, str]:
    """A failed handshake -> (outcome, reason). Outcomes: rejected, hung_up, mismatch."""
    if isinstance(
        err,
        (ssl.SSLEOFError, ssl.SSLZeroReturnError, ConnectionResetError, BrokenPipeError, TimeoutError),
    ):
        return "hung_up", type(err).__name__
    reason = (getattr(err, "reason", None) or "").upper()
    text = str(err).upper()
    if any(r in reason or r in text for r in CERT_REJECTIONS):
        return "rejected", reason or str(err)
    if isinstance(err, ssl.SSLError):
        return "mismatch", reason or str(err)
    return "hung_up", type(err).__name__


# ---------------------------------------------------------------------- MQTT
class Closed(Exception):
    """The peer closed the connection."""


def _read_exact(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise Closed()
        buf += chunk
    return buf


def read_packet(sock) -> tuple[int, int, bytes]:
    """One MQTT packet -> (type, flags, body)."""
    first = _read_exact(sock, 1)[0]
    length, shift = 0, 0
    for _ in range(4):
        byte = _read_exact(sock, 1)[0]
        length |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
    else:
        raise ValueError("malformed remaining length")
    if length > MAX_PACKET:
        raise ValueError(f"packet of {length} bytes is too large")
    return first >> 4, first & 0x0F, _read_exact(sock, length)


def _varint(buf: bytes, off: int) -> tuple[int, int]:
    value, shift = 0, 0
    while True:
        byte = buf[off]
        off += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, off
        shift += 7


def _encode_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _str(buf: bytes, off: int) -> tuple[str, int]:
    (n,) = struct.unpack_from(">H", buf, off)
    return buf[off + 2 : off + 2 + n].decode("utf-8", "replace"), off + 2 + n


def _skip_props(buf: bytes, off: int, level: int) -> int:
    if level != 5:
        return off
    n, off = _varint(buf, off)
    return off + n


@dataclass
class Connect:
    protocol: str
    level: int
    client_id: str
    keepalive: int
    clean: bool
    username: str | None = None
    password_len: int | None = None
    will_topic: str | None = None


def parse_connect(body: bytes) -> Connect:
    protocol, off = _str(body, 0)
    level, flags = body[off], body[off + 1]
    (keepalive,) = struct.unpack_from(">H", body, off + 2)
    off = _skip_props(body, off + 4, level)
    client_id, off = _str(body, off)
    info = Connect(protocol, level, client_id, keepalive, bool(flags & 0x02))
    if flags & 0x04:
        off = _skip_props(body, off, level)
        info.will_topic, off = _str(body, off)
        (n,) = struct.unpack_from(">H", body, off)
        off += 2 + n
    if flags & 0x80:
        info.username, off = _str(body, off)
    if flags & 0x40:
        (info.password_len,) = struct.unpack_from(">H", body, off)
    return info


def parse_subscribe(body: bytes, level: int) -> tuple[int, list[tuple[str, int]]]:
    (pid,) = struct.unpack_from(">H", body, 0)
    off = _skip_props(body, 2, level)
    topics = []
    while off < len(body):
        topic, off = _str(body, off)
        topics.append((topic, body[off] & 0x03))
        off += 1
    return pid, topics


def parse_unsubscribe(body: bytes, level: int) -> tuple[int, list[str]]:
    (pid,) = struct.unpack_from(">H", body, 0)
    off = _skip_props(body, 2, level)
    topics = []
    while off < len(body):
        topic, off = _str(body, off)
        topics.append(topic)
    return pid, topics


def parse_publish(flags: int, body: bytes, level: int) -> tuple[str, int, int | None, bytes]:
    qos = (flags >> 1) & 0x03
    topic, off = _str(body, 0)
    pid = None
    if qos:
        (pid,) = struct.unpack_from(">H", body, off)
        off += 2
    off = _skip_props(body, off, level)
    return topic, qos, pid, body[off:]


def connack(level: int) -> bytes:
    return b"\x20\x03\x00\x00\x00" if level == 5 else b"\x20\x02\x00\x00"


def suback(pid: int, granted: list[int], level: int) -> bytes:
    rest = struct.pack(">H", pid) + (b"\x00" if level == 5 else b"") + bytes(granted)
    return b"\x90" + _encode_varint(len(rest)) + rest


def unsuback(pid: int, count: int, level: int) -> bytes:
    rest = struct.pack(">H", pid) + ((b"\x00" + b"\x00" * count) if level == 5 else b"")
    return b"\xb0" + _encode_varint(len(rest)) + rest


def _ack(kind: int, pid: int) -> bytes:  # PUBACK 0x40, PUBREC 0x50, PUBCOMP 0x70
    return bytes([kind, 2]) + struct.pack(">H", pid)


def preview(payload: bytes, width: int = 160) -> str:
    try:
        text = " ".join(payload.decode("utf-8").split())
    except UnicodeDecodeError:
        return payload[:32].hex() + ("…" if len(payload) > 32 else "")
    return text if len(text) <= width else text[: width - 1] + "…"


# --------------------------------------------------------------------- probe
@dataclass
class PeerStats:
    outcomes: Counter = field(default_factory=Counter)
    reasons: Counter = field(default_factory=Counter)
    sni: Counter = field(default_factory=Counter)
    alpn: Counter = field(default_factory=Counter)
    client_ids: set = field(default_factory=set)
    usernames: set = field(default_factory=set)
    subscriptions: set = field(default_factory=set)
    published: Counter = field(default_factory=Counter)


class Probe:
    """TLS listener(s) that record how clients react to an untrusted certificate."""

    def __init__(
        self,
        certdir: str,
        names: list[str] | None = None,
        *,
        wrong_name: bool = False,
        handshake_only: bool = False,
        handshake_timeout: float = 15.0,
        out: Callable[[str], None] = print,
    ) -> None:
        self.names = list(names or DEFAULT_NAMES)
        self.wrong_name = wrong_name
        self.handshake_only = handshake_only
        self.handshake_timeout = handshake_timeout
        self._out = out
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._listeners: list[socket.socket] = []
        self._open: set = set()
        self._sni: dict[int, str] = {}
        self.peers: dict[str, PeerStats] = {}

        cert, key = make_certificate(self.names, wrong_name, certdir)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # Accept whatever the client offers, so a refusal can only be about the certificate.
        ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        ctx.set_ciphers("ALL:@SECLEVEL=0")
        ctx.load_cert_chain(cert, key)
        ctx.set_alpn_protocols(ALPN)
        ctx.sni_callback = self._on_sni
        self.ctx = ctx

    # ------------------------------------------------------------- plumbing
    def log(self, tag: str, message: str) -> None:
        with self._lock:
            self._out(f"{time.strftime('%H:%M:%S')}  {tag}  {message}")

    def _stats(self, peer: str) -> PeerStats:
        with self._lock:
            return self.peers.setdefault(peer, PeerStats())

    def _on_sni(self, sslsock, server_name, _ctx) -> None:
        if server_name:
            self._sni[id(sslsock)] = server_name

    def start(self, bind: str, ports: list[int]) -> list[int]:
        """Listen on each port; returns the ports actually bound."""
        bound = []
        for port in ports:
            try:
                srv = socket.create_server((bind, port), backlog=16)
            except PermissionError:
                self._out(f"Can't listen on port {port}: it needs root on this system (try sudo, or skip it).")
                continue
            except OSError as err:
                self._out(f"Can't listen on port {port}: {err}")
                continue
            srv.settimeout(0.5)
            self._listeners.append(srv)
            bound.append(srv.getsockname()[1])
            t = threading.Thread(target=self._accept_loop, args=(srv,), name=f"probe-accept-{port}", daemon=True)
            self._threads.append(t)
            t.start()
        return bound

    def _accept_loop(self, srv: socket.socket) -> None:
        port = srv.getsockname()[1]
        while not self._stop.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            t = threading.Thread(target=self._handle, args=(conn, addr, port), name="probe-conn", daemon=True)
            with self._lock:
                self._threads.append(t)
            t.start()

    def stop(self) -> None:
        self._stop.set()
        for srv in self._listeners:
            srv.close()
        with self._lock:
            open_socks = list(self._open)
        for s in open_socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for t in list(self._threads):
            t.join(timeout=5)

    # ----------------------------------------------------------- connection
    def _handle(self, raw: socket.socket, addr, port: int) -> None:
        peer, tag = addr[0], f"{addr[0]}:{addr[1]} -> :{port}"
        stats = self._stats(peer)
        with self._lock:
            self._open.add(raw)
        try:
            raw.settimeout(self.handshake_timeout)
            try:
                first = raw.recv(1, socket.MSG_PEEK)
            except OSError:
                first = b""
            if not first:
                self._record(stats, "silent")
                self.log(tag, "connected but sent nothing")
                return
            if first[0] != 0x16:
                kind = "plain MQTT" if first[0] >> 4 == 1 else "not TLS"
                self._record(stats, "not_tls")
                self.log(tag, f"{kind} (first byte 0x{first[0]:02x}), not a TLS handshake")
                return
            self._tls(raw, tag, stats)
        finally:
            with self._lock:
                self._open.discard(raw)
            raw.close()

    def _record(self, stats: PeerStats, outcome: str, reason: str | None = None) -> None:
        with self._lock:
            stats.outcomes[outcome] += 1
            if reason:
                stats.reasons[reason] += 1

    def _tls(self, raw: socket.socket, tag: str, stats: PeerStats) -> None:
        tls = self.ctx.wrap_socket(raw, server_side=True, do_handshake_on_connect=False)
        with self._lock:
            self._open.add(tls)
        try:
            try:
                tls.do_handshake()
            except (ssl.SSLError, OSError) as err:
                sni = self._sni.pop(id(tls), None)
                if sni:
                    with self._lock:
                        stats.sni[sni] += 1
                outcome, reason = classify_failure(err)
                if outcome == "hung_up" and sni:
                    # The SNI callback ran, so its ClientHello was parsed and we sent our
                    # certificate. Settings can't be the cause (we accept anything, and a
                    # mismatch fails earlier with a reason), so closing now is a refusal
                    # without an alert, as some TLS stacks (AWS's own SDK) do.
                    outcome, reason = "rejected", "closed after receiving our certificate (no alert)"
                self._record(stats, outcome, reason)
                asked = f" for {sni}" if sni else ""
                if outcome == "rejected":
                    self.log(tag, f"REFUSED our certificate{asked}: {reason}")
                elif outcome == "hung_up":
                    self.log(tag, f"hung up during the handshake{asked} ({reason}), without saying why")
                else:
                    self.log(tag, f"couldn't agree on TLS settings{asked}: {reason} (inconclusive)")
                return

            sni = self._sni.pop(id(tls), None)
            alpn = tls.selected_alpn_protocol()
            with self._lock:
                if sni:
                    stats.sni[sni] += 1
                stats.alpn[alpn or "none"] += 1
            self._record(stats, "accepted")
            cipher = (tls.cipher() or ("?",))[0]
            self.log(
                tag,
                f"ACCEPTED our untrusted certificate: {tls.version()}, {cipher}, "
                f"ALPN {alpn or 'none'}, asked for {sni or '(no SNI)'}",
            )
            if not self.handshake_only:
                self._mqtt(tls, tag, stats)
        finally:
            with self._lock:
                self._open.discard(tls)
            try:
                tls.close()
            except OSError:
                pass

    def _mqtt(self, sock, tag: str, stats: PeerStats) -> None:
        """Answer just enough MQTT to see what the machine does. Never publishes to it."""
        level = 4
        sock.settimeout(120)
        try:
            ptype, _flags, body = read_packet(sock)
            if ptype != 1:
                self.log(tag, f"first MQTT packet was type {ptype}, not CONNECT")
                return
            info = parse_connect(body)
            level = info.level
            extras = []
            if info.username is not None:
                extras.append(f"username {info.username!r}")
            if info.password_len is not None:
                extras.append(f"a {info.password_len}-byte password")
            if info.will_topic:
                extras.append(f"will on {info.will_topic}")
            self.log(
                tag,
                f"MQTT CONNECT {info.protocol} v{info.level}: client id {info.client_id!r}, "
                f"keepalive {info.keepalive} s, clean session {info.clean}"
                + (", " + ", ".join(extras) if extras else ""),
            )
            with self._lock:
                stats.client_ids.add(info.client_id)
                if info.username is not None:
                    stats.usernames.add(info.username)
            sock.sendall(connack(level))
            if info.keepalive:
                sock.settimeout(info.keepalive * 1.5 + 5)

            while not self._stop.is_set():
                ptype, flags, body = read_packet(sock)
                if ptype == 8:  # SUBSCRIBE
                    pid, topics = parse_subscribe(body, level)
                    for topic, qos in topics:
                        self.log(tag, f"SUBSCRIBE {topic} (QoS {qos})")
                    with self._lock:
                        stats.subscriptions.update(t for t, _ in topics)
                    sock.sendall(suback(pid, [min(q, 1) for _, q in topics], level))
                elif ptype == 3:  # PUBLISH
                    topic, qos, pid, payload = parse_publish(flags, body, level)
                    self.log(tag, f"PUBLISH {topic} (QoS {qos}, {len(payload):,} bytes): {preview(payload)}")
                    with self._lock:
                        stats.published[topic] += 1
                    if qos == 1:
                        sock.sendall(_ack(0x40, pid))
                    elif qos == 2:
                        sock.sendall(_ack(0x50, pid))
                elif ptype == 6:  # PUBREL
                    sock.sendall(_ack(0x70, struct.unpack_from(">H", body, 0)[0]))
                elif ptype == 10:  # UNSUBSCRIBE
                    pid, topics = parse_unsubscribe(body, level)
                    self.log(tag, f"UNSUBSCRIBE {', '.join(topics)}")
                    sock.sendall(unsuback(pid, len(topics), level))
                elif ptype == 12:  # PINGREQ
                    sock.sendall(b"\xd0\x00")
                elif ptype == 14:  # DISCONNECT
                    self.log(tag, "MQTT DISCONNECT")
                    return
                else:
                    self.log(tag, f"MQTT packet type {ptype} ignored")
        except Closed:
            self.log(tag, "connection closed")
        except (OSError, ValueError, IndexError, struct.error) as err:
            if not self._stop.is_set():
                self.log(tag, f"session ended: {err or type(err).__name__}")

    # --------------------------------------------------------------- report
    def verdict(self) -> tuple[str, str]:
        totals: Counter = Counter()
        reasons: Counter = Counter()
        for s in self.peers.values():
            totals.update(s.outcomes)
            reasons.update(s.reasons)
        if totals["accepted"]:
            text = (
                "The machine ACCEPTED an untrusted, self-signed certificate: it does not verify "
                "the broker, so a local broker behind a DNS redirect is possible."
            )
            if not self.wrong_name:
                text += (
                    " The certificate did carry the right hostname; run again with --wrong-name to "
                    "see whether it checks hostnames at all."
                )
            return "does_not_verify", text
        if totals["rejected"]:
            top = ", ".join(r for r, _ in reasons.most_common(2))
            return "verifies", (
                f"The machine REFUSED the certificate ({top}): it verifies the broker's certificate, "
                "so a DNS redirect to a local broker won't work. What's left is firmware work."
            )
        if totals["hung_up"]:
            return "probably_verifies", (
                "The machine hung up during every handshake without saying why, before naming a "
                "server. That usually means it rejected the certificate, but it isn't conclusive."
            )
        if totals["mismatch"]:
            top = ", ".join(r for r, _ in reasons.most_common(2))
            return "inconclusive", (
                f"The machine and the probe couldn't agree on TLS settings ({top}). That says nothing "
                "about certificate checking; please report the reason."
            )
        if totals["not_tls"]:
            return "no_tls", "Connections arrived, but none spoke TLS on these ports."
        return "no_connection", (
            "No connections. Check that the DNS override reaches the machine (it may use its own "
            "DNS server), and power-cycle it so it reconnects."
        )

    def report(self) -> str:
        lines = ["", "=== Summary"]
        if not self.peers:
            lines.append("No connections.")
        for peer, s in sorted(self.peers.items()):
            parts = [f"{n} {k.replace('_', ' ')}" for k, n in sorted(s.outcomes.items())]
            lines.append(f"{peer}: {', '.join(parts)}")
            if s.reasons:
                lines.append("  reasons: " + ", ".join(f"{r} ×{n}" for r, n in s.reasons.most_common()))
            if s.sni:
                lines.append("  asked for: " + ", ".join(s.sni))
            if s.alpn:
                lines.append("  ALPN: " + ", ".join(s.alpn))
            if s.client_ids:
                lines.append("  MQTT client id: " + ", ".join(sorted(s.client_ids)))
            if s.usernames:
                lines.append("  MQTT username: " + ", ".join(sorted(s.usernames)))
            for topic in sorted(s.subscriptions):
                lines.append(f"  subscribes to: {topic}")
            for topic, n in s.published.most_common():
                lines.append(f"  publishes to: {topic} ×{n}")
        lines += ["", "Verdict: " + self.verdict()[1]]
        return "\n".join(lines)


# ---------------------------------------------------------------------- main
def lan_ip() -> str | None:
    """This computer's LAN address (a UDP 'connect' sends nothing)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: never contacted
            return s.getsockname()[0]
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Check whether a Spinn verifies its broker's TLS certificate (see docs/TLS-PROBE.md)."
    )
    p.add_argument("--port", type=int, action="append", help="port to listen on; repeatable (default: 8883 and 443)")
    p.add_argument("--bind", default="0.0.0.0", help="address to listen on (default: all)")
    p.add_argument("--name", action="append", help="hostname for the certificate; repeatable (default: the Spinn endpoints)")
    p.add_argument("--wrong-name", action="store_true", help="serve a certificate for an unrelated name (after a completed handshake: does it check hostnames?)")
    p.add_argument("--handshake-only", action="store_true", help="close right after the TLS handshake instead of logging the MQTT session")
    p.add_argument("--minutes", type=float, default=0, help="stop after this many minutes (default: run until Ctrl-C)")
    args = p.parse_args(argv)

    names = args.name or list(DEFAULT_NAMES)

    def _stop(*_args) -> None:
        # Ctrl-C or SIGTERM (e.g. `kubectl delete pod`): stop and print the summary.
        # Wrappers like `uv run` may pass a signal on twice; ignore repeats so the
        # summary isn't cut short.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    say = functools.partial(print, flush=True)  # unbuffered, for container logs
    with tempfile.TemporaryDirectory() as certdir:
        probe = Probe(
            certdir, names, wrong_name=args.wrong_name, handshake_only=args.handshake_only, out=say
        )
        ports = probe.start(args.bind, args.port or [8883, 443])
        if not ports:
            print("Couldn't listen on any port.", file=sys.stderr)
            return 2
        ip = lan_ip() or "<this computer's LAN IP>"
        cert_for = WRONG_NAME if args.wrong_name else ", ".join(names)
        say(f"Listening on port {', '.join(map(str, ports))} with an untrusted certificate for {cert_for}.")
        say(f"Point these names at {ip} in your DNS, then power-cycle the machine:")
        for n in names:
            say(f"  {n}")
        say("Watching. Ctrl-C for the summary; remove the DNS override afterwards.\n")
        try:
            deadline = time.monotonic() + args.minutes * 60 if args.minutes else None
            while deadline is None or time.monotonic() < deadline:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            probe.stop()
        say(probe.report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
