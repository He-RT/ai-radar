from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Never

import pytest

from zhenfu_api.catalog import LoadedCatalog, SourceDefinition, load_catalog
from zhenfu_api.ingest.dispatcher import (
    DispatchStatus,
    IngestionDispatcher,
    RuntimeDisposition,
    RuntimeOperation,
    UnsupportedSourceError,
    catalog_runtime_coverage,
    runtime_plan,
)
from zhenfu_api.ingest.security import RawArtifact
from zhenfu_api.workers.ingest import CatalogIngestionWorker, MemoryReceiptStore

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
FIXTURES = Path(__file__).with_name("fixtures")
CATALOG = Path(__file__).resolve().parents[3] / "config/sources/ai_radar_sources.json"


def _source(
    *,
    source_id: str,
    url: str,
    connector: str,
    source_type: str,
) -> SourceDefinition:
    return SourceDefinition.model_validate(
        {
            "id": source_id,
            "name": "Dispatcher fixture",
            "url": url,
            "source_type": source_type,
            "language": "en",
            "region": "us",
            "priority": "P1",
            "poll_interval_minutes": 30,
            "connector": connector,
            "authority": "media",
            "risk_level": "low",
            "retention_policy": "90_days",
            "retention_basis": "test fixture policy",
            "enabled": connector != "manual",
            "manual_reason": "not_automatable" if connector == "manual" else None,
            "notes": "offline dispatcher fixture",
        },
        strict=True,
    )


def _artifact(
    body: bytes,
    *,
    content_type: str,
    final_url: str,
    status_code: int = 200,
) -> RawArtifact:
    return RawArtifact(
        requested_url=final_url,
        final_url=final_url,
        status_code=status_code,
        content_type=content_type,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
    )


def _catalog(*sources: SourceDefinition) -> LoadedCatalog:
    return load_catalog(
        json.dumps(
            {
                "catalog": "dispatcher test catalog",
                "version": 1,
                "generated_from": "offline fixture",
                "sources": [source.model_dump(mode="json") for source in sources],
            }
        ).encode()
    )


class FixtureFetcher:
    def __init__(self, artifact: RawArtifact) -> None:
        self.artifact = artifact
        self.urls: list[str] = []

    async def fetch(self, url: str) -> RawArtifact:
        self.urls.append(url)
        return self.artifact


class NeverFetch:
    async def fetch(self, url: str) -> Never:
        raise AssertionError(f"unexpected network fetch: {url}")


def _dispatcher(fetcher: FixtureFetcher | NeverFetch) -> IngestionDispatcher:
    return IngestionDispatcher(fetcher=fetcher, clock=lambda: NOW)


def test_runtime_plan_and_catalog_coverage_classify_each_source_without_network() -> None:
    html = _source(
        source_id="html-source",
        url="https://example.com/news/model-release",
        connector="html",
        source_type="html",
    )
    github_repository = _source(
        source_id="github-repository",
        url="https://github.com/openai/openai-python",
        connector="github",
        source_type="github",
    )
    github_releases = _source(
        source_id="github-releases",
        url="https://github.com/openai/openai-python/releases",
        connector="github",
        source_type="github",
    )
    manual = _source(
        source_id="manual-source",
        url="https://example.com/manual-submissions",
        connector="manual",
        source_type="manual",
    )
    unsupported = _source(
        source_id="api-source",
        url="https://api.example.com/releases",
        connector="api",
        source_type="api",
    )

    html_plan = runtime_plan(html)
    repository_plan = runtime_plan(github_repository)
    releases_plan = runtime_plan(github_releases)
    manual_plan = runtime_plan(manual)
    coverage = catalog_runtime_coverage(
        [manual, unsupported, github_repository, github_releases, html]
    )

    assert (html_plan.disposition, html_plan.operation, html_plan.fetch_url) == (
        RuntimeDisposition.SUPPORTED,
        RuntimeOperation.HTML_PAGE,
        "https://example.com/news/model-release",
    )
    assert (repository_plan.operation, repository_plan.fetch_url) == (
        RuntimeOperation.GITHUB_REPOSITORY,
        "https://api.github.com/repos/openai/openai-python",
    )
    assert (releases_plan.operation, releases_plan.fetch_url) == (
        RuntimeOperation.GITHUB_RELEASES,
        "https://api.github.com/repos/openai/openai-python/releases?per_page=100",
    )
    assert repository_plan.operation is not releases_plan.operation
    assert repository_plan.fetch_url != releases_plan.fetch_url
    assert (manual_plan.disposition, manual_plan.operation, manual_plan.fetch_url) == (
        RuntimeDisposition.POLICY_SKIP,
        RuntimeOperation.POLICY_SKIP,
        None,
    )
    assert (coverage.total, coverage.supported, coverage.policy_skip) == (5, 3, 1)
    assert coverage.unsupported_source_ids == ("api-source",)


def test_every_real_catalog_entry_has_an_executable_or_policy_skip_disposition() -> None:
    loaded = load_catalog(CATALOG, require_full_catalog=True)
    coverage = catalog_runtime_coverage(loaded.catalog.sources)
    operations = Counter(runtime_plan(source).operation for source in loaded.catalog.sources)

    assert coverage.total == 500
    assert coverage.supported + coverage.policy_skip == coverage.total
    assert coverage.unsupported == 0
    assert coverage.unsupported_source_ids == ()
    assert operations == {
        RuntimeOperation.GITHUB_REPOSITORY: 193,
        RuntimeOperation.GITHUB_RELEASES: 49,
        RuntimeOperation.HTML_PAGE: 205,
        RuntimeOperation.POLICY_SKIP: 53,
    }


def test_html_dispatch_returns_clean_inert_candidate() -> None:
    source = _source(
        source_id="html-source",
        url="https://example.com/news/model-release",
        connector="html",
        source_type="html",
    )
    body = b"""<!doctype html><html><head>
      <title>Model release | Example</title>
      <meta name="description" content="A safe model update.">
    </head><body><script>window.pwned = true</script>
      <h1>Model release</h1><p>Clean visible announcement text.</p>
    </body></html>"""
    artifact = _artifact(body, content_type="text/html", final_url=str(source.url))
    fetcher = FixtureFetcher(artifact)

    receipt = asyncio.run(_dispatcher(fetcher).dispatch(source))

    assert receipt.status is DispatchStatus.SUCCEEDED
    assert receipt.operation is RuntimeOperation.HTML_PAGE
    assert receipt.artifact_sha256 == artifact.sha256
    assert fetcher.urls == [str(source.url)]
    assert receipt.candidate_count == 1
    candidate = receipt.candidates[0]
    assert candidate.title == "Model release | Example"
    assert candidate.summary == "A safe model update."
    assert (
        candidate.content_text
        == "Model release | Example Model release Clean visible announcement text."
    )
    assert "pwned" not in candidate.content_text
    assert receipt.started_at == receipt.finished_at == NOW


def test_github_repository_dispatch_normalizes_single_api_payload() -> None:
    source = _source(
        source_id="github-source",
        url="https://github.com/openai/openai-python",
        connector="github",
        source_type="github",
    )
    body = json.dumps(
        {
            "node_id": " R_kgDOGithubRepo ",
            "id": 17,
            "full_name": " openai/openai-python\n",
            "name": "ignored-fallback-name",
            "html_url": " https://github.com/openai/openai-python ",
            "pushed_at": "2026-08-12T00:15:00Z",
            "updated_at": "2026-08-11T00:15:00Z",
            "description": " Official Python client\u0000  for the OpenAI API. " + "x" * 2_100,
        }
    ).encode()
    artifact = _artifact(
        body,
        content_type="application/json",
        final_url="https://api.github.com/repos/openai/openai-python",
    )
    fetcher = FixtureFetcher(artifact)

    receipt = asyncio.run(_dispatcher(fetcher).dispatch(source))

    assert receipt.status is DispatchStatus.SUCCEEDED
    assert receipt.operation is RuntimeOperation.GITHUB_REPOSITORY
    assert fetcher.urls == ["https://api.github.com/repos/openai/openai-python"]
    assert receipt.candidate_count == 1
    candidate = receipt.candidates[0]
    assert candidate.source_id == source.stable_uuid
    assert candidate.external_id == "R_kgDOGithubRepo"
    assert candidate.title == "openai/openai-python"
    assert candidate.url == "https://github.com/openai/openai-python"
    assert candidate.published_at == datetime(2026, 8, 12, 0, 15, tzinfo=UTC)
    assert candidate.summary.startswith("Official Python client for the OpenAI API.")
    assert "\x00" not in candidate.summary
    assert len(candidate.summary) == 2_000


def test_github_release_dispatch_normalizes_api_payload_and_uses_api_endpoint() -> None:
    source = _source(
        source_id="github-releases",
        url="https://github.com/openai/openai-python/releases",
        connector="github",
        source_type="github",
    )
    body = json.dumps(
        [
            {
                "id": 17,
                "name": "v2.0.0",
                "html_url": "https://github.com/openai/openai-python/releases/tag/v2.0.0",
                "published_at": "2026-08-12T00:15:00Z",
                "body": "Release notes\n\nwith details",
            }
        ]
    ).encode()
    endpoint = "https://api.github.com/repos/openai/openai-python/releases?per_page=100"
    fetcher = FixtureFetcher(
        _artifact(body, content_type="application/json", final_url=endpoint)
    )

    receipt = asyncio.run(_dispatcher(fetcher).dispatch(source))

    assert receipt.status is DispatchStatus.SUCCEEDED
    assert receipt.operation is RuntimeOperation.GITHUB_RELEASES
    assert fetcher.urls == [endpoint]
    assert receipt.candidate_count == 1
    candidate = receipt.candidates[0]
    assert candidate.source_id == source.stable_uuid
    assert candidate.external_id == "17"
    assert candidate.title == "v2.0.0"
    assert candidate.summary == "Release notes with details"
    assert candidate.url == "https://github.com/openai/openai-python/releases/tag/v2.0.0"


def test_github_security_page_dispatches_repository_advisory_fixture() -> None:
    source = _source(
        source_id="github-advisories",
        url="https://github.com/example/project/security",
        connector="github",
        source_type="github",
    )
    endpoint = "https://api.github.com/repos/example/project/security-advisories?per_page=100"
    body = (FIXTURES / "github_advisories.json").read_bytes()
    fetcher = FixtureFetcher(_artifact(body, content_type="application/json", final_url=endpoint))

    receipt = asyncio.run(_dispatcher(fetcher).dispatch(source))

    assert receipt.status is DispatchStatus.SUCCEEDED
    assert receipt.operation is RuntimeOperation.GITHUB_ADVISORIES
    assert fetcher.urls == [endpoint]
    assert receipt.candidate_count == 1
    candidate = receipt.candidates[0]
    assert candidate.external_id == "GHSA-abcd-1234-wxyz"
    assert candidate.title == "Unsafe deserialization in optional loader"
    assert candidate.summary.startswith("Upgrade to the fixed release")


def test_manual_source_is_a_terminal_policy_skip_without_fetching() -> None:
    source = _source(
        source_id="manual-source",
        url="https://example.com/manual-submissions",
        connector="manual",
        source_type="manual",
    )

    receipt = asyncio.run(_dispatcher(NeverFetch()).dispatch(source))

    assert receipt.terminal
    assert receipt.status is DispatchStatus.POLICY_SKIPPED
    assert receipt.disposition is RuntimeDisposition.POLICY_SKIP
    assert receipt.operation is RuntimeOperation.POLICY_SKIP
    assert receipt.fetch_url is None
    assert receipt.artifact_sha256 is None
    assert receipt.candidates == ()
    assert "human submission" in receipt.reason


@pytest.mark.parametrize("path", ["issues", "pulls", "issues/17", "pull/42"])
def test_github_issue_and_pull_pages_are_policy_skipped_without_fetching(path: str) -> None:
    source = _source(
        source_id="github-non-independent",
        url=f"https://github.com/example/project/{path}",
        connector="github",
        source_type="github",
    )

    receipt = asyncio.run(_dispatcher(NeverFetch()).dispatch(source))

    assert receipt.status is DispatchStatus.POLICY_SKIPPED
    assert receipt.disposition is RuntimeDisposition.POLICY_SKIP
    assert "not independent" in receipt.reason


def test_unsupported_connector_fails_closed_before_attempting_a_fetch() -> None:
    source = _source(
        source_id="api-source",
        url="https://api.example.com/releases",
        connector="api",
        source_type="api",
    )

    with pytest.raises(UnsupportedSourceError, match=r"api-source: connector 'api'"):
        asyncio.run(_dispatcher(NeverFetch()).dispatch(source))


def test_worker_run_one_due_records_one_terminal_receipt_and_never_refetches_same_slot() -> None:
    source = _source(
        source_id="html-source",
        url="https://example.com/news/model-release",
        connector="html",
        source_type="html",
    )
    body = b"<html><title>One item</title><p>Announcement</p></html>"
    fetcher = FixtureFetcher(_artifact(body, content_type="text/html", final_url=str(source.url)))
    worker = CatalogIngestionWorker(
        _catalog(source),
        _dispatcher(fetcher),
        receipt_store=MemoryReceiptStore(),
    )

    first = asyncio.run(worker.run_one_due(now=NOW))
    duplicate_slot = asyncio.run(worker.run_one_due(now=NOW))
    same_terminal_receipt = asyncio.run(worker.run_source(source.id, now=NOW))

    assert first is not None and first.terminal
    assert first.status is DispatchStatus.SUCCEEDED
    assert duplicate_slot is None
    assert same_terminal_receipt is first
    assert len(fetcher.urls) == 1
    assert len(worker.receipt_store.receipts) == 1
    assert worker.receipt_store.latest(source.id) is first
