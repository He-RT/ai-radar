from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AnyHttpUrl, TypeAdapter

from zhenfu_api.domain.models import (
    ActionRecipe,
    BriefingEventSnapshot,
    BriefingSnapshot,
    Claim,
    ClaimImportance,
    Correction,
    CoverageSnapshot,
    Event,
    EventVersion,
    Evidence,
    EvidenceGrade,
    EvidenceStatus,
    PublicationState,
    RiskLevel,
    ScoreSnapshot,
    Source,
    SourceItem,
    SourceTier,
)
from zhenfu_api.domain.services import ScoreInput, deterministic_score, normalized_content_hash

HTTP_URL = TypeAdapter(AnyHttpUrl)


def http_url(value: str) -> AnyHttpUrl:
    return HTTP_URL.validate_python(value)


def stable_id(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://radar.zhenfu.example/{value}")


class RadarRepository(Protocol):
    def sources(self) -> list[Source]: ...
    def events(self) -> list[Event]: ...
    def actions(self) -> list[ActionRecipe]: ...
    def briefings(self) -> list[BriefingSnapshot]: ...
    def corrections(self) -> list[Correction]: ...


class SyntheticRadarRepository:
    """A coherent demo dataset used locally and in tests, without a database."""

    def __init__(self) -> None:
        self._sources = self._build_sources()
        self._events = self._build_events()
        self._actions = self._build_actions()
        self._briefings = [
            BriefingSnapshot(
                id=stable_id("briefing/2026-08-12"),
                briefing_date=date(2026, 8, 12),
                title="AI Radar — 12 August 2026",
                executive_summary=(
                    "Two evidence-backed developments: a model release with measurable "
                    "efficiency gains and a governance framework entering implementation."
                ),
                event_ids=[event.id for event in self._events],
                event_snapshots=[
                    BriefingEventSnapshot.from_event(event) for event in self._events
                ],
                cutoff_at=_dt(2026, 8, 11, 20, 0),
                generated_at=_dt(2026, 8, 11, 20, 5),
            )
        ]
        self._corrections = [
            Correction(
                id=stable_id("correction/benchmark-scope"),
                event_id=self._events[0].id,
                published_at=_dt(2026, 8, 12, 9, 30),
                reason="Clarified the benchmark scope after the technical appendix was released.",
                before="Efficiency improved by 40% on all workloads.",
                after="Median inference cost improved by 40% on the disclosed benchmark suite.",
            )
        ]

    @staticmethod
    def _build_sources() -> list[Source]:
        return [
            Source(
                id=stable_id("source/atlas-labs"),
                name="Atlas Labs",
                homepage_url=http_url("https://atlas.example"),
                tier=SourceTier.PRIMARY,
            ),
            Source(
                id=stable_id("source/model-evals"),
                name="Independent Model Evals",
                homepage_url=http_url("https://evals.example"),
                tier=SourceTier.AUTHORITATIVE,
            ),
            Source(
                id=stable_id("source/standards-office"),
                name="Digital Standards Office",
                homepage_url=http_url("https://standards.example"),
                tier=SourceTier.PRIMARY,
            ),
            Source(
                id=stable_id("source/policy-observer"),
                name="Policy Observatory",
                homepage_url=http_url("https://policy.example"),
                tier=SourceTier.AUTHORITATIVE,
            ),
        ]

    def _build_events(self) -> list[Event]:
        event_specs = [
            {
                "slug": "atlas-2-inference-efficiency",
                "title": "Atlas 2 reports lower inference cost on disclosed suite",
                "summary": (
                    "Atlas Labs released model and evaluation notes; an independent lab "
                    "reproduced the direction of the efficiency result with a smaller gain."
                ),
                "category": "models",
                "tags": ["model-release", "inference", "evaluation"],
                "risk": RiskLevel.MEDIUM,
                "source_indexes": (0, 1),
                "score_input": ScoreInput(0.92, 0.88, 0.86, 0.95, 0.80),
                "claim": "Atlas 2 reduces median inference cost on the disclosed suite.",
            },
            {
                "slug": "assurance-framework-implementation",
                "title": "AI assurance framework enters implementation phase",
                "summary": (
                    "The Digital Standards Office published the final assurance controls "
                    "and an independent policy group mapped the changes for deployers."
                ),
                "category": "policy",
                "tags": ["governance", "assurance", "compliance"],
                "risk": RiskLevel.LOW,
                "source_indexes": (2, 3),
                "score_input": ScoreInput(0.84, 0.91, 0.90, 0.88, 0.86),
                "claim": "The final framework establishes phased assurance controls.",
            },
        ]
        events: list[Event] = []
        for index, spec in enumerate(event_specs):
            event_id = stable_id(f"event/{spec['slug']}")
            evidences: list[Evidence] = []
            source_ids: list[UUID] = []
            for position, source_index in enumerate(spec["source_indexes"]):
                source = self._sources[source_index]
                source_ids.append(source.id)
                item_id = stable_id(f"item/{spec['slug']}/{position}")
                evidences.append(
                    Evidence(
                        id=stable_id(f"evidence/{spec['slug']}/{position}"),
                        source_item_id=item_id,
                        url=http_url(
                            f"{str(source.homepage_url).rstrip('/')}/reports/{spec['slug']}"
                        ),
                        quote=(
                            "The published material states the measured result and describes "
                            "the evaluation or implementation methodology."
                        ),
                        locator="Results, paragraph 2",
                        source_tier=source.tier,
                    )
                )
            claim = Claim(
                id=stable_id(f"claim/{spec['slug']}/main"),
                text=spec["claim"],
                importance=ClaimImportance.KEY,
                evidence_ids=[evidence.id for evidence in evidences],
                confidence=0.88,
            )
            score, components = deterministic_score(spec["score_input"])
            published = (
                _dt(2026, 8, 11, 18, 15),
                _dt(2026, 8, 11, 19, 5),
            )[index]
            version = EventVersion(
                id=stable_id(f"version/{spec['slug']}/1"),
                event_id=event_id,
                version=1,
                title=spec["title"],
                summary=spec["summary"],
                claims=[claim],
                changed_at=published,
            )
            events.append(
                Event(
                    id=event_id,
                    slug=spec["slug"],
                    title=spec["title"],
                    summary=spec["summary"],
                    category=spec["category"],
                    tags=spec["tags"],
                    published_at=published,
                    updated_at=published,
                    state=PublicationState.PUBLISHED,
                    risk=spec["risk"],
                    confidence_grade=EvidenceGrade.A,
                    evidence_status=EvidenceStatus.VERIFIED,
                    public_version=1,
                    claims=[claim],
                    evidence=evidences,
                    source_ids=source_ids,
                    score=ScoreSnapshot(
                        id=stable_id(f"score/{spec['slug']}/1"),
                        event_id=event_id,
                        score=score,
                        components=components,
                        algorithm_version="radar-score-v1",
                        calculated_at=published,
                    ),
                    versions=[version],
                )
            )
        return events

    def _build_actions(self) -> list[ActionRecipe]:
        return [
            ActionRecipe(
                id=stable_id("action/reproduce-atlas"),
                event_id=self._events[0].id,
                title="Reproduce one representative inference workload",
                audience="ML platform leads",
                effort_minutes=90,
                steps=[
                    "Select a production-shaped request sample with sensitive data removed.",
                    "Run the current and candidate models with identical decoding settings.",
                    "Compare cost, latency, quality, and failure modes before deciding.",
                ],
                expected_outcome="A workload-specific adoption decision backed by measurements.",
                caveats=["Vendor benchmarks may not represent your workload."],
            ),
            ActionRecipe(
                id=stable_id("action/assurance-gap"),
                event_id=self._events[1].id,
                title="Run a 30-minute assurance gap scan",
                audience="AI governance and product teams",
                effort_minutes=30,
                steps=[
                    "List AI systems entering production this quarter.",
                    "Map existing controls to the framework's required evidence.",
                    "Assign owners to the three highest-impact gaps.",
                ],
                expected_outcome="A prioritized control-gap list with accountable owners.",
            ),
        ]

    def sources(self) -> list[Source]:
        return list(self._sources)

    def events(self) -> list[Event]:
        return list(self._events)

    def actions(self) -> list[ActionRecipe]:
        return list(self._actions)

    def briefings(self) -> list[BriefingSnapshot]:
        return list(self._briefings)

    def corrections(self) -> list[Correction]:
        return list(self._corrections)

    def source_items(self) -> list[SourceItem]:
        items: list[SourceItem] = []
        for event in self._events:
            for position, evidence in enumerate(event.evidence):
                items.append(
                    SourceItem(
                        id=evidence.source_item_id,
                        source_id=event.source_ids[position],
                        canonical_url=evidence.url,
                        title=event.title,
                        summary=event.summary,
                        content_hash=normalized_content_hash(event.summary),
                        published_at=event.published_at,
                        entities=set(event.tags),
                    )
                )
        return items

    def coverage(self) -> CoverageSnapshot:
        categories = Counter(event.category for event in self._events)
        tier_by_id = {source.id: source.tier.value for source in self._sources}
        tiers = Counter(tier_by_id[source_id] for event in self._events for source_id in event.source_ids)
        claims = [claim for event in self._events for claim in event.claims]
        covered = sum(bool(claim.evidence_ids) for claim in claims)
        return CoverageSnapshot(
            period="2026-08-12",
            total_events=len(self._events),
            categories=dict(categories),
            source_tiers=dict(tiers),
            evidence_coverage=covered / len(claims) if claims else 1.0,
        )


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)
