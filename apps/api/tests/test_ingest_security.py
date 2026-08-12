from __future__ import annotations

import asyncio
import socket
import ssl
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpcore
import pytest

from zhenfu_api.ingest.security import (
    FetchPolicy,
    SafeFetcher,
    UnsafeTargetError,
    validate_public_url,
)

PUBLIC_IP = "93.184.216.34"
SECOND_PUBLIC_IP = "1.1.1.1"
_USE_CONNECTED_PEER = object()


def _resolver(host: str, port: int):
    private_addresses = {"127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"}
    address = host if host in private_addresses else PUBLIC_IP
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, port))]


@dataclass(frozen=True, slots=True)
class _ResponseScript:
    head: bytes
    body_chunks: tuple[bytes, ...]
    peer: object = _USE_CONNECTED_PEER


class _TLSInfo:
    def selected_alpn_protocol(self) -> str:
        return "http/1.1"


class _ScriptedStream(httpcore.AsyncNetworkStream):
    def __init__(
        self,
        script: _ResponseScript,
        events: list[str],
        *,
        connected_peer: tuple[str, int],
    ) -> None:
        self._chunks = [script.head, *script.body_chunks]
        self._head_pending = True
        self._peer = connected_peer if script.peer is _USE_CONNECTED_PEER else script.peer
        self._events = events
        self.body_was_read = False
        self.closed = False
        self.server_hostname: str | None = None
        self.ssl_context: ssl.SSLContext | None = None
        self.writes: list[bytes] = []
        self.read_timeouts: list[float | None] = []
        self.write_timeouts: list[float | None] = []
        self.tls_timeout: float | None = None

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        self._events.append("read")
        self.read_timeouts.append(timeout)
        if not self._chunks:
            return b""
        if not self._head_pending:
            self.body_was_read = True
        self._head_pending = False
        return self._chunks.pop(0)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._events.append("write")
        self.writes.append(buffer)
        self.write_timeouts.append(timeout)

    async def aclose(self) -> None:
        self.closed = True
        self._events.append("close")

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self._events.append("start_tls")
        self.server_hostname = server_hostname
        self.ssl_context = ssl_context
        self.tls_timeout = timeout
        return self

    def get_extra_info(self, info: str) -> Any:
        if info == "server_addr":
            self._events.append("validate_peer")
            return self._peer
        if info == "ssl_object" and self.ssl_context is not None:
            return _TLSInfo()
        return None


class _ScriptedBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self,
        *scripts: _ResponseScript,
        connect_errors: Iterable[str] = (),
    ) -> None:
        self._scripts = list(scripts)
        self._connect_errors = set(connect_errors)
        self.events: list[str] = []
        self.connects: list[tuple[str, int, float | None]] = []
        self.streams: list[_ScriptedStream] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.events.append("connect")
        self.connects.append((host, port, timeout))
        if host in self._connect_errors:
            raise httpcore.ConnectError("scripted connection failure")
        if not self._scripts:
            raise AssertionError("unexpected source connection")
        stream = _ScriptedStream(
            self._scripts.pop(0), self.events, connected_peer=(host, port)
        )
        self.streams.append(stream)
        return stream

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise AssertionError("Unix sockets must not be used")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(0)


def _response(
    status_code: int = 200,
    *,
    headers: dict[str, str] | None = None,
    body_chunks: tuple[bytes, ...] = (b"{}",),
    peer: object = _USE_CONNECTED_PEER,
) -> _ResponseScript:
    response_headers = headers or {
        "content-type": "application/json",
        "content-length": str(sum(len(chunk) for chunk in body_chunks)),
    }
    reason = {200: "OK", 301: "Moved Permanently", 302: "Found"}.get(status_code, "Result")
    header_lines = [f"HTTP/1.1 {status_code} {reason}"]
    header_lines.extend(f"{name}: {value}" for name, value in response_headers.items())
    header_lines.append("connection: close")
    head = ("\r\n".join(header_lines) + "\r\n\r\n").encode("ascii")
    return _ResponseScript(head=head, body_chunks=body_chunks, peer=peer)


def _fetch(fetcher: SafeFetcher, url: str = "https://source.example/feed"):
    return asyncio.run(fetcher.fetch(url))


def _fetcher(
    backend: _ScriptedBackend,
    policy: FetchPolicy | None = None,
    *,
    resolver=_resolver,
) -> SafeFetcher:
    return SafeFetcher(
        policy,
        resolver=resolver,
        network_backend_factory=lambda: backend,
    )


def test_fetch_pins_tcp_but_preserves_host_sni_and_certificate_validation() -> None:
    backend = _ScriptedBackend(_response(body_chunks=(b'{"items":', b"[]}")))

    artifact = _fetch(_fetcher(backend))

    stream = backend.streams[0]
    request_bytes = b"".join(stream.writes).lower()
    assert artifact.body == b'{"items":[]}'
    assert artifact.final_url == "https://source.example/feed"
    assert backend.connects[0][:2] == (PUBLIC_IP, 443)
    assert stream.server_hostname == "source.example"
    assert stream.ssl_context is not None
    assert stream.ssl_context.check_hostname
    assert stream.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert b"host: source.example\r\n" in request_bytes
    assert backend.events.index("validate_peer") < backend.events.index("start_tls")
    assert backend.events.index("start_tls") < backend.events.index("write")


def test_dns_is_resolved_once_and_only_the_validated_ip_is_connected() -> None:
    resolutions = 0

    def rebinding_resolver(_host: str, port: int):
        nonlocal resolutions
        resolutions += 1
        address = PUBLIC_IP if resolutions == 1 else "10.0.0.8"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    backend = _ScriptedBackend(_response())

    _fetch(_fetcher(backend, resolver=rebinding_resolver))

    assert resolutions == 1
    assert backend.connects[0][:2] == (PUBLIC_IP, 443)


def test_tls_trust_store_does_not_follow_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", "/definitely/not/a/ca-bundle.pem")
    backend = _ScriptedBackend(_response())

    artifact = _fetch(_fetcher(backend))

    assert artifact.body == b"{}"
    assert backend.streams[0].ssl_context is not None


def test_private_connected_peer_is_rejected_before_tls_or_http_bytes() -> None:
    backend = _ScriptedBackend(_response(peer=("10.0.0.8", 443)))

    with pytest.raises(UnsafeTargetError, match="connection used a non-public"):
        _fetch(_fetcher(backend))

    stream = backend.streams[0]
    assert stream.closed
    assert stream.server_hostname is None
    assert not stream.writes
    assert "start_tls" not in backend.events
    assert "write" not in backend.events


def test_unexpected_public_peer_is_rejected_before_http_bytes() -> None:
    backend = _ScriptedBackend(_response(peer=(SECOND_PUBLIC_IP, 443)))

    with pytest.raises(UnsafeTargetError, match="unexpected peer"):
        _fetch(_fetcher(backend))

    assert backend.streams[0].closed
    assert not backend.streams[0].writes


def test_missing_connected_peer_fails_closed_before_http_bytes() -> None:
    backend = _ScriptedBackend(_response(peer=None))

    with pytest.raises(UnsafeTargetError, match="valid peer"):
        _fetch(_fetcher(backend))

    assert backend.streams[0].closed
    assert not backend.streams[0].writes


def test_content_length_precheck_rejects_without_reading_body() -> None:
    backend = _ScriptedBackend(
        _response(
            headers={"content-type": "text/plain", "content-length": "11"},
            body_chunks=(b"small",),
        )
    )
    fetcher = _fetcher(backend, FetchPolicy(max_bytes=10))

    with pytest.raises(UnsafeTargetError, match="maximum size"):
        _fetch(fetcher)

    assert not backend.streams[0].body_was_read


def test_streamed_byte_count_rejects_response_without_content_length() -> None:
    backend = _ScriptedBackend(
        _response(
            headers={"content-type": "text/plain"},
            body_chunks=(b"12345", b"678901"),
        )
    )
    fetcher = _fetcher(backend, FetchPolicy(max_bytes=10))

    with pytest.raises(UnsafeTargetError, match="maximum size"):
        _fetch(fetcher)


def test_redirect_target_is_revalidated_and_pinned_before_second_request() -> None:
    first_url = "https://source.example/feed"
    second_url = "https://redirect.example/next"
    addresses = {"source.example": PUBLIC_IP, "redirect.example": SECOND_PUBLIC_IP}
    resolutions: list[str] = []

    def resolver(host: str, port: int):
        resolutions.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addresses[host], port))]

    backend = _ScriptedBackend(
        _response(302, headers={"location": second_url}, body_chunks=()),
        _response(body_chunks=(b"done",)),
    )

    artifact = _fetch(_fetcher(backend, resolver=resolver), first_url)

    assert artifact.final_url == second_url
    assert artifact.body == b"done"
    assert resolutions == ["source.example", "redirect.example"]
    assert [connect[:2] for connect in backend.connects] == [
        (PUBLIC_IP, 443),
        (SECOND_PUBLIC_IP, 443),
    ]
    assert [stream.server_hostname for stream in backend.streams] == [
        "source.example",
        "redirect.example",
    ]


def test_redirect_to_private_target_is_rejected_before_second_request() -> None:
    backend = _ScriptedBackend(
        _response(
            302,
            headers={"location": "http://127.0.0.1/secrets"},
            body_chunks=(),
        )
    )

    with pytest.raises(UnsafeTargetError, match="non-public"):
        _fetch(_fetcher(backend))

    assert len(backend.connects) == 1


def test_redirect_limit_is_enforced_with_automatic_redirects_disabled() -> None:
    backend = _ScriptedBackend(
        *(
            _response(302, headers={"location": f"/redirect/{index}"}, body_chunks=())
            for index in range(3)
        )
    )
    fetcher = _fetcher(backend, FetchPolicy(max_redirects=2))

    with pytest.raises(UnsafeTargetError, match="redirect limit"):
        _fetch(fetcher)

    assert len(backend.connects) == 3


def test_operation_timeouts_are_forwarded_through_the_pinned_transport() -> None:
    backend = _ScriptedBackend(_response())

    _fetch(_fetcher(backend, FetchPolicy(timeout_seconds=0.25)))

    stream = backend.streams[0]
    connect_timeout = backend.connects[0][2]
    assert connect_timeout is not None
    assert 0.24 < connect_timeout <= 0.25
    assert stream.tls_timeout == pytest.approx(0.25)
    assert all(timeout == pytest.approx(0.25) for timeout in stream.write_timeouts)
    assert all(timeout == pytest.approx(0.25) for timeout in stream.read_timeouts)


def test_falls_back_only_to_another_prevalidated_address() -> None:
    def resolver(_host: str, port: int):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (SECOND_PUBLIC_IP, port)),
        ]

    backend = _ScriptedBackend(_response(), connect_errors={PUBLIC_IP})

    artifact = _fetch(_fetcher(backend, resolver=resolver))

    assert artifact.body == b"{}"
    assert [connect[0] for connect in backend.connects] == [PUBLIC_IP, SECOND_PUBLIC_IP]


@pytest.mark.parametrize(
    "address",
    [
        "64:ff9b::7f00:1",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b:1::7f00:1",
        "::ffff:127.0.0.1",
        "2002:7f00:1::",
        "2001:0000:4136:e378:8000:63bf:3fff:fdd2",
        "fec0::1",
        "ff0e::1",
    ],
)
def test_ipv6_transition_addresses_cannot_tunnel_to_non_public_ipv4(address: str) -> None:
    def resolver(_host: str, port: int):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, port, 0, 0))]

    with pytest.raises(UnsafeTargetError, match="non-public"):
        validate_public_url("https://source.example/feed", resolver=resolver)


def test_public_ipv4_mapped_ipv6_address_remains_allowed() -> None:
    address = "::ffff:8.8.8.8"

    def resolver(_host: str, port: int):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, port, 0, 0))]

    url = "https://source.example/feed"
    assert validate_public_url(url, resolver=resolver) == url


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({"content-type": "image/png", "content-length": "2"}, "unsupported content type"),
        (
            {"content-type": "text/plain", "content-length": "not-a-number"},
            "source request failed safely",
        ),
    ],
)
def test_invalid_response_metadata_fails_closed(headers: dict[str, str], message: str) -> None:
    backend = _ScriptedBackend(_response(headers=headers))

    with pytest.raises(UnsafeTargetError, match=message):
        _fetch(_fetcher(backend))


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:password@source.example/feed",
        "https://@source.example/feed",
    ],
)
def test_protocols_and_credentials_are_rejected_without_connecting(url: str) -> None:
    backend = _ScriptedBackend()

    with pytest.raises(UnsafeTargetError):
        _fetch(_fetcher(backend), url)

    assert not backend.connects
