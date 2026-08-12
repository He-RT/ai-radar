from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from zhenfu_api.catalog import (
    CatalogLoadError,
    SourceScheduleState,
    group_by_connector,
    load_catalog,
    next_due_at,
    select_due_sources,
    stable_source_uuid,
)

ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = ROOT / "config/sources/ai_radar_sources.json"


def _fixture(*, source_id: str = "source-a", url: str = "https://example.com/feed", priority: str = "P1") -> bytes:
    return json.dumps(
        {
            "catalog": "test catalog",
            "version": 7,
            "generated_from": "test fixture",
            "sources": [
                {
                    "id": source_id,
                    "name": "Test source",
                    "url": url,
                    "source_type": "html",
                    "language": "en",
                    "region": "us",
                    "priority": priority,
                    "poll_interval_minutes": 10 if priority == "P0" else 30,
                    "connector": "html",
                    "authority": "media",
                    "risk_level": "low",
                    "retention_policy": "90_days",
                    "retention_basis": "test fixture policy",
                    "enabled": True,
                    "notes": "fixture",
                }
            ],
        }
    ).encode()


def test_loads_real_full_catalog_with_version_and_hash() -> None:
    loaded = load_catalog(CATALOG_PATH, require_full_catalog=True)
    assert len(loaded.catalog.sources) == 500
    assert loaded.version == 3
    assert loaded.content_hash == hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
    assert loaded.sha256 == loaded.content_hash
    assert stable_source_uuid("gh-openai-openai-python-repository") == stable_source_uuid(
        "gh-openai-openai-python-repository"
    )


def test_bad_entries_fail_closed_and_name_their_path() -> None:
    duplicate = json.loads(_fixture())
    duplicate["sources"].append({**duplicate["sources"][0], "name": "duplicate"})
    with pytest.raises(CatalogLoadError, match=r"catalog validation failed.*<document>"):
        load_catalog(json.dumps(duplicate).encode())

    invalid_url = json.loads(_fixture())
    invalid_url["sources"][0]["url"] = "http://example.com/feed"
    with pytest.raises(CatalogLoadError, match=r"sources\.0\.url.*HTTPS"):
        load_catalog(json.dumps(invalid_url).encode())

    with pytest.raises(CatalogLoadError, match=r"expected exactly 500"):
        load_catalog(_fixture(), require_full_catalog=True)

    bad_interval = json.loads(_fixture())
    bad_interval["sources"][0]["poll_interval_minutes"] = 9
    with pytest.raises(CatalogLoadError, match=r"sources\.0\.poll_interval_minutes"):
        load_catalog(json.dumps(bad_interval).encode())


def test_manual_and_github_runtime_policy_fail_closed() -> None:
    manual = json.loads(_fixture())
    manual["sources"][0].update(
        connector="manual",
        enabled=False,
        manual_reason="policy_review",
    )
    assert load_catalog(json.dumps(manual).encode()).catalog.sources[0].enabled is False

    manual["sources"][0]["enabled"] = True
    with pytest.raises(CatalogLoadError, match="manual sources must be disabled"):
        load_catalog(json.dumps(manual).encode())

    github = json.loads(_fixture())
    github["sources"][0].update(
        url="https://github.com/openai/openai-python?tab=readme",
        source_type="github",
        connector="github",
    )
    with pytest.raises(CatalogLoadError, match="query, fragment, or escapes"):
        load_catalog(json.dumps(github).encode())


def test_due_selection_backoff_timezone_priority_and_determinism() -> None:
    p1 = load_catalog(_fixture(source_id="source-p1", priority="P1")).catalog.sources[0]
    p0 = load_catalog(_fixture(source_id="source-p0", priority="P0")).catalog.sources[0]
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)
    states: dict[str | UUID, SourceScheduleState] = {
        p1.id: SourceScheduleState(last_success_at=now - timedelta(minutes=61)),
        p0.id: SourceScheduleState(
            last_attempt_at=now - timedelta(minutes=19), consecutive_failures=3
        ),
    }
    assert next_due_at(p0, states[p0.id]) == now + timedelta(minutes=1)
    assert select_due_sources([p1, p0], states, now=now) == (p1,)
    states[p0.id] = SourceScheduleState(last_attempt_at=now - timedelta(minutes=20), consecutive_failures=3)
    assert select_due_sources([p1, p0], states, now=now) == (p0, p1)
    assert select_due_sources([p0, p1], states, now=now) == (p0, p1)
    assert next_due_at(
        p0,
        SourceScheduleState(last_attempt_at=now, consecutive_failures=20),
        failure_backoff_cap=timedelta(hours=1),
    ) == now + timedelta(hours=1)


def test_grouping_and_timezone_rules() -> None:
    loaded = load_catalog(CATALOG_PATH, require_full_catalog=True)
    batches = group_by_connector(loaded.catalog.sources)
    assert set(batches) == {"github", "html", "manual"}
    assert all(tuple(sorted(batch, key=lambda source: source.id)) == batch for batch in batches.values())
    source = loaded.catalog.sources[0]
    with pytest.raises(ValueError, match="timezone-aware"):
        select_due_sources([source], {}, now=datetime.fromisoformat("2026-08-12T12:00:00"))
