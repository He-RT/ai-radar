from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


claim_evidence = Table(
    "claim_evidence",
    Base.metadata,
    Column("claim_id", Uuid(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True),
    Column("evidence_id", Uuid(as_uuid=True), ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True),
)

event_sources = Table(
    "event_sources",
    Base.metadata,
    Column("event_id", Uuid(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("source_id", Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"), primary_key=True),
)

team_members = Table(
    "team_members",
    Base.metadata,
    Column("team_id", Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceRecord(Base, TimestampMixin):
    __tablename__ = "sources"
    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    homepage_url: Mapped[str] = mapped_column(String(2048))
    tier: Mapped[str] = mapped_column(String(32), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SourceItemRecord(Base):
    __tablename__ = "source_items"
    __table_args__ = (UniqueConstraint("canonical_url"), UniqueConstraint("content_hash", "source_id"))
    id: Mapped[UUID] = uuid_pk()
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)
    canonical_url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    language: Mapped[str] = mapped_column(String(16), default="en")
    entities: Mapped[list[str]] = mapped_column(JSON, default=list)


class EventRecord(Base, TimestampMixin):
    __tablename__ = "events"
    id: Mapped[UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True, default="draft")
    risk: Mapped[str] = mapped_column(String(32), index=True, default="low")
    confidence_grade: Mapped[str] = mapped_column(String(1), index=True, default="C")
    evidence_status: Mapped[str] = mapped_column(String(32), index=True, default="monitoring")
    public_version: Mapped[int] = mapped_column(Integer, default=1)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class EvidenceRecord(Base, TimestampMixin):
    __tablename__ = "evidence"
    id: Mapped[UUID] = uuid_pk()
    source_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_items.id", ondelete="RESTRICT"), index=True
    )
    url: Mapped[str] = mapped_column(String(2048))
    quote: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(500))
    stance: Mapped[str] = mapped_column(String(32), index=True)
    source_tier: Mapped[str] = mapped_column(String(32))


class ClaimRecord(Base, TimestampMixin):
    __tablename__ = "claims"
    id: Mapped[UUID] = uuid_pk()
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    importance: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float)


class EventVersionRecord(Base):
    __tablename__ = "event_versions"
    __table_args__ = (UniqueConstraint("event_id", "version"),)
    id: Mapped[UUID] = uuid_pk()
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    change_note: Mapped[str] = mapped_column(Text)


class ScoreSnapshotRecord(Base):
    __tablename__ = "score_snapshots"
    id: Mapped[UUID] = uuid_pk()
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    components: Mapped[dict[str, float]] = mapped_column(JSON)
    algorithm_version: Mapped[str] = mapped_column(String(64))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActionRecipeRecord(Base, TimestampMixin):
    __tablename__ = "action_recipes"
    id: Mapped[UUID] = uuid_pk()
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    audience: Mapped[str] = mapped_column(String(200), index=True)
    effort_minutes: Mapped[int] = mapped_column(Integer)
    steps: Mapped[list[str]] = mapped_column(JSON)
    expected_outcome: Mapped[str] = mapped_column(Text)
    caveats: Mapped[list[str]] = mapped_column(JSON, default=list)


class BriefingSnapshotRecord(Base):
    __tablename__ = "briefing_snapshots"
    id: Mapped[UUID] = uuid_pk()
    briefing_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    executive_summary: Mapped[str] = mapped_column(Text)
    event_ids: Mapped[list[str]] = mapped_column(JSON)
    # Nullable only for pre-0003 rows, which cannot be truthfully backfilled
    # from the mutable event ledger. Public repository reads fail closed when
    # this immutable payload is absent or invalid.
    event_snapshots: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    state: Mapped[str] = mapped_column(String(32), index=True)


class CorrectionRecord(Base):
    __tablename__ = "corrections"
    id: Mapped[UUID] = uuid_pk()
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str] = mapped_column(Text)
    before: Mapped[str] = mapped_column(Text)
    after: Mapped[str] = mapped_column(Text)


class UserRecord(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    display_name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(32), default="user", server_default="user", index=True)


class IdentitySessionRecord(Base):
    __tablename__ = "identity_sessions"
    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class TeamRecord(Base, TimestampMixin):
    __tablename__ = "teams"
    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100))
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)


class WatchRecord(Base, TimestampMixin):
    __tablename__ = "watches"
    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(String(500))
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class OutboxRecord(Base):
    __tablename__ = "outbox"
    id: Mapped[UUID] = uuid_pk()
    topic: Mapped[str] = mapped_column(String(200), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class JobReceiptRecord(Base):
    __tablename__ = "job_receipts"
    __table_args__ = (UniqueConstraint("job_key", "input_hash"),)
    id: Mapped[UUID] = uuid_pk()
    job_key: Mapped[str] = mapped_column(String(200), index=True)
    input_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
