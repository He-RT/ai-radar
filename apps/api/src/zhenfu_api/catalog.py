"""Strict, database-free runtime support for the curated source catalog."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from pydantic import AnyUrl, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic import BaseModel as PydanticBaseModel

Priority = Literal["P0", "P1", "P2", "P3"]
Authority = Literal["first_party", "regulator", "research", "media", "discovery"]
Language = Literal["en", "zh", "multilingual"]
Region = Literal["bg", "ca", "ch", "cn", "de", "eu", "fr", "global", "nl", "uk", "us"]
Connector = Literal["rss", "html", "api", "github", "arxiv", "sitemap", "manual"]
SourceType = Literal["rss", "html", "api", "github", "arxiv", "research", "sitemap", "manual"]
RiskLevel = Literal["low", "medium", "high"]
RetentionPolicy = Literal["30_days", "90_days", "365_days", "permanent"]
ManualReason = Literal[
    "access_control", "legal", "not_automatable", "paywall", "policy_review", "robots", "tls"
]

CATALOG_UUID_NAMESPACE = UUID("6e08ef48-48ee-5daf-a9b7-505d5ffd3f88")
FULL_CATALOG_SIZE = 500
MINIMUM_AUTHORITY_COVERAGE = {
    "first_party": 100,
    "regulator": 50,
    "research": 50,
    "media": 50,
}
MINIMUM_LANGUAGE_COVERAGE = {"en": 75, "zh": 75}
MAXIMUM_REPOSITORY_SIGNALS = 250
_PRIORITY_ORDER: dict[Priority, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


class CatalogLoadError(ValueError):
    """A catalog was malformed and must not be used by a worker."""


class SourceDefinition(PydanticBaseModel):
    """One source exactly as represented in the checked-in JSON catalog."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    id: Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[a-z0-9][a-z0-9-]*$")]
    name: Annotated[str, Field(min_length=1, max_length=500)]
    url: AnyUrl
    source_type: SourceType
    language: Language
    region: Region
    priority: Priority
    poll_interval_minutes: Annotated[int, Field(ge=10, le=10_080)]
    connector: Connector
    authority: Authority
    risk_level: RiskLevel
    retention_policy: RetentionPolicy
    retention_basis: Annotated[str, Field(min_length=1, max_length=1_000)]
    enabled: bool
    manual_reason: ManualReason | None = None
    notes: Annotated[str, Field(min_length=1, max_length=4_000)]

    @field_validator("url")
    @classmethod
    def url_must_be_public_https(cls, value: AnyUrl) -> AnyUrl:
        parsed = urlsplit(str(value))
        if parsed.scheme != "https":
            raise ValueError("source URL must use HTTPS")
        if not parsed.hostname:
            raise ValueError("source URL requires a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("source URL must not contain credentials")
        return value

    @model_validator(mode="after")
    def connector_matches_url(self) -> SourceDefinition:
        parsed = urlsplit(str(self.url))
        host = (parsed.hostname or "").casefold()
        compatible_connectors: dict[SourceType, frozenset[Connector]] = {
            "api": frozenset({"api"}),
            "arxiv": frozenset({"arxiv"}),
            "github": frozenset({"github"}),
            "html": frozenset({"html", "manual"}),
            "manual": frozenset({"manual"}),
            "research": frozenset({"arxiv", "html", "manual"}),
            "rss": frozenset({"rss"}),
            "sitemap": frozenset({"sitemap"}),
        }
        if self.connector not in compatible_connectors[self.source_type]:
            raise ValueError(
                f"source_type={self.source_type} is incompatible with connector={self.connector}"
            )
        if self.connector == "github":
            if host != "github.com":
                raise ValueError("github connector requires a github.com URL")
            if parsed.query or parsed.fragment or "%" in parsed.path:
                raise ValueError("github connector URL cannot contain query, fragment, or escapes")
        if self.connector == "manual":
            if self.enabled:
                raise ValueError("manual sources must be disabled from automatic scheduling")
            if self.manual_reason is None:
                raise ValueError("manual sources require manual_reason")
        elif self.manual_reason is not None:
            raise ValueError("manual_reason is only valid for manual sources")
        maximum_interval = {"P0": 10, "P1": 30, "P2": 60, "P3": 360}[self.priority]
        if self.poll_interval_minutes > maximum_interval:
            raise ValueError(
                f"{self.priority} poll interval cannot exceed {maximum_interval} minutes"
            )
        return self

    @property
    def stable_uuid(self) -> UUID:
        return stable_source_uuid(self.id)


class CatalogDefinition(PydanticBaseModel):
    """The complete source-catalog document."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    catalog: Annotated[str, Field(min_length=1, max_length=500)]
    version: Annotated[int, Field(ge=1)]
    generated_from: Annotated[str, Field(min_length=1, max_length=2_000)]
    # JSON arrays deserialize as lists.  Keeping this a list preserves strict
    # parsing while the frozen model prevents replacement of the field itself.
    sources: list[SourceDefinition]

    @model_validator(mode="after")
    def source_ids_and_urls_are_unique(self) -> CatalogDefinition:
        ids = [source.id for source in self.sources]
        urls = [str(source.url) for source in self.sources]
        duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
        duplicate_urls = sorted({value for value in urls if urls.count(value) > 1})
        if duplicate_ids:
            raise ValueError("sources: duplicate source id(s): " + ", ".join(duplicate_ids))
        if duplicate_urls:
            raise ValueError("sources: duplicate source url(s): " + ", ".join(duplicate_urls))
        return self


@dataclass(frozen=True, slots=True)
class LoadedCatalog:
    catalog: CatalogDefinition
    content_hash: str
    version: int

    @property
    def sha256(self) -> str:
        """Compatibility-friendly explicit name for the content hash."""
        return self.content_hash


@dataclass(frozen=True, slots=True)
class SourceScheduleState:
    """Worker-maintained timing state; it deliberately has no persistence dependency."""

    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        if self.consecutive_failures < 0:
            raise ValueError("consecutive_failures must be non-negative")
        for name, value in (("last_attempt_at", self.last_attempt_at), ("last_success_at", self.last_success_at)):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")


SourceRuntimeState = SourceScheduleState


def stable_source_uuid(source_id: str) -> UUID:
    """Map a catalog id to the same UUID on every process and deployment."""
    return uuid5(CATALOG_UUID_NAMESPACE, source_id)


def _validation_error_with_paths(exc: ValidationError) -> CatalogLoadError:
    paths = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "<document>"
        paths.append(f"{location}: {error['msg']}")
    return CatalogLoadError("catalog validation failed: " + "; ".join(paths))


def load_catalog(raw_or_path: bytes | Path, *, require_full_catalog: bool = False) -> LoadedCatalog:
    """Load catalog bytes or a path, failing closed before returning any source."""
    if isinstance(raw_or_path, Path):
        try:
            raw = raw_or_path.read_bytes()
        except OSError as exc:
            raise CatalogLoadError(f"catalog path {raw_or_path}: could not be read") from exc
    elif isinstance(raw_or_path, bytes):
        raw = raw_or_path
    else:
        raise TypeError("load_catalog requires bytes or pathlib.Path")

    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogLoadError(f"catalog JSON: {exc}") from exc
    try:
        catalog = CatalogDefinition.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise _validation_error_with_paths(exc) from exc
    if require_full_catalog and len(catalog.sources) != FULL_CATALOG_SIZE:
        raise CatalogLoadError(
            f"catalog.sources: expected exactly {FULL_CATALOG_SIZE}, got {len(catalog.sources)}"
        )
    if require_full_catalog:
        authority_counts = Counter(source.authority for source in catalog.sources)
        language_counts = Counter(source.language for source in catalog.sources)
        for authority, minimum in MINIMUM_AUTHORITY_COVERAGE.items():
            if authority_counts[authority] < minimum:
                raise CatalogLoadError(
                    f"catalog.sources.authority: expected at least {minimum} {authority}, "
                    f"got {authority_counts[authority]}"
                )
        for language, minimum in MINIMUM_LANGUAGE_COVERAGE.items():
            if language_counts[language] < minimum:
                raise CatalogLoadError(
                    f"catalog.sources.language: expected at least {minimum} {language}, "
                    f"got {language_counts[language]}"
                )
        repository_signals = sum(
            source.source_type == "github"
            or source.connector == "github"
            or (urlsplit(str(source.url)).hostname or "").casefold()
            in {"github.com", "huggingface.co", "modelscope.cn"}
            for source in catalog.sources
        )
        if repository_signals > MAXIMUM_REPOSITORY_SIGNALS:
            raise CatalogLoadError(
                "catalog.sources: expected at most "
                f"{MAXIMUM_REPOSITORY_SIGNALS} repository signals, got {repository_signals}"
            )
    return LoadedCatalog(
        catalog=catalog,
        content_hash=hashlib.sha256(raw).hexdigest(),
        version=catalog.version,
    )


def load_catalog_path(path: Path, *, require_full_catalog: bool = False) -> LoadedCatalog:
    return load_catalog(path, require_full_catalog=require_full_catalog)


def load_catalog_bytes(raw: bytes, *, require_full_catalog: bool = False) -> LoadedCatalog:
    return load_catalog(raw, require_full_catalog=require_full_catalog)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def next_due_at(
    source: SourceDefinition,
    state: SourceScheduleState | None = None,
    *,
    failure_backoff_base: timedelta = timedelta(minutes=5),
    failure_backoff_cap: timedelta = timedelta(hours=6),
) -> datetime | None:
    """Return the next UTC attempt time, or ``None`` for a never-attempted source."""
    if failure_backoff_base <= timedelta(0) or failure_backoff_cap <= timedelta(0):
        raise ValueError("failure backoff durations must be positive")
    if failure_backoff_base > failure_backoff_cap:
        raise ValueError("failure_backoff_base cannot exceed failure_backoff_cap")
    if state is None or (state.last_attempt_at is None and state.last_success_at is None):
        return None

    attempted = _utc(state.last_attempt_at) if state.last_attempt_at else None
    successful = _utc(state.last_success_at) if state.last_success_at else None
    if attempted is not None and (successful is None or attempted >= successful):
        failures = max(1, state.consecutive_failures)
        backoff = min(failure_backoff_base * (2 ** (failures - 1)), failure_backoff_cap)
        return attempted + backoff
    assert successful is not None
    return successful + timedelta(minutes=source.poll_interval_minutes)


def select_due_sources(
    sources: Iterable[SourceDefinition],
    states: Mapping[str | UUID, SourceScheduleState] | None,
    *,
    now: datetime,
    failure_backoff_base: timedelta = timedelta(minutes=5),
    failure_backoff_cap: timedelta = timedelta(hours=6),
) -> tuple[SourceDefinition, ...]:
    """Select enabled due sources, P0-first and stably ordered for worker dispatch."""
    current = _utc(now)
    state_by_id = states or {}
    selected: list[tuple[SourceDefinition, datetime | None]] = []
    for source in sources:
        # Manual entries are an explicit human-submission policy lane.  They
        # remain auditable catalog entries but must never enter a poll queue.
        if not source.enabled or source.connector == "manual":
            continue
        state = state_by_id.get(source.id) or state_by_id.get(source.stable_uuid)
        due_at = next_due_at(
            source,
            state,
            failure_backoff_base=failure_backoff_base,
            failure_backoff_cap=failure_backoff_cap,
        )
        if due_at is None or due_at <= current:
            selected.append((source, due_at))
    selected.sort(
        key=lambda item: (
            _PRIORITY_ORDER[item[0].priority],
            item[1] or datetime.min.replace(tzinfo=UTC),
            item[0].id,
        )
    )
    return tuple(source for source, _ in selected)


def group_by_connector(sources: Iterable[SourceDefinition]) -> dict[Connector, tuple[SourceDefinition, ...]]:
    """Create deterministic connector batches suitable for independent workers."""
    grouped: defaultdict[Connector, list[SourceDefinition]] = defaultdict(list)
    for source in sources:
        grouped[source.connector].append(source)
    return {
        connector: tuple(sorted(values, key=lambda source: source.id))
        for connector, values in sorted(grouped.items())
    }
