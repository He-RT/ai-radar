from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from zhenfu_api.catalog import (
    LoadedCatalog,
    SourceDefinition,
    SourceScheduleState,
    load_catalog,
    next_due_at,
    select_due_sources,
)
from zhenfu_api.ingest.dispatcher import (
    DispatchReceipt,
    DispatchStatus,
    IngestionDispatcher,
    RuntimeDisposition,
    UnsupportedSourceError,
    catalog_runtime_coverage,
    runtime_plan,
)
from zhenfu_api.jobs import celery_app


class SourceNotDueError(ValueError):
    pass


@dataclass(slots=True)
class MemoryReceiptStore:
    """Process-local idempotency store used by the single-concurrency ingest worker."""

    receipts: dict[str, DispatchReceipt] = field(default_factory=dict)
    latest_by_source: dict[str, DispatchReceipt] = field(default_factory=dict)
    states: dict[str | UUID, SourceScheduleState] = field(default_factory=dict)

    def get(self, run_key: str) -> DispatchReceipt | None:
        return self.receipts.get(run_key)

    def latest(self, source_id: str) -> DispatchReceipt | None:
        return self.latest_by_source.get(source_id)

    def state(self, source_id: str) -> SourceScheduleState | None:
        return self.states.get(source_id)

    def save(
        self,
        run_key: str,
        receipt: DispatchReceipt,
        state: SourceScheduleState | None,
    ) -> DispatchReceipt:
        existing = self.receipts.get(run_key)
        if existing is not None:
            return existing
        self.receipts[run_key] = receipt
        self.latest_by_source[receipt.source_id] = receipt
        if state is not None:
            self.states[receipt.source_id] = state
        return receipt


class CatalogIngestionWorker:
    """Select and terminally dispatch at most one due, supported catalog source."""

    def __init__(
        self,
        catalog: LoadedCatalog,
        dispatcher: IngestionDispatcher,
        *,
        receipt_store: MemoryReceiptStore | None = None,
    ) -> None:
        coverage = catalog_runtime_coverage(catalog.catalog.sources)
        if coverage.unsupported_source_ids:
            raise UnsupportedSourceError(
                "catalog contains unsupported sources: "
                + ", ".join(coverage.unsupported_source_ids)
            )
        self.catalog = catalog
        self.dispatcher = dispatcher
        self.receipt_store = receipt_store or MemoryReceiptStore()
        self._sources = {source.id: source for source in catalog.catalog.sources}
        self._lock = asyncio.Lock()

    @staticmethod
    def _current(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("worker now must be timezone-aware")
        return value.astimezone(UTC)

    def _run_key(self, source: SourceDefinition, due_at: datetime | None) -> str:
        slot = due_at.isoformat() if due_at is not None else "initial"
        material = f"{self.catalog.content_hash}\x00{source.id}\x00{slot}"
        return hashlib.sha256(material.encode()).hexdigest()

    async def run_source(self, source_id: str, *, now: datetime) -> DispatchReceipt:
        async with self._lock:
            return await self._run_source(source_id, now=self._current(now))

    async def _run_source(self, source_id: str, *, now: datetime) -> DispatchReceipt:
        try:
            source = self._sources[source_id]
        except KeyError as exc:
            raise KeyError(f"unknown catalog source: {source_id}") from exc
        if not source.enabled:
            raise SourceNotDueError(f"catalog source is disabled: {source_id}")

        plan = runtime_plan(source)
        if plan.disposition is RuntimeDisposition.POLICY_SKIP:
            run_key = hashlib.sha256(
                f"{self.catalog.content_hash}\x00{source.id}\x00policy-skip".encode()
            ).hexdigest()
            if existing := self.receipt_store.get(run_key):
                return existing
            receipt = await self.dispatcher.dispatch(source)
            return self.receipt_store.save(run_key, receipt, None)

        state = self.receipt_store.state(source.id)
        due_at = next_due_at(source, state)
        if due_at is not None and due_at > now:
            latest = self.receipt_store.latest(source.id)
            if latest is None:
                raise SourceNotDueError(f"catalog source is not due: {source_id}")
            return latest

        run_key = self._run_key(source, due_at)
        if existing := self.receipt_store.get(run_key):
            return existing
        receipt = await self.dispatcher.dispatch(source)
        previous_failures = state.consecutive_failures if state else 0
        if receipt.status is DispatchStatus.SUCCEEDED:
            next_state = SourceScheduleState(
                last_attempt_at=receipt.finished_at,
                last_success_at=receipt.finished_at,
                consecutive_failures=0,
            )
        else:
            next_state = SourceScheduleState(
                last_attempt_at=receipt.finished_at,
                last_success_at=state.last_success_at if state else None,
                consecutive_failures=previous_failures + 1,
            )
        return self.receipt_store.save(run_key, receipt, next_state)

    async def run_one_due(self, *, now: datetime) -> DispatchReceipt | None:
        current = self._current(now)
        async with self._lock:
            scheduled = [
                source
                for source in self.catalog.catalog.sources
                if runtime_plan(source).disposition is RuntimeDisposition.SUPPORTED
            ]
            due = select_due_sources(
                scheduled,
                self.receipt_store.states,
                now=current,
            )
            if not due:
                return None
            return await self._run_source(due[0].id, now=current)


def _default_catalog_path() -> Path:
    configured = os.environ.get("RADAR_SOURCE_CATALOG_PATH")
    if configured:
        return Path(configured)
    relative = Path("config/sources/ai_radar_sources.json")
    search_roots = (Path.cwd(), *Path(__file__).resolve().parents)
    for root in search_roots:
        candidate = root / relative
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "source catalog not found; set RADAR_SOURCE_CATALOG_PATH or mount config/sources"
    )


@lru_cache
def _default_worker() -> CatalogIngestionWorker:
    catalog = load_catalog(_default_catalog_path(), require_full_catalog=True)
    return CatalogIngestionWorker(catalog, IngestionDispatcher())


def _receipt_payload(receipt: DispatchReceipt | None) -> dict[str, object]:
    if receipt is None:
        return {"status": "no_due_source"}
    return {
        "source_id": receipt.source_id,
        "status": receipt.status.value,
        "operation": receipt.operation.value,
        "terminal": receipt.terminal,
        "candidate_count": receipt.candidate_count,
        "artifact_sha256": receipt.artifact_sha256,
        "idempotency_key": receipt.idempotency_key,
        "finished_at": receipt.finished_at.isoformat(),
        "reason": receipt.reason,
    }


@celery_app.task(name="radar.ingest.run_one_due")
def run_one_due_task(now: str | None = None) -> dict[str, object]:
    """Celery boundary: select, dispatch, and terminally receipt one due source."""
    current = datetime.fromisoformat(now) if now else datetime.now(UTC)
    receipt = asyncio.run(_default_worker().run_one_due(now=current))
    return _receipt_payload(receipt)


def main() -> None:
    """Run the constrained real-time discovery and ingestion queue."""
    celery_app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            "--queues=radar-ingest",
            "--concurrency=1",
            "--hostname=ingest@%h",
        ]
    )


if __name__ == "__main__":
    main()
