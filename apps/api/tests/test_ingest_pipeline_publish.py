from __future__ import annotations

import socket
from uuid import uuid4

import pytest

from zhenfu_api.domain.models import PublicationState
from zhenfu_api.domain.services import PublicationRejected
from zhenfu_api.ingest.connectors import RSSConnector
from zhenfu_api.ingest.security import UnsafeTargetError, validate_public_url
from zhenfu_api.pipeline import ItemTerminalStatus, PipelineReceipt, PipelineStage
from zhenfu_api.publishing import render_briefing_markdown, render_daily_rss
from zhenfu_api.repository import SyntheticRadarRepository


def _resolver(address: str):
    def resolve(_host: str, port: int):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    return resolve


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_private_fetch_targets_are_rejected(address: str) -> None:
    with pytest.raises(UnsafeTargetError):
        validate_public_url("https://source.example/feed", resolver=_resolver(address))


def test_public_fetch_target_is_accepted() -> None:
    assert validate_public_url(
        "https://source.example/feed", resolver=_resolver("93.184.216.34")
    ) == "https://source.example/feed"


def test_rss_connector_discovers_normalized_candidates() -> None:
    payload = b"""<?xml version='1.0'?><rss version='2.0'><channel><item>
      <title>Model release</title><link>https://example.com/release?utm_source=test</link>
      <guid>release-1</guid><pubDate>Wed, 12 Aug 2026 00:15:00 GMT</pubDate>
    </item></channel></rss>"""
    candidates = RSSConnector().discover(payload, source_id=uuid4(), base_url="https://example.com")
    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/release"
    assert candidates[0].external_id == "release-1"


def test_pipeline_receipt_has_exactly_one_terminal_state() -> None:
    receipt = PipelineReceipt("item-1", "pipeline-v1")
    receipt.advance(PipelineStage.FETCHED)
    receipt.finish(ItemTerminalStatus.LOW_SCORE, "retained in the complete ledger")
    assert receipt.terminal_status is ItemTerminalStatus.LOW_SCORE
    with pytest.raises(ValueError):
        receipt.finish(ItemTerminalStatus.PUBLISHED)


def test_markdown_and_rss_share_the_same_immutable_snapshot() -> None:
    repository = SyntheticRadarRepository()
    briefing = repository.briefings()[0]
    markdown = render_briefing_markdown(briefing)
    rss = render_daily_rss(briefing, "https://radar.example.com")
    assert str(briefing.id) in markdown
    assert repository.events()[0].title in markdown
    assert str(repository.events()[0].id) in rss
    assert "utm_source" not in rss


def test_renderers_reject_non_public_or_incomplete_snapshots() -> None:
    repository = SyntheticRadarRepository()
    briefing = repository.briefings()[0]
    pinned = briefing.event_snapshots[0]
    draft_event = pinned.event.model_copy(update={"state": PublicationState.DRAFT})
    draft_snapshot = pinned.model_copy(update={"event": draft_event})
    invalid = briefing.model_copy(
        update={"event_snapshots": [draft_snapshot, *briefing.event_snapshots[1:]]}
    )
    with pytest.raises(PublicationRejected, match="invalid immutable event snapshots"):
        render_briefing_markdown(invalid)

    missing = briefing.model_copy(update={"event_ids": [*briefing.event_ids, uuid4()]})
    with pytest.raises(PublicationRejected, match="invalid immutable event snapshots"):
        render_daily_rss(missing, "https://radar.example.com")
