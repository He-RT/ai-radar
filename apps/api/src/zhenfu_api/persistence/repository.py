from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Select, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

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
    EvidenceStance,
    EvidenceStatus,
    PublicationState,
    RiskLevel,
    ScoreSnapshot,
    Source,
    SourceItem,
    SourceTier,
)
from zhenfu_api.domain.services import PublicationRejected, validate_publishable
from zhenfu_api.repository import RadarRepository, http_url

from .tables import (
    ActionRecipeRecord,
    BriefingSnapshotRecord,
    ClaimRecord,
    CorrectionRecord,
    EventRecord,
    EventVersionRecord,
    EvidenceRecord,
    ScoreSnapshotRecord,
    SourceItemRecord,
    SourceRecord,
    claim_evidence,
    event_sources,
)

Record = TypeVar("Record")


class SqlRadarRepository(RadarRepository):
    """Read-only Radar repository backed by the production SQLAlchemy schema.

    Records are mapped into the domain models rather than returned as database
    objects.  A malformed public event is deliberately omitted: it is safer to
    hide it than to expose a claim whose evidentiary graph is incomplete.
    """

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def is_ready(self) -> bool:
        """Return whether a fresh database session can execute a trivial query."""
        try:
            with self._sessions() as session:
                session.execute(text("SELECT 1")).scalar_one()
        except SQLAlchemyError:
            return False
        return True

    def sources(self) -> list[Source]:
        with self._sessions() as session:
            records = self._all(session, select(SourceRecord).order_by(SourceRecord.name))
        return [self._source(record) for record in records]

    def source_items(self) -> list[SourceItem]:
        with self._sessions() as session:
            records = self._all(session, select(SourceItemRecord).order_by(SourceItemRecord.published_at))
        return [self._source_item(record) for record in records]

    def events(self) -> list[Event]:
        with self._sessions() as session:
            event_records = self._all(
                session,
                select(EventRecord).order_by(EventRecord.published_at.desc(), EventRecord.slug),
            )
            claim_records = self._all(session, select(ClaimRecord))
            evidence_records = self._all(session, select(EvidenceRecord))
            version_records = self._all(session, select(EventVersionRecord))
            score_records = self._all(session, select(ScoreSnapshotRecord))
            claim_evidence_rows = session.execute(
                select(claim_evidence.c.claim_id, claim_evidence.c.evidence_id)
            ).all()
            event_source_rows = session.execute(
                select(event_sources.c.event_id, event_sources.c.source_id)
            ).all()

        claims_by_event: dict[UUID, list[ClaimRecord]] = defaultdict(list)
        for claim in claim_records:
            claims_by_event[claim.event_id].append(claim)
        evidence_by_id = {evidence.id: evidence for evidence in evidence_records}
        evidence_ids_by_claim: dict[UUID, list[UUID]] = defaultdict(list)
        for claim_id, evidence_id in claim_evidence_rows:
            evidence_ids_by_claim[claim_id].append(evidence_id)
        versions_by_event: dict[UUID, list[EventVersionRecord]] = defaultdict(list)
        for version in version_records:
            versions_by_event[version.event_id].append(version)
        scores_by_event: dict[UUID, list[ScoreSnapshotRecord]] = defaultdict(list)
        for score in score_records:
            scores_by_event[score.event_id].append(score)
        source_ids_by_event: dict[UUID, list[UUID]] = defaultdict(list)
        for event_id, source_id in event_source_rows:
            source_ids_by_event[event_id].append(source_id)

        events: list[Event] = []
        for record in event_records:
            try:
                event = self._event(
                    record,
                    claims_by_event[record.id],
                    evidence_ids_by_claim,
                    evidence_by_id,
                    versions_by_event[record.id],
                    scores_by_event[record.id],
                    source_ids_by_event[record.id],
                )
                if event.state in {PublicationState.PUBLISHED, PublicationState.CORRECTED}:
                    validate_publishable(event)
            except (PublicationRejected, ValidationError, TypeError, ValueError):
                # This is a public-read fail-closed boundary.  Never surface a
                # partially persisted published/corrected event.
                continue
            events.append(event)
        return events

    def actions(self) -> list[ActionRecipe]:
        with self._sessions() as session:
            records = self._all(session, select(ActionRecipeRecord).order_by(ActionRecipeRecord.title))
        return [
            ActionRecipe(
                id=record.id,
                event_id=record.event_id,
                title=record.title,
                audience=record.audience,
                effort_minutes=record.effort_minutes,
                steps=list(record.steps),
                expected_outcome=record.expected_outcome,
                caveats=list(record.caveats),
            )
            for record in records
        ]

    def briefings(self) -> list[BriefingSnapshot]:
        with self._sessions() as session:
            records = self._all(
                session,
                select(BriefingSnapshotRecord).order_by(BriefingSnapshotRecord.briefing_date.desc()),
            )
        briefings: list[BriefingSnapshot] = []
        for record in records:
            try:
                if not isinstance(record.event_snapshots, list):
                    # Legacy ID-only rows are deliberately not reconstructed
                    # from today's events: doing so would falsify the cutoff.
                    continue
                briefing = BriefingSnapshot(
                    id=record.id,
                    briefing_date=record.briefing_date,
                    title=record.title,
                    executive_summary=record.executive_summary,
                    event_ids=[UUID(str(event_id)) for event_id in record.event_ids],
                    event_snapshots=[
                        BriefingEventSnapshot.model_validate(snapshot)
                        for snapshot in record.event_snapshots
                    ],
                    cutoff_at=_utc(record.cutoff_at),
                    generated_at=_utc(record.generated_at),
                    state=PublicationState(record.state),
                )
            except (AttributeError, TypeError, ValidationError, ValueError):
                # Snapshot integrity is a public-read boundary. A partial or
                # mismatched persisted payload must never reach a renderer.
                continue
            briefings.append(briefing)
        return briefings

    def corrections(self) -> list[Correction]:
        with self._sessions() as session:
            records = self._all(
                session,
                select(CorrectionRecord).order_by(CorrectionRecord.published_at.desc()),
            )
        return [
            Correction(
                id=record.id,
                event_id=record.event_id,
                published_at=_utc(record.published_at),
                reason=record.reason,
                before=record.before,
                after=record.after,
            )
            for record in records
        ]

    def coverage(self) -> CoverageSnapshot:
        events = self.events()
        sources = {source.id: source for source in self.sources()}
        claims = [claim for event in events for claim in event.claims]
        categories = Counter(event.category for event in events)
        source_tiers = Counter(
            sources[source_id].tier.value
            for event in events
            for source_id in event.source_ids
            if source_id in sources
        )
        return CoverageSnapshot(
            period=datetime.now(UTC).date().isoformat(),
            total_events=len(events),
            categories=dict(categories),
            source_tiers=dict(source_tiers),
            evidence_coverage=(sum(bool(claim.evidence_ids) for claim in claims) / len(claims))
            if claims
            else 1.0,
        )

    @staticmethod
    def _all(session: Session, statement: Select[tuple[Record]]) -> list[Record]:
        return list(session.scalars(statement))

    @staticmethod
    def _source(record: SourceRecord) -> Source:
        return Source(
            id=record.id,
            name=record.name,
            homepage_url=http_url(record.homepage_url),
            tier=SourceTier(record.tier),
            enabled=record.enabled,
        )

    @staticmethod
    def _source_item(record: SourceItemRecord) -> SourceItem:
        return SourceItem(
            id=record.id,
            source_id=record.source_id,
            canonical_url=http_url(record.canonical_url),
            title=record.title,
            summary=record.summary,
            content_hash=record.content_hash,
            published_at=_utc(record.published_at),
            ingested_at=_utc(record.ingested_at),
            language=record.language,
            entities=set(record.entities),
        )

    def _event(
        self,
        record: EventRecord,
        claim_records: list[ClaimRecord],
        evidence_ids_by_claim: dict[UUID, list[UUID]],
        evidence_by_id: dict[UUID, EvidenceRecord],
        version_records: list[EventVersionRecord],
        score_records: list[ScoreSnapshotRecord],
        source_ids: list[UUID],
    ) -> Event:
        if record.published_at is None or record.updated_at is None:
            raise ValueError("events exposed through the repository require publication timestamps")
        claims = [
            Claim(
                id=claim.id,
                text=claim.text,
                importance=ClaimImportance(claim.importance),
                evidence_ids=list(evidence_ids_by_claim[claim.id]),
                confidence=claim.confidence,
            )
            for claim in claim_records
        ]
        evidence_ids = {
            evidence_id
            for claim in claim_records
            for evidence_id in evidence_ids_by_claim[claim.id]
        }
        evidence = [
            Evidence(
                id=evidence_by_id[evidence_id].id,
                source_item_id=evidence_by_id[evidence_id].source_item_id,
                url=http_url(evidence_by_id[evidence_id].url),
                quote=evidence_by_id[evidence_id].quote,
                locator=evidence_by_id[evidence_id].locator,
                stance=EvidenceStance(evidence_by_id[evidence_id].stance),
                source_tier=SourceTier(evidence_by_id[evidence_id].source_tier),
            )
            for evidence_id in sorted(evidence_ids, key=str)
            if evidence_id in evidence_by_id
        ]
        versions = [
            EventVersion(
                id=version.id,
                event_id=version.event_id,
                version=version.version,
                title=version.title,
                summary=version.summary,
                claims=[Claim.model_validate(claim) for claim in version.claims],
                changed_at=_utc(version.changed_at),
                change_note=version.change_note,
            )
            for version in sorted(version_records, key=lambda value: value.version)
        ]
        score = self._latest_score(record.id, score_records)
        return Event(
            id=record.id,
            slug=record.slug,
            title=record.title,
            summary=record.summary,
            category=record.category,
            tags=list(record.tags),
            published_at=_utc(record.published_at),
            updated_at=_utc(record.updated_at),
            state=PublicationState(record.state),
            risk=RiskLevel(record.risk),
            confidence_grade=EvidenceGrade(record.confidence_grade),
            evidence_status=EvidenceStatus(record.evidence_status),
            public_version=record.public_version,
            claims=claims,
            evidence=evidence,
            source_ids=list(source_ids),
            score=score,
            versions=versions,
        )

    @staticmethod
    def _latest_score(event_id: UUID, scores: list[ScoreSnapshotRecord]) -> ScoreSnapshot | None:
        if not scores:
            return None
        record = max(scores, key=lambda value: _utc(value.calculated_at))
        return ScoreSnapshot(
            id=record.id,
            event_id=event_id,
            score=record.score,
            components=record.components,
            algorithm_version=record.algorithm_version,
            calculated_at=_utc(record.calculated_at),
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
