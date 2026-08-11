from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from hashlib import sha256
from ipaddress import ip_address
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError

from zhenfu_api.adapters.answering import Answer, AnswerAdapter, ExtractiveAnswerStub
from zhenfu_api.auth import EDITORIAL_ROLES, IdentityRepository, IdentityStore
from zhenfu_api.config import Settings, get_settings
from zhenfu_api.domain.models import (
    ActionRecipe,
    BriefingSnapshot,
    Correction,
    CoverageSnapshot,
    Event,
    PublicationState,
    Team,
    User,
)
from zhenfu_api.domain.services import (
    PublicationRejected,
    automatic_publish_gate,
    validate_publishable,
)
from zhenfu_api.http_safety import RequestBodyLimitMiddleware
from zhenfu_api.publishing import (
    render_briefing_markdown,
    render_daily_rss,
    resolve_public_snapshot,
)
from zhenfu_api.rate_limit import (
    ConcurrencyLimitExceeded,
    HighCostGate,
    InMemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
    private_rate_limit_key,
)
from zhenfu_api.repository import RadarRepository, SyntheticRadarRepository


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=500)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def password_fits_utf8_budget(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 1024:
            raise ValueError("password must not exceed 1024 UTF-8 bytes")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("password")
    @classmethod
    def password_fits_utf8_budget(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 1024:
            raise ValueError("password must not exceed 1024 UTF-8 bytes")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    id: str
    email: str
    display_name: str
    active: bool
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserPublic":
        return cls(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            active=user.active,
            created_at=user.created_at,
        )


class TeamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=100)


class PublicationCheck(BaseModel):
    valid: bool
    automatic_publish_allowed: bool
    reasons: list[str]


class RadarResponse(BaseModel):
    generated_at: datetime
    knowledge_cutoff: datetime
    headline_events: list[Event]
    recommended_actions: list[ActionRecipe]
    latest_briefing: BriefingSnapshot | None
    coverage: CoverageSnapshot


class ReadinessResponse(BaseModel):
    status: str


class ProtectionProblem(RuntimeError):
    def __init__(self, status_code: int, title: str, detail: str, retry_after: int) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.retry_after = retry_after


_FORWARDED_IDENTITY_HEADERS = frozenset(
    {"forwarded", "x-forwarded-for", "x-forwarded-proto", "x-real-ip"}
)
_UNVERIFIED_FORWARDED_CLIENT = "unverified-forwarded-client"


def create_app(
    *,
    settings: Settings | None = None,
    repository: RadarRepository | None = None,
    answer_adapter: AnswerAdapter | None = None,
    identity_repository: IdentityRepository | None = None,
    identity_store: IdentityRepository | None = None,
    rate_limiter: RateLimiter | None = None,
    high_cost_gate: HighCostGate | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if repository is None:
        if not settings.synthetic_repository:
            raise RuntimeError("a persistent RadarRepository must be injected when demo data is disabled")
        repository = SyntheticRadarRepository()
    answer_adapter = answer_adapter or ExtractiveAnswerStub()
    if identity_repository is not None and identity_store is not None:
        raise RuntimeError("inject only one identity repository")
    identity_repository = identity_repository or identity_store
    if identity_repository is None:
        if settings.environment == "production":
            raise RuntimeError("a persistent IdentityRepository must be injected in production")
        identity_repository = IdentityStore(ttl_seconds=settings.session_ttl_seconds)
    elif settings.environment == "production" and not identity_repository.persistent:
        raise RuntimeError("production requires a persistent IdentityRepository")
    if rate_limiter is None:
        rate_limiter = (
            RedisRateLimiter.from_url(settings.valkey_url)
            if settings.environment == "production"
            else InMemoryRateLimiter()
        )
    high_cost_gate = high_cost_gate or HighCostGate(
        settings.high_cost_concurrency_limit,
        settings.high_cost_retry_after_seconds,
    )

    app = FastAPI(
        title="震幅 AI Radar API",
        summary="Evidence-first AI intelligence and action API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.repository = repository
    app.state.answer_adapter = answer_adapter
    app.state.identity_repository = identity_repository
    # Compatibility alias for integrations that inspected the original app state.
    app.state.identity_store = identity_repository
    app.state.settings = settings
    app.state.rate_limiter = rate_limiter
    app.state.high_cost_gate = high_cost_gate
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=65_536)

    bearer = HTTPBearer(auto_error=False)

    def client_identity(request: Request) -> str:
        peer = request.client.host if request.client is not None else "unknown-client"
        # Production Uvicorn trusts only Caddy's fixed container address. It
        # rewrites request.client to the public peer before FastAPI runs. A direct
        # internal caller that merely supplies forwarding headers retains its
        # private address and is collapsed into one bounded fallback bucket.
        if any(header in request.headers for header in _FORWARDED_IDENTITY_HEADERS):
            try:
                if ip_address(peer).is_global:
                    return peer
            except ValueError:
                pass
            return _UNVERIFIED_FORWARDED_CLIENT
        return peer

    def enforce_rate_limits(
        request: Request,
        *,
        scope: str,
        account_identity: str | None,
        ip_limit: int,
        account_limit: int,
        window_seconds: int,
    ) -> None:
        try:
            ip_key = private_rate_limit_key(
                settings.app_secret_key,
                scope,
                "ip",
                client_identity(request),
            )
            ip_result = rate_limiter.check(ip_key, ip_limit, window_seconds)
        except Exception as exc:
            raise ProtectionProblem(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Service Unavailable",
                "Request protection is temporarily unavailable.",
                settings.high_cost_retry_after_seconds,
            ) from exc
        if not ip_result.allowed:
            raise ProtectionProblem(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too Many Requests",
                "Rate limit exceeded for this high-cost endpoint.",
                ip_result.retry_after,
            )
        if account_identity is None:
            return
        try:
            account_key = private_rate_limit_key(
                settings.app_secret_key,
                scope,
                "account",
                account_identity,
            )
            account_result = rate_limiter.check(account_key, account_limit, window_seconds)
        except Exception as exc:
            raise ProtectionProblem(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Service Unavailable",
                "Request protection is temporarily unavailable.",
                settings.high_cost_retry_after_seconds,
            ) from exc
        if not account_result.allowed:
            raise ProtectionProblem(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too Many Requests",
                "Rate limit exceeded for this high-cost endpoint.",
                account_result.retry_after,
            )

    @contextmanager
    def high_cost_slot() -> Iterator[None]:
        try:
            with high_cost_gate.slot():
                yield
        except ConcurrencyLimitExceeded as exc:
            raise ProtectionProblem(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Service Unavailable",
                "High-cost request capacity is temporarily exhausted.",
                high_cost_gate.retry_after,
            ) from exc

    def current_user(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> User:
        if credentials is None or credentials.scheme.casefold() != "bearer":
            raise HTTPException(status_code=401, detail="authentication required")
        user = identity_repository.user_for_token(credentials.credentials)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid or expired access token")
        return user

    def editorial_user(user: Annotated[User, Depends(current_user)]) -> User:
        if identity_repository.role_for_user(user.id) not in EDITORIAL_ROLES:
            raise HTTPException(status_code=403, detail="editor or admin role required")
        return user

    @app.exception_handler(PublicationRejected)
    async def rejected_handler(_request: Request, exc: PublicationRejected) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "publication_rejected", "reasons": exc.reasons},
        )

    @app.exception_handler(ProtectionProblem)
    async def protection_handler(_request: Request, exc: ProtectionProblem) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": "about:blank",
                "title": exc.title,
                "status": exc.status_code,
                "detail": exc.detail,
            },
            headers={"Retry-After": str(exc.retry_after)},
            media_type="application/problem+json",
        )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "zhenfu-ai-radar-api", "version": "0.1.0"}

    @app.get("/healthz", tags=["system"])
    def healthz() -> dict[str, str]:
        """Liveness: the API process is able to serve requests."""
        return {"status": "ok", "service": "zhenfu-ai-radar-api"}

    @app.get(
        "/readyz",
        tags=["system"],
        response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse, "description": "Dependencies unavailable"}},
    )
    def readyz() -> JSONResponse:
        """Readiness: synthetic data is available or the configured database responds."""

        def dependency_ready(dependency: object) -> bool:
            check = getattr(dependency, "is_ready", None)
            try:
                return callable(check) and bool(check())
            except (AttributeError, OSError, RuntimeError, SQLAlchemyError):
                # Readiness must fail closed, even for a driver-specific error.
                return False

        if settings.environment == "production":
            # Authentication and high-cost endpoints fail closed if either
            # shared dependency is unavailable, so a production instance is not
            # ready until both have a fresh successful check.
            ready = dependency_ready(repository) and dependency_ready(rate_limiter)
        else:
            ready = settings.synthetic_repository or dependency_ready(repository)
        if not ready:
            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "not_ready"})
        return JSONResponse(content={"status": "ready"})

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(content=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @app.get("/api/v1/radar", tags=["public"], response_model=RadarResponse)
    def radar() -> RadarResponse:
        events = _published(repository.events())
        public_event_ids = {event.id for event in events}
        actions = [action for action in repository.actions() if action.event_id in public_event_ids]
        briefings = _public_briefings(repository.briefings())
        briefing = max(briefings, key=lambda item: item.briefing_date, default=None)
        knowledge_cutoff = briefing.cutoff_at if briefing else datetime.now(UTC)
        events = [event for event in events if event.updated_at <= knowledge_cutoff]
        return RadarResponse(
            generated_at=datetime.now(UTC),
            knowledge_cutoff=knowledge_cutoff,
            headline_events=events[:5],
            recommended_actions=actions[:3],
            latest_briefing=briefing,
            coverage=_coverage(repository),
        )

    @app.get("/api/v1/events", tags=["public"], response_model=Page[Event])
    def events(
        category: str | None = None,
        tag: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Page[Event]:
        values = _published(repository.events())
        if category:
            values = [event for event in values if event.category.casefold() == category.casefold()]
        if tag:
            values = [event for event in values if tag.casefold() in map(str.casefold, event.tags)]
        return _page(values, limit, offset)

    @app.get("/api/v1/events/{slug}", tags=["public"], response_model=Event)
    def event_detail(slug: str) -> Event:
        event = next(
            (item for item in _published(repository.events()) if item.slug == slug),
            None,
        )
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        return event

    @app.get("/api/v1/actions", tags=["public"], response_model=Page[ActionRecipe])
    def actions(
        audience: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Page[ActionRecipe]:
        public_event_ids = {event.id for event in _published(repository.events())}
        values = [item for item in repository.actions() if item.event_id in public_event_ids]
        if audience:
            values = [item for item in values if audience.casefold() in item.audience.casefold()]
        return _page(values, limit, offset)

    @app.get(
        "/api/v1/briefings/{briefing_date}.md",
        tags=["public"],
        response_class=Response,
        responses={
            200: {
                "description": "A published daily briefing in Markdown.",
                "content": {"text/markdown": {"schema": {"type": "string"}}},
            }
        },
    )
    def briefing_markdown(briefing_date: date, request: Request) -> Response:
        briefing = _briefing_for_date(repository, briefing_date)
        try:
            content = render_briefing_markdown(briefing)
        except PublicationRejected as exc:
            raise HTTPException(status_code=404, detail="briefing not found") from exc
        filename = f"briefing-{briefing.briefing_date.isoformat()}.md"
        return _public_text_response(
            request,
            content,
            "text/markdown",
            {"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get(
        "/api/v1/feeds/daily.xml",
        tags=["public"],
        response_class=Response,
        responses={
            200: {
                "description": "The latest published daily briefing as RSS 2.0.",
                "content": {"application/rss+xml": {"schema": {"type": "string"}}},
            }
        },
    )
    def daily_feed(request: Request) -> Response:
        briefing = _latest_briefing(repository)
        try:
            content = render_daily_rss(briefing, settings.public_base_url)
        except PublicationRejected as exc:
            raise HTTPException(status_code=404, detail="briefing not found") from exc
        return _public_text_response(request, content, "application/rss+xml; charset=utf-8")

    @app.get(
        "/api/v1/briefings/{briefing_date}", tags=["public"], response_model=BriefingSnapshot
    )
    def briefing(briefing_date: date) -> BriefingSnapshot:
        item = next(
            (
                value
                for value in _public_briefings(repository.briefings())
                if value.briefing_date == briefing_date
            ),
            None,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="briefing not found")
        return item

    @app.get("/api/v1/corrections", tags=["public"], response_model=Page[Correction])
    def corrections(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Page[Correction]:
        public_event_ids = {event.id for event in _published(repository.events())}
        values = sorted(
            (item for item in repository.corrections() if item.event_id in public_event_ids),
            key=lambda item: item.published_at,
            reverse=True,
        )
        return _page(values, limit, offset)

    @app.get("/api/v1/coverage", tags=["public"], response_model=CoverageSnapshot)
    def coverage() -> CoverageSnapshot:
        return _coverage(repository)

    @app.get("/api/v1/search", tags=["public"], response_model=Page[Event])
    def search(
        q: Annotated[str, Query(min_length=2, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Page[Event]:
        terms = [term for term in q.casefold().split() if term]
        values = [
            event
            for event in _published(repository.events())
            if all(
                term
                in f"{event.title} {event.summary} {' '.join(event.tags)} {event.category}".casefold()
                for term in terms
            )
        ]
        return _page(values, limit, offset)

    @app.post("/api/v1/ask", tags=["public"], response_model=Answer)
    def ask(
        payload: AskRequest,
        request: Request,
    ) -> Answer:
        account_identity: str | None = None
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.casefold() == "bearer" and token:
            user = identity_repository.user_for_token(token)
            account_identity = str(user.id) if user is not None else token
        enforce_rate_limits(
            request,
            scope="ask",
            account_identity=account_identity,
            ip_limit=settings.ask_ip_limit,
            account_limit=settings.ask_account_limit,
            window_seconds=settings.ask_window_seconds,
        )
        with high_cost_slot():
            return answer_adapter.answer(payload.question, _published(repository.events()))

    @app.post("/api/v1/auth/register", tags=["identity"], response_model=UserPublic, status_code=201)
    def register(payload: RegisterRequest, request: Request) -> UserPublic:
        enforce_rate_limits(
            request,
            scope="register",
            account_identity=payload.email.strip().casefold(),
            ip_limit=settings.register_ip_limit,
            account_limit=settings.register_account_limit,
            window_seconds=settings.register_window_seconds,
        )
        try:
            with high_cost_slot():
                user = identity_repository.register(
                    payload.email,
                    payload.password,
                    payload.display_name,
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=409 if "registered" in str(exc) else 422,
                detail=str(exc),
            ) from exc
        return UserPublic.from_user(user)

    @app.post("/api/v1/auth/login", tags=["identity"], response_model=TokenResponse)
    def login(payload: LoginRequest, request: Request) -> TokenResponse:
        enforce_rate_limits(
            request,
            scope="login",
            account_identity=payload.email.strip().casefold(),
            ip_limit=settings.login_ip_limit,
            account_limit=settings.login_account_limit,
            window_seconds=settings.login_window_seconds,
        )
        with high_cost_slot():
            token = identity_repository.login(payload.email, payload.password)
        if token is None:
            raise HTTPException(status_code=401, detail="invalid credentials")
        return TokenResponse(access_token=token)

    @app.get("/api/v1/users/me", tags=["identity"], response_model=UserPublic)
    def me(user: Annotated[User, Depends(current_user)]) -> UserPublic:
        return UserPublic.from_user(user)

    @app.post("/api/v1/teams", tags=["identity"], response_model=Team, status_code=201)
    def create_team(
        payload: TeamRequest,
        user: Annotated[User, Depends(current_user)],
    ) -> Team:
        try:
            return identity_repository.create_team(user, payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/teams", tags=["identity"], response_model=list[Team])
    def teams(user: Annotated[User, Depends(current_user)]) -> list[Team]:
        return identity_repository.teams_for_user(user.id)

    @app.post(
        "/api/v1/internal/events/{slug}/publication-check",
        tags=["editorial"],
        response_model=PublicationCheck,
    )
    def publication_check(
        slug: str,
        _user: Annotated[User, Depends(editorial_user)],
    ) -> PublicationCheck:
        event = next((item for item in repository.events() if item.slug == slug), None)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        reasons: list[str] = []
        try:
            validate_publishable(event)
        except PublicationRejected as exc:
            reasons.extend(exc.reasons)
        decision = automatic_publish_gate(event)
        return PublicationCheck(
            valid=not reasons,
            automatic_publish_allowed=decision.allowed,
            reasons=list(dict.fromkeys([*reasons, *decision.reasons])),
        )

    return app


def _published(events: list[Event]) -> list[Event]:
    public: list[Event] = []
    for event in events:
        if event.state not in {PublicationState.PUBLISHED, PublicationState.CORRECTED}:
            continue
        try:
            validate_publishable(event)
        except PublicationRejected:
            continue
        public.append(event)
    return sorted(
        public,
        key=lambda event: ((event.score.score if event.score else 0), event.published_at),
        reverse=True,
    )


def _page[T](values: list[T], limit: int, offset: int) -> Page[T]:
    return Page(items=values[offset : offset + limit], total=len(values), limit=limit, offset=offset)


def _public_briefings(briefings: list[BriefingSnapshot]) -> list[BriefingSnapshot]:
    public: list[BriefingSnapshot] = []
    for briefing in briefings:
        try:
            resolve_public_snapshot(briefing)
        except PublicationRejected:
            continue
        public.append(briefing)
    return public


def _briefing_for_date(repository: RadarRepository, briefing_date: date) -> BriefingSnapshot:
    briefing = next(
        (
            item
            for item in _public_briefings(repository.briefings())
            if item.briefing_date == briefing_date
        ),
        None,
    )
    if briefing is None:
        raise HTTPException(status_code=404, detail="briefing not found")
    return briefing


def _latest_briefing(repository: RadarRepository) -> BriefingSnapshot:
    briefings = _public_briefings(repository.briefings())
    if not briefings:
        raise HTTPException(status_code=404, detail="briefing not found")
    return max(briefings, key=lambda item: item.briefing_date)


def _public_text_response(
    request: Request,
    content: str,
    media_type: str,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    encoded = content.encode("utf-8")
    etag = f'"{sha256(encoded).hexdigest()}"'
    headers = {
        "Cache-Control": "public, max-age=300, must-revalidate",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
        **(extra_headers or {}),
    }
    if _if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=encoded, media_type=media_type, headers=headers)


def _if_none_match_matches(value: str | None, etag: str) -> bool:
    if value is None:
        return False
    return any(
        candidate == "*" or candidate.removeprefix("W/") == etag
        for candidate in (candidate.strip() for candidate in value.split(","))
    )


def _coverage(repository: RadarRepository) -> CoverageSnapshot:
    coverage_method = getattr(repository, "coverage", None)
    if coverage_method is None:
        raise HTTPException(status_code=501, detail="coverage is not implemented by repository")
    return coverage_method()
