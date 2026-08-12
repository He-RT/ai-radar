from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from uuid import uuid4
from xml.etree import ElementTree

from zhenfu_api.config import Settings


def test_public_markdown_is_utf8_cacheable_and_conditional(client, repository) -> None:
    response = client.get("/api/v1/briefings/2026-08-12.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown; charset=utf-8")
    assert response.headers["etag"] == f'"{sha256(response.content).hexdigest()}"'
    assert response.headers["cache-control"] == "public, max-age=300, must-revalidate"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == 'attachment; filename="briefing-2026-08-12.md"'
    assert response.text == response.content.decode("utf-8")
    assert repository.events()[0].title in response.text

    not_modified = client.get(
        "/api/v1/briefings/2026-08-12.md", headers={"If-None-Match": response.headers["etag"]}
    )
    assert not_modified.status_code == 304
    assert not not_modified.content
    assert not_modified.headers["etag"] == response.headers["etag"]


def test_daily_rss_and_markdown_share_the_exact_public_snapshot(repository) -> None:
    from fastapi.testclient import TestClient

    from zhenfu_api.api import create_app
    from zhenfu_api.auth import IdentityStore

    settings = Settings(
        environment="test",
        public_base_url="https://radar.example.test/news",
        synthetic_repository=True,
    )
    with TestClient(
        create_app(
            settings=settings,
            repository=repository,
            identity_store=IdentityStore(ttl_seconds=3600),
        )
    ) as client:
        response = client.get("/api/v1/feeds/daily.xml")
        markdown = client.get("/api/v1/briefings/2026-08-12.md")

    assert response.status_code == 200
    assert markdown.status_code == 200
    assert response.headers["content-type"].startswith("application/rss+xml; charset=utf-8")
    root = ElementTree.fromstring(response.content)
    assert root.findtext("./channel/link") == "https://radar.example.test/news"
    guids = [item.findtext("guid") for item in root.findall("./channel/item")]
    briefing = repository.briefings()[0]
    assert guids == [
        f"{snapshot.event_id}:{snapshot.public_version}"
        for snapshot in briefing.event_snapshots
    ]
    assert markdown.text.count("### ") == len(briefing.event_ids)
    for event_id, snapshot in zip(
        briefing.event_ids, briefing.event_snapshots, strict=True
    ):
        assert event_id == snapshot.event_id
        assert snapshot.event.title in markdown.text


def test_public_feed_routes_return_404_for_missing_or_invalid_snapshots(client, repository) -> None:
    assert client.get("/api/v1/briefings/1999-01-01.md").status_code == 404

    briefing = repository._briefings[0]
    repository._briefings[0] = briefing.model_copy(
        update={"event_ids": [*briefing.event_ids, uuid4()]}
    )
    assert client.get("/api/v1/briefings/2026-08-12.md").status_code == 404
    assert client.get("/api/v1/feeds/daily.xml").status_code == 404


def test_public_feed_routes_remain_identical_after_live_event_updates(client, repository) -> None:
    briefing = repository._briefings[0]
    before_markdown = client.get("/api/v1/briefings/2026-08-12.md")
    before_rss = client.get("/api/v1/feeds/daily.xml")
    before_json = client.get("/api/v1/briefings/2026-08-12")

    event = repository._events[0]
    repository._events[0] = event.model_copy(
        update={
            "title": "A later corrected title that is not part of the briefing",
            "updated_at": briefing.cutoff_at + timedelta(seconds=1),
        }
    )

    markdown = client.get("/api/v1/briefings/2026-08-12.md")
    rss = client.get("/api/v1/feeds/daily.xml")
    briefing_json = client.get("/api/v1/briefings/2026-08-12")
    assert markdown.status_code == rss.status_code == briefing_json.status_code == 200
    assert markdown.content == before_markdown.content
    assert markdown.headers["etag"] == before_markdown.headers["etag"]
    assert rss.content == before_rss.content
    assert rss.headers["etag"] == before_rss.headers["etag"]
    assert briefing_json.json() == before_json.json()
    assert event.title in markdown.text
    assert "A later corrected title" not in markdown.text


def test_public_routes_fail_closed_on_mismatched_embedded_snapshot(client, repository) -> None:
    briefing = repository._briefings[0]
    pinned = briefing.event_snapshots[0]
    mismatched = pinned.model_copy(update={"public_version": pinned.public_version + 1})
    repository._briefings[0] = briefing.model_copy(
        update={"event_snapshots": [mismatched, *briefing.event_snapshots[1:]]}
    )

    assert client.get("/api/v1/briefings/2026-08-12.md").status_code == 404
    assert client.get("/api/v1/feeds/daily.xml").status_code == 404
    assert client.get("/api/v1/briefings/2026-08-12").status_code == 404
