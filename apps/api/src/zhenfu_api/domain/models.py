from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class RadarModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SourceTier(StrEnum):
    PRIMARY = "primary"
    AUTHORITATIVE = "authoritative"
    SECONDARY = "secondary"
    COMMUNITY = "community"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PublicationState(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    CORRECTED = "corrected"
    RETRACTED = "retracted"


class ClaimImportance(StrEnum):
    CONTEXT = "context"
    SUPPORTING = "supporting"
    KEY = "key"


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class EvidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class EvidenceStatus(StrEnum):
    VERIFIED = "verified"
    PENDING_CROSS_CHECK = "pending_cross_check"
    MONITORING = "monitoring"
    CORRECTED = "corrected"


class Source(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    homepage_url: AnyHttpUrl
    tier: SourceTier
    enabled: bool = True


class SourceItem(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    canonical_url: AnyHttpUrl
    title: str = Field(min_length=1, max_length=500)
    summary: str = ""
    content_hash: str = Field(min_length=16, max_length=128)
    published_at: datetime
    ingested_at: datetime = Field(default_factory=utcnow)
    language: str = "en"
    entities: set[str] = Field(default_factory=set)


class Evidence(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    source_item_id: UUID
    url: AnyHttpUrl
    quote: str = Field(min_length=1, max_length=2000)
    locator: str = Field(description="Paragraph, page, timestamp, or section locator")
    stance: EvidenceStance = EvidenceStance.SUPPORTS
    source_tier: SourceTier


class Claim(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    text: str = Field(min_length=1, max_length=2000)
    importance: ClaimImportance = ClaimImportance.SUPPORTING
    evidence_ids: list[UUID] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0, le=1)] = 0.5


class ScoreSnapshot(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    score: Annotated[float, Field(ge=0, le=100)]
    components: dict[str, float]
    algorithm_version: str
    calculated_at: datetime = Field(default_factory=utcnow)


class EventVersion(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    version: int = Field(ge=1)
    title: str
    summary: str
    claims: list[Claim]
    changed_at: datetime = Field(default_factory=utcnow)
    change_note: str = "initial publication"


class Event(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str
    summary: str
    category: str
    published_at: datetime
    updated_at: datetime
    state: PublicationState = PublicationState.DRAFT
    risk: RiskLevel = RiskLevel.LOW
    confidence_grade: EvidenceGrade = EvidenceGrade.C
    evidence_status: EvidenceStatus = EvidenceStatus.MONITORING
    public_version: int = Field(default=1, ge=1)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    source_ids: list[UUID] = Field(default_factory=list)
    score: ScoreSnapshot | None = None
    tags: list[str] = Field(default_factory=list)
    versions: list[EventVersion] = Field(default_factory=list)

    @model_validator(mode="after")
    def published_version_is_explicit(self) -> Event:
        if self.state in {PublicationState.PUBLISHED, PublicationState.CORRECTED}:
            if not self.versions:
                raise ValueError("published events require at least one immutable version")
            if self.public_version != max(version.version for version in self.versions):
                raise ValueError("public_version must equal the latest immutable event version")
            key_claims = [claim for claim in self.claims if claim.importance is ClaimImportance.KEY]
            if not key_claims:
                raise ValueError("published events require at least one key claim")
            evidence_by_id = {item.id: item for item in self.evidence}
            for claim in key_claims:
                supporting = [
                    evidence_by_id[evidence_id]
                    for evidence_id in claim.evidence_ids
                    if evidence_id in evidence_by_id
                    and evidence_by_id[evidence_id].stance is EvidenceStance.SUPPORTS
                ]
                if not supporting:
                    raise ValueError("every published key claim requires supporting evidence")
        return self


class ActionRecipe(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    title: str
    audience: str
    effort_minutes: int = Field(ge=1)
    steps: list[str] = Field(min_length=1)
    expected_outcome: str
    caveats: list[str] = Field(default_factory=list)


class BriefingEventSnapshot(RadarModel):
    """Versioned, self-contained public event captured by a briefing.

    The redundant identity and version pins are intentional. They make a
    truncated, reordered, or mismatched JSON envelope invalid instead of
    silently allowing a renderer to join against the mutable event ledger.
    """

    snapshot_schema_version: Literal[1]
    event_id: UUID
    public_version: int = Field(ge=1)
    event: Event

    @classmethod
    def from_event(cls, event: Event) -> BriefingEventSnapshot:
        # Round-trip through plain data so the snapshot does not retain mutable
        # nested model instances from the live event object.
        return cls.model_validate(
            {
                "snapshot_schema_version": 1,
                "event_id": event.id,
                "public_version": event.public_version,
                "event": event.model_dump(mode="python"),
            }
        )

    @model_validator(mode="after")
    def pins_a_complete_public_event(self) -> BriefingEventSnapshot:
        event = self.event
        if event.state not in {PublicationState.PUBLISHED, PublicationState.CORRECTED}:
            raise ValueError("briefing event snapshots require a public event")
        if self.event_id != event.id:
            raise ValueError("briefing event snapshot event_id must match event.id")
        if self.public_version != event.public_version:
            raise ValueError(
                "briefing event snapshot public_version must match event.public_version"
            )
        if event.score is not None and event.score.event_id != event.id:
            raise ValueError("briefing event snapshot score must reference its event")

        evidence_ids = {evidence.id for evidence in event.evidence}
        for claim in event.claims:
            if missing := set(claim.evidence_ids) - evidence_ids:
                raise ValueError(
                    "briefing event snapshot claim references missing evidence: "
                    + ", ".join(sorted(map(str, missing)))
                )
        for version in event.versions:
            if version.event_id != event.id:
                raise ValueError("briefing event snapshot version must reference its event")
            for claim in version.claims:
                if missing := set(claim.evidence_ids) - evidence_ids:
                    raise ValueError(
                        "briefing event snapshot version claim references missing evidence: "
                        + ", ".join(sorted(map(str, missing)))
                    )

        selected_version = next(
            (version for version in event.versions if version.version == event.public_version),
            None,
        )
        if selected_version is None:
            raise ValueError("briefing event snapshot is missing its pinned public version")
        if (
            selected_version.title != event.title
            or selected_version.summary != event.summary
            or selected_version.claims != event.claims
        ):
            raise ValueError(
                "briefing event snapshot facts must match the pinned public event version"
            )
        return self


class BriefingSnapshot(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    briefing_date: date
    title: str
    executive_summary: str
    event_ids: list[UUID]
    event_snapshots: list[BriefingEventSnapshot]
    cutoff_at: datetime
    generated_at: datetime = Field(default_factory=utcnow)
    state: PublicationState = PublicationState.PUBLISHED

    @model_validator(mode="after")
    def contains_a_complete_cutoff_snapshot(self) -> BriefingSnapshot:
        if self.generated_at < self.cutoff_at:
            raise ValueError("briefing cannot be generated before its knowledge cutoff")

        snapshot_ids = [snapshot.event_id for snapshot in self.event_snapshots]
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("briefing event_ids must be unique")
        if len(set(snapshot_ids)) != len(snapshot_ids):
            raise ValueError("briefing event snapshots must be unique")
        if self.event_ids != snapshot_ids:
            raise ValueError(
                "briefing event_ids must exactly match event snapshots in publication order"
            )

        for snapshot in self.event_snapshots:
            event = snapshot.event
            if event.published_at > self.cutoff_at or event.updated_at > self.cutoff_at:
                raise ValueError("briefing event snapshot contains facts newer than its cutoff")
            if event.score is not None and event.score.calculated_at > self.cutoff_at:
                raise ValueError("briefing event snapshot contains a score newer than its cutoff")
            if any(version.changed_at > self.cutoff_at for version in event.versions):
                raise ValueError("briefing event snapshot contains a version newer than its cutoff")
        return self


class Correction(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    published_at: datetime = Field(default_factory=utcnow)
    reason: str
    before: str
    after: str


class User(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password_hash: str
    display_name: str
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Team(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    owner_id: UUID
    member_ids: set[UUID] = Field(default_factory=set)

    @model_validator(mode="after")
    def owner_is_member(self) -> Team:
        self.member_ids.add(self.owner_id)
        return self


class Watch(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    team_id: UUID | None = None
    query: str
    filters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class Outbox(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    topic: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utcnow)
    published_at: datetime | None = None
    attempts: int = 0


class JobReceipt(RadarModel):
    id: UUID = Field(default_factory=uuid4)
    job_key: str
    input_hash: str
    status: str
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    output: dict[str, Any] = Field(default_factory=dict)


class CoverageSnapshot(RadarModel):
    period: str
    total_events: int
    categories: dict[str, int]
    source_tiers: dict[str, int]
    evidence_coverage: float
    generated_at: datetime = Field(default_factory=utcnow)
