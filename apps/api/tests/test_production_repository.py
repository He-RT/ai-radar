from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from zhenfu_api.api import create_app
from zhenfu_api.config import Settings
from zhenfu_api.main import create_application
from zhenfu_api.persistence import Base, SqlRadarRepository, build_engine, session_factory
from zhenfu_api.persistence.tables import (
    BriefingSnapshotRecord,
    ClaimRecord,
    EventRecord,
    EventVersionRecord,
)
from zhenfu_api.repository import SyntheticRadarRepository


@pytest.fixture
def persistent_client():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = SqlRadarRepository(session_factory(engine))
    app = create_app(
        settings=Settings(environment="test", database_url="sqlite+pysqlite:///:memory:", synthetic_repository=False),
        repository=repository,
    )
    with TestClient(app) as client:
        yield client, repository, session_factory(engine)
    engine.dispose()


def test_main_uses_sql_repository_when_production_disables_synthetic_data():
    settings = Settings(
        environment="production",
        app_secret_key="production-app-secret-with-32-characters",
        database_url="postgresql+psycopg://postgres:postgres@127.0.0.1:1/radar",
        valkey_url="redis://:production-secret@127.0.0.1:6379/0",
        s3_endpoint="https://objects.example",
        s3_access_key="production-access-key",
        s3_secret_key="production-s3-secret-with-24-characters",
        s3_bucket="radar-production",
        smtp_url="smtps://mail.example:465",
        llm_api_key="production-model-key",
        llm_base_url="https://api.openai.com/v1",
        llm_model="approved-production-model",
        public_base_url="https://radar.example",
        synthetic_repository=False,
    )

    app = create_application(settings=settings)

    assert isinstance(app.state.repository, SqlRadarRepository)
    assert app.state.settings.synthetic_repository is False
    app.state.database_engine.dispose()


def test_empty_persistent_database_starts_and_is_ready(persistent_client):
    client, repository, _sessions = persistent_client

    assert repository.events() == []
    assert client.get("/api/v1/events").json()["total"] == 0
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").json() == {"status": "ready"}
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert b"# HELP" in metrics.content


def test_sql_repository_uses_only_complete_embedded_briefing_events(persistent_client):
    _client, repository, sessions = persistent_client
    source = SyntheticRadarRepository().briefings()[0]
    with sessions() as session:
        session.add(
            BriefingSnapshotRecord(
                id=source.id,
                briefing_date=source.briefing_date,
                title=source.title,
                executive_summary=source.executive_summary,
                event_ids=[str(event_id) for event_id in source.event_ids],
                event_snapshots=[
                    snapshot.model_dump(mode="json") for snapshot in source.event_snapshots
                ],
                cutoff_at=source.cutoff_at,
                generated_at=source.generated_at,
                state=source.state.value,
            )
        )
        session.add(
            BriefingSnapshotRecord(
                id=uuid4(),
                briefing_date=date(2026, 8, 11),
                title="Legacy ID-only briefing",
                executive_summary="This row cannot be reconstructed truthfully.",
                event_ids=[str(source.event_ids[0])],
                event_snapshots=None,
                cutoff_at=source.cutoff_at,
                generated_at=source.generated_at,
                state="published",
            )
        )
        session.commit()

    assert repository.briefings() == [source]


def test_published_event_without_supporting_evidence_is_not_public(persistent_client):
    client, repository, sessions = persistent_client
    event_id = uuid4()
    claim_id = uuid4()
    changed_at = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    with sessions() as session:
        session.add(
            EventRecord(
                id=event_id,
                slug="missing-evidence",
                title="Published record lacking evidence",
                summary="This must not be made public.",
                category="models",
                published_at=changed_at,
                state="published",
                risk="low",
                confidence_grade="A",
                evidence_status="verified",
                public_version=1,
                tags=["test"],
            )
        )
        session.add(
            ClaimRecord(
                id=claim_id,
                event_id=event_id,
                text="A key claim without evidence.",
                importance="key",
                confidence=0.9,
            )
        )
        session.add(
            EventVersionRecord(
                id=uuid4(),
                event_id=event_id,
                version=1,
                title="Published record lacking evidence",
                summary="This must not be made public.",
                claims=[],
                changed_at=changed_at,
                change_note="initial publication",
            )
        )
        session.commit()

    assert repository.events() == []
    assert client.get("/api/v1/events").json()["items"] == []
    assert client.get("/api/v1/events/missing-evidence").status_code == 404
