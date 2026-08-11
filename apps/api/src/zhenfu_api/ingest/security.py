from __future__ import annotations

import hashlib
import ipaddress
import socket
import time
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Self, cast
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx


class UnsafeTargetError(ValueError):
    pass


AddressInfo = tuple[object, object, object, object, tuple[object, ...]]
Resolver = Callable[[str, int], Sequence[AddressInfo]]
NetworkBackendFactory = Callable[[], httpcore.AsyncNetworkBackend]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_NAT64_NETWORKS = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
)


def _is_public_address(address: IPAddress) -> bool:
    if not address.is_global or address.is_reserved or address.is_multicast:
        return False
    if not isinstance(address, ipaddress.IPv6Address):
        return True
    if address.is_site_local:
        return False
    if any(address in network for network in _NAT64_NETWORKS):
        return False

    embedded_addresses: tuple[ipaddress.IPv4Address, ...] = ()
    if address.ipv4_mapped is not None:
        embedded_addresses = (address.ipv4_mapped,)
    elif address.sixtofour is not None:
        embedded_addresses = (address.sixtofour,)
    elif address.teredo is not None:
        embedded_addresses = address.teredo
    return all(_is_public_address(embedded) for embedded in embedded_addresses)


def _require_global_address(raw_address: object, *, source: str) -> IPAddress:
    try:
        address = ipaddress.ip_address(str(raw_address))
    except ValueError as exc:
        raise UnsafeTargetError(f"{source} did not provide a valid IP address") from exc
    if not _is_public_address(address):
        raise UnsafeTargetError(f"{source} used a non-public address: {address}")
    return address


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    timeout_seconds: float = 15
    max_bytes: int = 5_000_000
    max_redirects: int = 4
    allowed_content_types: tuple[str, ...] = (
        "application/atom+xml",
        "application/json",
        "application/rss+xml",
        "application/xml",
        "text/html",
        "text/plain",
        "text/xml",
    )


@dataclass(frozen=True, slots=True)
class RawArtifact:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class _ResolvedTarget:
    url: str
    scheme: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def _ascii_hostname(hostname: str) -> str:
    try:
        return hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise UnsafeTargetError("source URL had an invalid hostname") from exc


def _resolve_public_url(url: str, *, resolver: Resolver) -> _ResolvedTarget:
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise UnsafeTargetError("source URL could not be parsed") from exc
    if parts.scheme not in {"http", "https"}:
        raise UnsafeTargetError("only HTTP(S) targets are allowed")
    if parts.username is not None or parts.password is not None:
        raise UnsafeTargetError("credentials in source URLs are not allowed")
    hostname = parts.hostname
    if not hostname or hostname.casefold() == "localhost":
        raise UnsafeTargetError("source URL requires a public hostname")
    hostname = _ascii_hostname(hostname)
    try:
        explicit_port = parts.port
    except ValueError as exc:
        raise UnsafeTargetError("source URL has an invalid port") from exc
    if explicit_port == 0:
        raise UnsafeTargetError("source URL has an invalid port")
    port = explicit_port if explicit_port is not None else (443 if parts.scheme == "https" else 80)
    try:
        results = resolver(hostname, port)
    except (OSError, UnicodeError) as exc:
        raise UnsafeTargetError("source hostname could not be resolved") from exc
    if not results:
        raise UnsafeTargetError("source hostname resolved to no addresses")

    addresses: list[str] = []
    for result in results:
        try:
            raw_address = result[4][0]
        except (IndexError, TypeError) as exc:
            raise UnsafeTargetError("source resolver returned an invalid address") from exc
        address = str(_require_global_address(raw_address, source="source hostname"))
        if address not in addresses:
            addresses.append(address)
    return _ResolvedTarget(
        url=url,
        scheme=parts.scheme,
        hostname=hostname,
        port=port,
        addresses=tuple(addresses),
    )


def validate_public_url(url: str, *, resolver: Resolver = socket.getaddrinfo) -> str:
    return _resolve_public_url(url, resolver=resolver).url


def _validate_connected_peer(
    stream: httpcore.AsyncNetworkStream, *, expected_address: str, expected_port: int
) -> None:
    try:
        server_address = stream.get_extra_info("server_addr")
    except Exception as exc:
        raise UnsafeTargetError("source connection peer address could not be inspected") from exc
    if not isinstance(server_address, tuple) or len(server_address) < 2:
        raise UnsafeTargetError("source connection did not expose a valid peer address")
    peer = _require_global_address(server_address[0], source="source connection")
    if peer != ipaddress.ip_address(expected_address) or server_address[1] != expected_port:
        raise UnsafeTargetError(
            f"source connection used an unexpected peer endpoint: {peer}:{server_address[1]}"
        )


def _validated_content_length(response: httpx.Response, *, max_bytes: int) -> None:
    content_length = response.headers.get("content-length")
    if content_length is None:
        return
    value = content_length.strip()
    if not value or any(character not in "0123456789" for character in value):
        raise UnsafeTargetError("source response had an invalid Content-Length")
    if int(value) > max_bytes:
        raise UnsafeTargetError("source response exceeded maximum size")


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect an HTTP origin only to IP addresses resolved and checked by us."""

    def __init__(
        self,
        target: _ResolvedTarget,
        *,
        backend: httpcore.AsyncNetworkBackend,
    ) -> None:
        self._target = target
        self._backend = backend

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if host.casefold() != self._target.hostname or port != self._target.port:
            raise UnsafeTargetError("source connection attempted an unvalidated origin")

        started_at = time.monotonic()
        last_error: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
        for address in self._target.addresses:
            remaining = None if timeout is None else timeout - (time.monotonic() - started_at)
            if remaining is not None and remaining <= 0:
                break
            try:
                stream = await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=remaining,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
                continue
            try:
                _validate_connected_peer(stream, expected_address=address, expected_port=port)
            except BaseException:
                await stream.aclose()
                raise
            return stream

        if last_error is not None:
            raise last_error
        raise httpcore.ConnectTimeout("timed out connecting to a validated source address")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise UnsafeTargetError("Unix socket source connections are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _HttpcoreResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: AsyncIterable[bytes]) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._stream:
            yield chunk

    async def aclose(self) -> None:
        close = getattr(self._stream, "aclose", None)
        if callable(close):
            await cast(Awaitable[object], close())


class _PinnedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    """HTTPX adapter that preserves the URL host while pinning the TCP address."""

    def __init__(
        self,
        target: _ResolvedTarget,
        *,
        network_backend: httpcore.AsyncNetworkBackend,
    ) -> None:
        self._target = target
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=1,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PinnedNetworkBackend(target, backend=network_backend),
        )

    async def __aenter__(self) -> Self:
        await self._pool.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self._pool.__aexit__(exc_type, exc_value, traceback)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not isinstance(request.stream, httpx.AsyncByteStream):
            raise UnsafeTargetError("source request did not provide an asynchronous body")
        if request.url.raw_scheme.decode("ascii").casefold() != self._target.scheme:
            raise UnsafeTargetError("source request attempted an unvalidated protocol")
        response = await self._pool.handle_async_request(
            httpcore.Request(
                method=request.method,
                url=httpcore.URL(
                    scheme=request.url.raw_scheme,
                    host=request.url.raw_host,
                    port=request.url.port,
                    target=request.url.raw_path,
                ),
                headers=request.headers.raw,
                content=request.stream,
                extensions=request.extensions,
            )
        )
        if not isinstance(response.stream, AsyncIterable):
            raise UnsafeTargetError("source response did not provide an asynchronous body")
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_HttpcoreResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def _default_network_backend() -> httpcore.AsyncNetworkBackend:
    return cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())


class SafeFetcher:
    def __init__(
        self,
        policy: FetchPolicy | None = None,
        *,
        resolver: Resolver = socket.getaddrinfo,
        network_backend_factory: NetworkBackendFactory | None = None,
    ) -> None:
        self.policy = policy or FetchPolicy()
        self._resolver = resolver
        self._network_backend_factory = network_backend_factory or _default_network_backend

    async def fetch(self, url: str) -> RawArtifact:
        current = url
        headers = {"User-Agent": "AmplitudeAIRadar/0.1 (+https://github.com/He-RT/ai-radar)"}
        timeout = httpx.Timeout(self.policy.timeout_seconds)
        try:
            for _ in range(self.policy.max_redirects + 1):
                target = _resolve_public_url(current, resolver=self._resolver)
                transport = _PinnedAsyncHTTPTransport(
                    target, network_backend=self._network_backend_factory()
                )
                async with httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=False,
                    headers=headers,
                    transport=transport,
                    trust_env=False,
                ) as client, client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise UnsafeTargetError("redirect response had no location")
                        current = urljoin(current, location)
                        continue

                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                        .lower()
                    )
                    if content_type not in self.policy.allowed_content_types:
                        raise UnsafeTargetError(
                            f"unsupported content type: {content_type or 'missing'}"
                        )
                    _validated_content_length(response, max_bytes=self.policy.max_bytes)

                    body_buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body_buffer) + len(chunk) > self.policy.max_bytes:
                            raise UnsafeTargetError("source response exceeded maximum size")
                        body_buffer.extend(chunk)
                    body = bytes(body_buffer)
                    return RawArtifact(
                        requested_url=url,
                        final_url=current,
                        status_code=response.status_code,
                        content_type=content_type,
                        body=body,
                        sha256=hashlib.sha256(body).hexdigest(),
                    )
        except UnsafeTargetError:
            raise
        except Exception as exc:
            raise UnsafeTargetError("source request failed safely") from exc
        raise UnsafeTargetError("source exceeded redirect limit")
