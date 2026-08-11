from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ItemTerminalStatus(StrEnum):
    PUBLISHED = "published"
    MERGED = "merged"
    LOW_SCORE = "low_score"
    UNCONFIRMED = "unconfirmed"
    HUMAN_REVIEW = "human_review"
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"
    POLICY_SKIPPED = "policy_skipped"


class PipelineStage(StrEnum):
    DISCOVERED = "discovered"
    FETCHED = "fetched"
    NORMALIZED = "normalized"
    CLUSTERED = "clustered"
    EVIDENCED = "evidenced"
    SCORED = "scored"
    TERMINAL = "terminal"


@dataclass(slots=True)
class PipelineReceipt:
    item_key: str
    algorithm_version: str
    stage: PipelineStage = PipelineStage.DISCOVERED
    terminal_status: ItemTerminalStatus | None = None
    attempts: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    notes: list[str] = field(default_factory=list)

    @property
    def idempotency_key(self) -> str:
        return f"{self.item_key}:{self.algorithm_version}:{self.stage.value}"

    def advance(self, stage: PipelineStage, note: str = "") -> None:
        if self.terminal_status is not None:
            raise ValueError("terminal pipeline receipts cannot advance")
        order = list(PipelineStage)
        if order.index(stage) < order.index(self.stage):
            raise ValueError("pipeline stages cannot move backwards")
        self.stage = stage
        self.updated_at = datetime.now(UTC)
        if note:
            self.notes.append(note)

    def finish(self, status: ItemTerminalStatus, note: str = "") -> None:
        if self.terminal_status is not None and self.terminal_status != status:
            raise ValueError("a source item can have only one terminal status")
        self.stage = PipelineStage.TERMINAL
        self.terminal_status = status
        self.updated_at = datetime.now(UTC)
        if note:
            self.notes.append(note)
