from __future__ import annotations

from xml.etree import ElementTree

from pydantic import ValidationError

from zhenfu_api.domain.models import BriefingSnapshot, Event, PublicationState
from zhenfu_api.domain.services import PublicationRejected, validate_publishable

PUBLIC_STATES = {PublicationState.PUBLISHED, PublicationState.CORRECTED}


def resolve_public_snapshot(briefing: BriefingSnapshot) -> list[Event]:
    """Validate and return only the events embedded at publication time."""

    reasons: list[str] = []
    if briefing.state not in PUBLIC_STATES:
        reasons.append(f"briefing {briefing.id} is not public")
    try:
        # model_copy(update=...) and mutable nested lists do not re-run Pydantic
        # validators. Re-parse plain data at every public boundary so corrupted
        # in-memory snapshots fail closed too.
        validated = BriefingSnapshot.model_validate(briefing.model_dump(mode="python"))
    except (TypeError, ValidationError, ValueError) as exc:
        reasons.append(f"briefing {briefing.id} has invalid immutable event snapshots: {exc}")
        validated = None

    included = (
        [snapshot.event for snapshot in validated.event_snapshots]
        if validated is not None
        else []
    )
    for event in included:
        try:
            validate_publishable(event)
        except PublicationRejected as exc:
            reasons.extend(exc.reasons)
    if reasons:
        raise PublicationRejected(list(dict.fromkeys(reasons)))
    return included


def render_briefing_markdown(briefing: BriefingSnapshot) -> str:
    """Render only the public events captured by the immutable snapshot."""

    included = resolve_public_snapshot(briefing)
    lines = [
        f"# AI 雷达快照｜{briefing.briefing_date.isoformat()}",
        "",
        f"> 知识截止：{briefing.cutoff_at.isoformat()} · 快照 ID：{briefing.id}",
        "",
        "## 今日判断",
        "",
        briefing.executive_summary,
        "",
        "## 事件",
        "",
    ]
    for index, event in enumerate(included, 1):
        lines.extend(
            [
                f"### {index}. {event.title}｜{event.score.score if event.score else 0:.0f}｜{event.confidence_grade.value}",
                "",
                event.summary,
                "",
                f"- 状态：{event.evidence_status.value}",
                f"- 事件版本：{event.public_version}",
                "- 证据："
                + "、".join(f"[{item.locator}]({item.url})" for item in event.evidence),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_daily_rss(briefing: BriefingSnapshot, base_url: str) -> str:
    """Render only the public events captured by the immutable snapshot."""

    included = resolve_public_snapshot(briefing)
    base_url = base_url.rstrip("/")
    root = ElementTree.Element("rss", {"version": "2.0"})
    channel = ElementTree.SubElement(root, "channel")
    ElementTree.SubElement(channel, "title").text = _xml_text(briefing.title)
    ElementTree.SubElement(channel, "link").text = _xml_text(base_url)
    ElementTree.SubElement(channel, "description").text = _xml_text(briefing.executive_summary)
    for event in included:
        link = f"{base_url.rstrip('/')}/event/{event.slug}"
        item = ElementTree.SubElement(channel, "item")
        ElementTree.SubElement(item, "title").text = _xml_text(event.title)
        ElementTree.SubElement(item, "link").text = _xml_text(link)
        guid = ElementTree.SubElement(item, "guid", {"isPermaLink": "false"})
        guid.text = _xml_text(f"{event.id}:{event.public_version}")
        ElementTree.SubElement(item, "description").text = _xml_text(event.summary)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _xml_text(value: str) -> str:
    """Keep untrusted editorial text valid under XML 1.0."""
    return "".join(
        character
        for character in value
        if character in {"\t", "\n", "\r"}
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
    )
