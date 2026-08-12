from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, cast

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from zhenfu_api.adapters.answering import Answer
from zhenfu_api.api import create_app
from zhenfu_api.auth import IdentityStore
from zhenfu_api.config import Settings
from zhenfu_api.domain.models import Event
from zhenfu_api.rate_limit import (
    HighCostGate,
    InMemoryRateLimiter,
    RateLimiter,
    RateLimiterUnavailable,
    RateLimitResult,
    RedisRateLimiter,
)
from zhenfu_api.repository import SyntheticRadarRepository


@dataclass
class RecordingLimiter:
    keys: list[str] = field(default_factory=list)

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        self.keys.append(key)
        return RateLimitResult(allowed=True, retry_after=window_seconds)

    def is_ready(self) -> bool:
        return True


class FailedLimiter:
    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        raise RateLimiterUnavailable("redis unavailable")

    def is_ready(self) -> bool:
        return False


class FailingRedis:
    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        raise ConnectionError("redis unavailable")

    def ping(self) -> bool:
        raise ConnectionError("redis unavailable")


class PersistentIdentityStore(IdentityStore):
    persistent: ClassVar[bool] = True


class ReadinessRepository(SyntheticRadarRepository):
    def __init__(self, ready: bool) -> None:
        super().__init__()
        self._ready = ready

    def is_ready(self) -> bool:
        return self._ready


@dataclass
class ReadinessLimiter:
    ready: bool

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        return RateLimitResult(allowed=True, retry_after=window_seconds)

    def is_ready(self) -> bool:
        return self.ready


@dataclass
class FlakyAnswerAdapter:
    attempts: int = 0

    def answer(self, question: str, events: list[Event]) -> Answer:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("answer failed")
        return Answer(answer="recovered", generated_by="test")


def _app(
    settings: Settings,
    *,
    rate_limiter: RateLimiter | None = None,
    high_cost_gate: HighCostGate | None = None,
    answer_adapter: FlakyAnswerAdapter | None = None,
):
    return create_app(
        settings=settings,
        repository=SyntheticRadarRepository(),
        identity_store=IdentityStore(),
        rate_limiter=rate_limiter,
        high_cost_gate=high_cost_gate,
        answer_adapter=answer_adapter,
    )


def _production_settings() -> Settings:
    return Settings(
        environment="production",
        app_secret_key="production-app-secret-with-32-characters",
        database_url="postgresql+psycopg://user:password@postgres/radar",
        valkey_url="redis://:password@valkey:6379/0",
        smtp_url="smtps://mail.example:465",
        public_base_url="https://radar.example",
        synthetic_repository=False,
    )


def test_ip_limit_resists_forwarded_header_spoofing_with_wildcard_uvicorn_trust() -> None:
    settings = Settings(environment="test", ask_ip_limit=1, ask_account_limit=100)
    # Uvicorn and Starlette expose compatible ASGI runtime interfaces but use
    # incompatible Scope aliases in their type stubs.
    app = ProxyHeadersMiddleware(_app(settings), trusted_hosts="*")  # pyright: ignore[reportArgumentType]
    with TestClient(app, client=("198.51.100.10", 50000)) as client:  # pyright: ignore[reportArgumentType]
        first = client.post(
            "/api/v1/ask",
            json={"question": "What changed?"},
            headers={"X-Forwarded-For": "203.0.113.1"},
        )
        blocked = client.post(
            "/api/v1/ask",
            json={"question": "What else changed?"},
            headers={"X-Forwarded-For": "203.0.113.2"},
        )

    assert first.status_code == 200
    assert blocked.status_code == 429
    assert blocked.headers["content-type"].startswith("application/problem+json")
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.json()["status"] == 429


def test_trusted_proxy_preserves_distinct_global_client_buckets() -> None:
    settings = Settings(environment="test", ask_ip_limit=1, ask_account_limit=100)
    app = ProxyHeadersMiddleware(
        _app(settings),  # pyright: ignore[reportArgumentType]
        trusted_hosts=["198.51.100.10"],
    )
    with TestClient(app, client=("198.51.100.10", 50000)) as client:  # pyright: ignore[reportArgumentType]
        first = client.post(
            "/api/v1/ask",
            json={"question": "What changed?"},
            headers={"X-Forwarded-For": "8.8.8.8"},
        )
        second = client.post(
            "/api/v1/ask",
            json={"question": "What else changed?"},
            headers={"X-Forwarded-For": "1.1.1.1"},
        )

    assert first.status_code == 200
    assert second.status_code == 200


def test_ask_account_limit_is_shared_across_client_ips() -> None:
    settings = Settings(environment="test", ask_ip_limit=100, ask_account_limit=1)
    app = _app(settings)
    headers = {"Authorization": "Bearer stable-ask-identity"}
    with (
        TestClient(app, client=("198.51.100.10", 50000)) as first_client,
        TestClient(app, client=("198.51.100.11", 50000)) as second_client,
    ):
        first = first_client.post(
            "/api/v1/ask",
            json={"question": "What changed?"},
            headers=headers,
        )
        blocked = second_client.post(
            "/api/v1/ask",
            json={"question": "What changed today?"},
            headers=headers,
        )

    assert first.status_code == 200
    assert blocked.status_code == 429


def test_login_enforces_ip_and_normalized_account_dimensions() -> None:
    account_settings = Settings(
        environment="test",
        login_ip_limit=100,
        login_account_limit=1,
    )
    account_app = _app(account_settings)
    with (
        TestClient(account_app, client=("198.51.100.10", 50000)) as first_client,
        TestClient(account_app, client=("198.51.100.11", 50000)) as second_client,
    ):
        first = first_client.post(
            "/api/v1/auth/login",
            json={"email": "Person@Example.com", "password": "wrong password value"},
        )
        account_blocked = second_client.post(
            "/api/v1/auth/login",
            json={"email": " person@example.COM ", "password": "wrong password value"},
        )

    ip_settings = Settings(environment="test", login_ip_limit=1, login_account_limit=100)
    ip_app = _app(ip_settings)
    with TestClient(ip_app, client=("198.51.100.20", 50000)) as client:
        client.post(
            "/api/v1/auth/login",
            json={"email": "first@example.com", "password": "wrong password value"},
        )
        ip_blocked = client.post(
            "/api/v1/auth/login",
            json={"email": "second@example.com", "password": "wrong password value"},
        )

    assert first.status_code == 401
    assert account_blocked.status_code == 429
    assert ip_blocked.status_code == 429


def test_ip_block_does_not_create_account_keys_for_distinct_emails_or_bearers() -> None:
    login_limiter = InMemoryRateLimiter()
    login_app = _app(
        Settings(environment="test", login_ip_limit=1, login_account_limit=100),
        rate_limiter=login_limiter,
    )
    with TestClient(login_app, client=("198.51.100.30", 50000)) as client:
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "seed@example.com", "password": "wrong password value"},
            ).status_code
            == 401
        )
        login_key_count = len(login_limiter._windows)
        responses = [
            client.post(
                "/api/v1/auth/login",
                json={"email": f"spray-{index}@example.com", "password": "wrong password value"},
            )
            for index in range(25)
        ]

    assert login_key_count == 2
    assert all(response.status_code == 429 for response in responses)
    assert len(login_limiter._windows) == login_key_count

    ask_limiter = InMemoryRateLimiter()
    ask_app = _app(
        Settings(environment="test", ask_ip_limit=1, ask_account_limit=100),
        rate_limiter=ask_limiter,
    )
    with TestClient(ask_app, client=("198.51.100.31", 50000)) as client:
        assert (
            client.post(
                "/api/v1/ask",
                json={"question": "What changed?"},
                headers={"Authorization": "Bearer seed-bearer"},
            ).status_code
            == 200
        )
        ask_key_count = len(ask_limiter._windows)
        responses = [
            client.post(
                "/api/v1/ask",
                json={"question": "What changed today?"},
                headers={"Authorization": f"Bearer sprayed-bearer-{index}"},
            )
            for index in range(25)
        ]

    assert ask_key_count == 2
    assert all(response.status_code == 429 for response in responses)
    assert len(ask_limiter._windows) == ask_key_count


def test_email_casefolding_and_private_keys_hide_request_data() -> None:
    settings = Settings(environment="test", login_ip_limit=100, login_account_limit=100)
    limiter = RecordingLimiter()
    app = _app(settings, rate_limiter=limiter)
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/auth/login",
            json={"email": "Editor@Example.com", "password": "wrong password value"},
        )
        second = client.post(
            "/api/v1/auth/login",
            json={"email": " editor@example.COM ", "password": "wrong password value"},
        )
        client.post("/api/v1/ask", json={"question": "Private unreleased model question"})

    assert first.status_code == second.status_code == 401
    assert limiter.keys[1] == limiter.keys[3]
    serialized_keys = " ".join(limiter.keys).casefold()
    assert "editor@example.com" not in serialized_keys
    assert "private" not in serialized_keys
    assert "question" not in serialized_keys
    assert all(key.rsplit(":", 1)[-1].isalnum() for key in limiter.keys)


def test_memory_window_recovers_deterministically() -> None:
    now = [100.0]
    limiter = InMemoryRateLimiter(clock=lambda: now[0])

    assert limiter.check("private-key", 1, 10).allowed is True
    blocked = limiter.check("private-key", 1, 10)
    assert blocked.allowed is False
    assert blocked.retry_after == 10

    now[0] = 110.0
    assert limiter.check("private-key", 1, 10).allowed is True


def test_redis_failure_is_fail_closed_for_high_cost_endpoint() -> None:
    redis_limiter = RedisRateLimiter(cast(Redis, FailingRedis()))
    with pytest.raises(RateLimiterUnavailable):
        redis_limiter.check("private-key", 1, 10)
    assert redis_limiter.is_ready() is False

    app = _app(Settings(environment="test"), rate_limiter=FailedLimiter())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "person@example.com", "password": "wrong password value"},
        )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json()["status"] == 503


def test_redis_client_uses_finite_connect_and_read_timeouts() -> None:
    limiter = RedisRateLimiter.from_url("redis://localhost:6379/0")
    options = limiter.client.connection_pool.connection_kwargs

    assert options["socket_connect_timeout"] == 1.0
    assert options["socket_timeout"] == 1.0


def test_production_readiness_requires_database_and_shared_limiter() -> None:
    healthy_app = create_app(
        settings=_production_settings(),
        repository=ReadinessRepository(ready=True),
        identity_repository=PersistentIdentityStore(),
        rate_limiter=ReadinessLimiter(ready=True),
    )
    with TestClient(healthy_app) as client:
        assert client.get("/healthz").status_code == 200
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

    limiter_unavailable_app = create_app(
        settings=_production_settings(),
        repository=ReadinessRepository(ready=True),
        identity_repository=PersistentIdentityStore(),
        rate_limiter=ReadinessLimiter(ready=False),
    )
    with TestClient(limiter_unavailable_app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_high_cost_slot_is_released_after_endpoint_failure() -> None:
    adapter = FlakyAnswerAdapter()
    gate = HighCostGate(limit=1)
    app = _app(
        Settings(environment="test", ask_ip_limit=100),
        high_cost_gate=gate,
        answer_adapter=adapter,
    )
    with TestClient(app) as client:
        with pytest.raises(RuntimeError, match="answer failed"):
            client.post("/api/v1/ask", json={"question": "First attempt"})
        recovered = client.post("/api/v1/ask", json={"question": "Second attempt"})

    assert recovered.status_code == 200
    assert recovered.json()["answer"] == "recovered"


def test_high_cost_concurrency_rejects_immediately() -> None:
    gate = HighCostGate(limit=1, retry_after=2)
    app = _app(Settings(environment="test", ask_ip_limit=100), high_cost_gate=gate)
    with gate.slot(), TestClient(app) as client:
        blocked = client.post("/api/v1/ask", json={"question": "No slot available"})

    assert blocked.status_code == 503
    assert blocked.headers["retry-after"] == "2"
