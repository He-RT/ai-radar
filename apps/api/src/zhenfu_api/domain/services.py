from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from .models import ClaimImportance, Event, PublicationState, RiskLevel, SourceItem


class PublicationRejected(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def validate_publishable(event: Event) -> None:
    evidence_ids = {item.id for item in event.evidence}
    supporting_evidence_ids = {
        item.id for item in event.evidence if item.stance.value == "supports"
    }
    reasons: list[str] = []
    key_claims = [claim for claim in event.claims if claim.importance is ClaimImportance.KEY]
    if not key_claims:
        reasons.append("published events require at least one key claim")
    for claim in event.claims:
        missing = set(claim.evidence_ids) - evidence_ids
        if claim.importance is ClaimImportance.KEY and not claim.evidence_ids:
            reasons.append(f"key claim {claim.id} has no evidence")
        if claim.importance is ClaimImportance.KEY and not (
            set(claim.evidence_ids) & supporting_evidence_ids
        ):
            reasons.append(f"key claim {claim.id} has no supporting evidence")
        if missing:
            reasons.append(f"claim {claim.id} references missing evidence: {sorted(map(str, missing))}")
    if reasons:
        raise PublicationRejected(reasons)


@dataclass(frozen=True)
class ScoreInput:
    relevance: float
    evidence_quality: float
    source_independence: float
    recency: float
    actionability: float


SCORE_WEIGHTS = {
    "relevance": Decimal("0.30"),
    "evidence_quality": Decimal("0.25"),
    "source_independence": Decimal("0.20"),
    "recency": Decimal("0.15"),
    "actionability": Decimal("0.10"),
}


def deterministic_score(value: ScoreInput) -> tuple[float, dict[str, float]]:
    components: dict[str, float] = {}
    total = Decimal(0)
    for name, weight in SCORE_WEIGHTS.items():
        raw = Decimal(str(getattr(value, name)))
        if not Decimal(0) <= raw <= Decimal(1):
            raise ValueError(f"{name} must be between 0 and 1")
        contribution = (raw * weight * Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        components[name] = float(contribution)
        total += contribution
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)), components


@dataclass(frozen=True)
class AutoPublishDecision:
    allowed: bool
    reasons: tuple[str, ...]


def automatic_publish_gate(event: Event) -> AutoPublishDecision:
    reasons: list[str] = []
    try:
        validate_publishable(event)
    except PublicationRejected as exc:
        reasons.extend(exc.reasons)
    supporting_sources: set[UUID] = {
        ev.source_item_id for ev in event.evidence if ev.stance.value == "supports"
    }
    if len(supporting_sources) < 2:
        reasons.append("automatic publication requires two independent supporting source items")
    if len(set(event.source_ids)) < 2:
        reasons.append("automatic publication requires two independent publishers")
    if event.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        reasons.append(f"{event.risk.value}-risk events require human review")
    if any(claim.confidence < 0.72 for claim in event.claims if claim.importance is ClaimImportance.KEY):
        reasons.append("key claim confidence is below 0.72")
    if event.score is None or event.score.score < 65:
        reasons.append("event score is below automatic publication threshold 65")
    return AutoPublishDecision(not reasons, tuple(reasons))


TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
        )
    )
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, query, ""))


def normalized_content_hash(content: str) -> str:
    normalized = re.sub(r"[^\w]+", " ", content.casefold(), flags=re.UNICODE)
    normalized = " ".join(normalized.split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[\w-]+", value.casefold(), flags=re.UNICODE))


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 1.0


def cluster_similarity(left: SourceItem, right: SourceItem) -> float:
    if canonicalize_url(str(left.canonical_url)) == canonicalize_url(str(right.canonical_url)):
        return 1.0
    if left.content_hash == right.content_hash:
        return 1.0
    title = _jaccard(_tokens(left.title), _tokens(right.title))
    entities = _jaccard({x.casefold() for x in left.entities}, {x.casefold() for x in right.entities})
    time_delta = abs((left.published_at - right.published_at).total_seconds())
    temporal = math.exp(-time_delta / (36 * 3600))
    diversity = 1.0 if left.source_id != right.source_id else 0.0
    return round(0.50 * title + 0.25 * entities + 0.15 * temporal + 0.10 * diversity, 4)


def is_duplicate(left: SourceItem, right: SourceItem, threshold: float = 0.82) -> bool:
    return cluster_similarity(left, right) >= threshold


def publish(event: Event, automatic: bool = False) -> Event:
    validate_publishable(event)
    if automatic:
        decision = automatic_publish_gate(event)
        if not decision.allowed:
            raise PublicationRejected(list(decision.reasons))
    return event.model_copy(
        update={"state": PublicationState.PUBLISHED, "updated_at": datetime.now(UTC)}
    )
