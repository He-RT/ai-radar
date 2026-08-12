"""Bounded catalog-source dispatch from a validated definition to candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast
from urllib.parse import urlsplit

from zhenfu_api.catalog import SourceDefinition

from .connectors import (
    MAX_CANDIDATES,
    Candidate,
    GitHubAdvisoryConnector,
    GitHubReleaseConnector,
    GitHubRepositoryConnector,
    HTMLConnector,
    RSSConnector,
    SitemapConnector,
)
from .security import RawArtifact, SafeFetcher


class UnsupportedSourceError(ValueError):
    """A source has no deliberately implemented runtime behavior."""


class RuntimeDisposition(StrEnum):
    SUPPORTED = "supported"
    POLICY_SKIP = "policy_skip"


class RuntimeOperation(StrEnum):
    HTML_PAGE = "html_page"
    RSS_FEED = "rss_feed"
    SITEMAP = "sitemap"
    GITHUB_REPOSITORY = "github_repository"
    GITHUB_RELEASES = "github_releases"
    GITHUB_ADVISORIES = "github_advisories"
    POLICY_SKIP = "policy_skip"


class DispatchStatus(StrEnum):
    SUCCEEDED = "succeeded"
    POLICY_SKIPPED = "policy_skipped"
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"


@dataclass(frozen=True, slots=True)
class SourceRuntimePlan:
    source_id: str
    disposition: RuntimeDisposition
    operation: RuntimeOperation
    fetch_url: str | None
    candidate_base_url: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeCoverage:
    total: int
    supported: int
    policy_skip: int
    unsupported_source_ids: tuple[str, ...]

    @property
    def unsupported(self) -> int:
        return len(self.unsupported_source_ids)


@dataclass(frozen=True, slots=True)
class DispatchReceipt:
    source_id: str
    source_uuid: str
    disposition: RuntimeDisposition
    operation: RuntimeOperation
    status: DispatchStatus
    fetch_url: str | None
    artifact_sha256: str | None
    candidates: tuple[Candidate, ...]
    started_at: datetime
    finished_at: datetime
    reason: str = ""

    @property
    def terminal(self) -> bool:
        return True

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def idempotency_key(self) -> str:
        material = "\x00".join(
            (
                self.source_id,
                self.operation.value,
                self.artifact_sha256 or self.disposition.value,
            )
        )
        return hashlib.sha256(material.encode()).hexdigest()


class ArtifactFetcher(Protocol):
    async def fetch(self, url: str) -> RawArtifact: ...


_GITHUB_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_GITHUB_POLICY_PATHS = frozenset({"issue", "issues", "pull", "pulls"})


def _github_runtime_plan(source: SourceDefinition) -> SourceRuntimePlan:
    parts = urlsplit(str(source.url))
    if (
        parts.scheme != "https"
        or (parts.hostname or "").casefold() != "github.com"
        or parts.port not in {None, 443}
        or parts.query
        or parts.fragment
        or "%" in parts.path
    ):
        raise UnsupportedSourceError(f"{source.id}: unsupported GitHub source URL")

    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2:
        raise UnsupportedSourceError(f"{source.id}: GitHub source URL requires owner/repository")
    owner, repository = segments[:2]
    repository = repository.removesuffix(".git")
    if (
        not owner
        or not repository
        or not _GITHUB_SEGMENT.fullmatch(owner)
        or not _GITHUB_SEGMENT.fullmatch(repository)
        or owner in {".", ".."}
        or repository in {".", ".."}
    ):
        raise UnsupportedSourceError(f"{source.id}: invalid GitHub owner/repository")

    suffix = [segment.casefold() for segment in segments[2:]]
    candidate_base_url = f"https://github.com/{owner}/{repository}"
    api_base_url = f"https://api.github.com/repos/{owner}/{repository}"
    if not suffix:
        return SourceRuntimePlan(
            source_id=source.id,
            disposition=RuntimeDisposition.SUPPORTED,
            operation=RuntimeOperation.GITHUB_REPOSITORY,
            fetch_url=api_base_url,
            candidate_base_url=candidate_base_url,
        )
    if suffix == ["releases"]:
        return SourceRuntimePlan(
            source_id=source.id,
            disposition=RuntimeDisposition.SUPPORTED,
            operation=RuntimeOperation.GITHUB_RELEASES,
            fetch_url=f"{api_base_url}/releases?per_page={MAX_CANDIDATES}",
            candidate_base_url=candidate_base_url,
        )
    if suffix in (["security"], ["security", "advisories"]):
        return SourceRuntimePlan(
            source_id=source.id,
            disposition=RuntimeDisposition.SUPPORTED,
            operation=RuntimeOperation.GITHUB_ADVISORIES,
            fetch_url=f"{api_base_url}/security-advisories?per_page={MAX_CANDIDATES}",
            candidate_base_url=candidate_base_url,
        )
    if suffix and suffix[0] in _GITHUB_POLICY_PATHS:
        return SourceRuntimePlan(
            source_id=source.id,
            disposition=RuntimeDisposition.POLICY_SKIP,
            operation=RuntimeOperation.POLICY_SKIP,
            fetch_url=None,
            candidate_base_url=candidate_base_url,
            reason="GitHub issues and pull requests are not independent catalog sources",
        )
    raise UnsupportedSourceError(f"{source.id}: unsupported GitHub repository path")


def runtime_plan(source: SourceDefinition) -> SourceRuntimePlan:
    """Return the sole runtime action for a source, failing closed when absent."""
    source_url = str(source.url)
    if source.connector == "html":
        return SourceRuntimePlan(
            source.id,
            RuntimeDisposition.SUPPORTED,
            RuntimeOperation.HTML_PAGE,
            source_url,
            source_url,
        )
    if source.connector == "rss":
        return SourceRuntimePlan(
            source.id,
            RuntimeDisposition.SUPPORTED,
            RuntimeOperation.RSS_FEED,
            source_url,
            source_url,
        )
    if source.connector == "sitemap":
        return SourceRuntimePlan(
            source.id,
            RuntimeDisposition.SUPPORTED,
            RuntimeOperation.SITEMAP,
            source_url,
            source_url,
        )
    if source.connector == "github":
        return _github_runtime_plan(source)
    if source.connector == "manual":
        return SourceRuntimePlan(
            source.id,
            RuntimeDisposition.POLICY_SKIP,
            RuntimeOperation.POLICY_SKIP,
            None,
            source_url,
            "manual sources require an explicit human submission and are never scheduled",
        )
    raise UnsupportedSourceError(
        f"{source.id}: connector {source.connector!r} has no runtime implementation"
    )


def catalog_runtime_coverage(sources: list[SourceDefinition]) -> RuntimeCoverage:
    """Statically classify catalog entries without performing network access."""
    supported = 0
    policy_skip = 0
    unsupported: list[str] = []
    for source in sources:
        try:
            plan = runtime_plan(source)
        except UnsupportedSourceError:
            unsupported.append(source.id)
            continue
        if plan.disposition is RuntimeDisposition.SUPPORTED:
            supported += 1
        else:
            policy_skip += 1
    return RuntimeCoverage(
        total=len(sources),
        supported=supported,
        policy_skip=policy_skip,
        unsupported_source_ids=tuple(sorted(unsupported)),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json_object_array(artifact: RawArtifact) -> list[dict[str, object]]:
    if artifact.content_type != "application/json":
        raise ValueError("GitHub response was not JSON")
    payload = json.loads(artifact.body)
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise ValueError("GitHub response must be an array of objects")
    return cast(list[dict[str, object]], payload)


def _json_object(artifact: RawArtifact) -> dict[str, object]:
    if artifact.content_type != "application/json":
        raise ValueError("GitHub response was not JSON")
    payload = json.loads(artifact.body)
    if not isinstance(payload, dict):
        raise TypeError("GitHub response must be an object")
    return cast(dict[str, object], payload)


class IngestionDispatcher:
    """Fetch and parse exactly one validated catalog source into a terminal receipt."""

    def __init__(
        self,
        fetcher: ArtifactFetcher | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._fetcher = fetcher or SafeFetcher()
        self._clock = clock

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("dispatcher clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    async def dispatch(self, source: SourceDefinition) -> DispatchReceipt:
        plan = runtime_plan(source)
        started_at = self._now()
        if plan.disposition is RuntimeDisposition.POLICY_SKIP:
            return DispatchReceipt(
                source_id=source.id,
                source_uuid=str(source.stable_uuid),
                disposition=plan.disposition,
                operation=plan.operation,
                status=DispatchStatus.POLICY_SKIPPED,
                fetch_url=None,
                artifact_sha256=None,
                candidates=(),
                started_at=started_at,
                finished_at=self._now(),
                reason=plan.reason,
            )

        assert plan.fetch_url is not None
        try:
            artifact = await self._fetcher.fetch(plan.fetch_url)
        # The injectable boundary may use a different HTTP client.  All
        # implementation errors become the same non-sensitive terminal state.
        except Exception:  # noqa: BLE001
            return DispatchReceipt(
                source_id=source.id,
                source_uuid=str(source.stable_uuid),
                disposition=plan.disposition,
                operation=plan.operation,
                status=DispatchStatus.FETCH_FAILED,
                fetch_url=plan.fetch_url,
                artifact_sha256=None,
                candidates=(),
                started_at=started_at,
                finished_at=self._now(),
                reason="source fetch failed safely",
            )

        if not 200 <= artifact.status_code < 300:
            return DispatchReceipt(
                source_id=source.id,
                source_uuid=str(source.stable_uuid),
                disposition=plan.disposition,
                operation=plan.operation,
                status=DispatchStatus.FETCH_FAILED,
                fetch_url=plan.fetch_url,
                artifact_sha256=artifact.sha256,
                candidates=(),
                started_at=started_at,
                finished_at=self._now(),
                reason=f"source returned HTTP {artifact.status_code}",
            )

        try:
            candidates = self._parse(plan, source, artifact)
        # XML, HTML, and injected parser implementations do not share one
        # exception hierarchy.  All parser failures terminate identically.
        except Exception:  # noqa: BLE001
            return DispatchReceipt(
                source_id=source.id,
                source_uuid=str(source.stable_uuid),
                disposition=plan.disposition,
                operation=plan.operation,
                status=DispatchStatus.PARSE_FAILED,
                fetch_url=plan.fetch_url,
                artifact_sha256=artifact.sha256,
                candidates=(),
                started_at=started_at,
                finished_at=self._now(),
                reason="source payload could not be parsed safely",
            )

        return DispatchReceipt(
            source_id=source.id,
            source_uuid=str(source.stable_uuid),
            disposition=plan.disposition,
            operation=plan.operation,
            status=DispatchStatus.SUCCEEDED,
            fetch_url=plan.fetch_url,
            artifact_sha256=artifact.sha256,
            candidates=tuple(candidates[:MAX_CANDIDATES]),
            started_at=started_at,
            finished_at=self._now(),
        )

    @staticmethod
    def _parse(
        plan: SourceRuntimePlan, source: SourceDefinition, artifact: RawArtifact
    ) -> list[Candidate]:
        if plan.operation is RuntimeOperation.HTML_PAGE:
            if artifact.content_type != "text/html":
                raise ValueError("HTML source returned a non-HTML payload")
            return HTMLConnector().discover(
                artifact.body,
                source_id=source.stable_uuid,
                base_url=artifact.final_url,
            )
        if plan.operation is RuntimeOperation.RSS_FEED:
            return RSSConnector().discover(
                artifact.body,
                source_id=source.stable_uuid,
                base_url=artifact.final_url,
            )
        if plan.operation is RuntimeOperation.SITEMAP:
            return SitemapConnector().discover(
                artifact.body,
                source_id=source.stable_uuid,
                base_url=artifact.final_url,
            )
        if plan.operation is RuntimeOperation.GITHUB_REPOSITORY:
            return GitHubRepositoryConnector().discover_json(
                _json_object(artifact),
                source_id=source.stable_uuid,
                base_url=plan.candidate_base_url,
            )
        payload = _json_object_array(artifact)
        if plan.operation is RuntimeOperation.GITHUB_RELEASES:
            return GitHubReleaseConnector().discover_json(
                payload,
                source_id=source.stable_uuid,
                base_url=plan.candidate_base_url,
            )
        if plan.operation is RuntimeOperation.GITHUB_ADVISORIES:
            return GitHubAdvisoryConnector().discover_json(
                payload,
                source_id=source.stable_uuid,
                base_url=plan.candidate_base_url,
            )
        raise UnsupportedSourceError(f"{source.id}: dispatch operation is not parseable")
