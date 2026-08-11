from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import AnyHttpUrl

from zhenfu_api.domain.models import (
    Claim,
    ClaimImportance,
    RiskLevel,
    SourceItem,
)
from zhenfu_api.domain.services import (
    PublicationRejected,
    ScoreInput,
    automatic_publish_gate,
    canonicalize_url,
    cluster_similarity,
    deterministic_score,
    normalized_content_hash,
    publish,
    validate_publishable,
)


def test_key_claim_without_evidence_is_rejected(repository):
    event = repository.events()[0].model_copy(
        update={
            "claims": [
                Claim(
                    text="An unsupported material claim",
                    importance=ClaimImportance.KEY,
                    confidence=0.99,
                )
            ],
            "evidence": [],
        }
    )

    with pytest.raises(PublicationRejected, match="has no evidence"):
        validate_publishable(event)
    with pytest.raises(PublicationRejected):
        publish(event)


def test_claim_cannot_reference_nonexistent_evidence(repository):
    event = repository.events()[0]
    bad_claim = event.claims[0].model_copy(update={"evidence_ids": [uuid4()]})
    with pytest.raises(PublicationRejected, match="references missing evidence"):
        validate_publishable(event.model_copy(update={"claims": [bad_claim]}))


def test_score_is_deterministic_and_component_sum_is_exact():
    value = ScoreInput(0.92, 0.88, 0.86, 0.95, 0.80)
    first = deterministic_score(value)
    second = deterministic_score(value)
    assert first == second
    score, components = first
    assert score == 89.05
    assert round(sum(components.values()), 2) == score


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_score_rejects_out_of_range_input(bad):
    with pytest.raises(ValueError, match="relevance"):
        deterministic_score(ScoreInput(bad, 0.5, 0.5, 0.5, 0.5))


def test_automatic_gate_blocks_high_risk_even_with_good_evidence(repository):
    event = repository.events()[0].model_copy(update={"risk": RiskLevel.HIGH})
    decision = automatic_publish_gate(event)
    assert not decision.allowed
    assert "high-risk events require human review" in decision.reasons


def test_automatic_gate_requires_independent_publishers(repository):
    event = repository.events()[0]
    event = event.model_copy(update={"source_ids": [event.source_ids[0], event.source_ids[0]]})
    decision = automatic_publish_gate(event)
    assert not decision.allowed
    assert "automatic publication requires two independent publishers" in decision.reasons


def test_demo_events_clear_automatic_gate(repository):
    assert all(automatic_publish_gate(event).allowed for event in repository.events())


def test_url_and_content_deduplication_normalize_noise():
    assert canonicalize_url("HTTPS://Example.COM/a//b/?utm_source=x&b=2&a=1#part") == (
        "https://example.com/a/b?a=1&b=2"
    )
    assert normalized_content_hash("Hello,   WORLD!") == normalized_content_hash("hello world")


def test_cluster_similarity_combines_title_entities_time_and_source():
    now = datetime.now(UTC)
    first = SourceItem(
        source_id=uuid4(),
        canonical_url=AnyHttpUrl("https://one.example/story"),
        title="Atlas model cuts inference cost",
        content_hash="a" * 64,
        published_at=now,
        entities={"Atlas", "Inference"},
    )
    second = SourceItem(
        source_id=uuid4(),
        canonical_url=AnyHttpUrl("https://two.example/report"),
        title="Atlas model cuts inference cost substantially",
        content_hash="b" * 64,
        published_at=now + timedelta(hours=2),
        entities={"Atlas", "Inference"},
    )
    unrelated = second.model_copy(
        update={
            "title": "New governance rules published",
            "entities": {"Policy"},
            "published_at": now + timedelta(days=10),
        }
    )
    assert cluster_similarity(first, second) > 0.82
    assert cluster_similarity(first, unrelated) < 0.3
