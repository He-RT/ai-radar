from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from zhenfu_api.api import create_app
from zhenfu_api.auth import IdentityStore
from zhenfu_api.config import Settings
from zhenfu_api.persistence import Base, SqlIdentityRepository, build_engine, session_factory
from zhenfu_api.persistence.tables import IdentitySessionRecord, UserRecord
from zhenfu_api.repository import SyntheticRadarRepository


@pytest.fixture
def sql_identity():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    repository = SqlIdentityRepository(sessions, ttl_seconds=3600)
    try:
        yield repository, sessions
    finally:
        engine.dispose()


def test_identity_persists_across_repository_instances_and_stores_only_token_hash(sql_identity):
    repository, sessions = sql_identity
    user = repository.register("Editor@Example.com", "correct horse battery staple", "Radar Editor")
    token = repository.login("editor@example.com", "correct horse battery staple")
    assert token is not None

    second_repository = SqlIdentityRepository(sessions, ttl_seconds=3600)
    restored = second_repository.user_for_token(token)
    assert restored is not None
    assert restored.id == user.id
    assert restored.email == "editor@example.com"

    with sessions() as session:
        stored_session = session.scalar(select(IdentitySessionRecord))
        assert stored_session is not None
        assert stored_session.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in stored_session.token_hash
        stored_user = session.get(UserRecord, user.id)
        assert stored_user is not None
        assert stored_user.role == "user"
        assert stored_user.password_hash.startswith("$argon2id$")


def test_unique_normalized_email_and_public_registration_role(sql_identity):
    repository, _sessions = sql_identity
    user = repository.register("Person@Example.com", "a sufficiently strong password", "Person")
    assert repository.role_for_user(user.id) == "user"

    with pytest.raises(ValueError, match="already registered"):
        repository.register(" person@example.com ", "another sufficiently strong password", "Other")


def test_multiple_sessions_expiry_and_independent_revocation(sql_identity):
    repository, sessions = sql_identity
    user = repository.register("person@example.com", "a sufficiently strong password", "Person")
    first = repository.login(user.email, "a sufficiently strong password")
    second = repository.login(user.email, "a sufficiently strong password")
    assert first is not None and second is not None and first != second
    assert repository.user_for_token(first) is not None
    assert repository.user_for_token(second) is not None

    assert repository.revoke_token(first)
    assert not repository.revoke_token(first)
    assert repository.user_for_token(first) is None
    assert repository.user_for_token(second) is not None

    second_hash = hashlib.sha256(second.encode()).hexdigest()
    with sessions.begin() as session:
        stored_session = session.scalar(
            select(IdentitySessionRecord).where(IdentitySessionRecord.token_hash == second_hash)
        )
        assert stored_session is not None
        stored_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert repository.user_for_token(second) is None


def test_team_membership_is_persistent_and_not_backed_by_public_dict(sql_identity):
    repository, sessions = sql_identity
    user = repository.register("owner@example.com", "a sufficiently strong password", "Owner")
    team = repository.create_team(user, "Research")

    second_repository = SqlIdentityRepository(sessions)
    assert second_repository.teams_for_user(user.id) == [team]
    assert not hasattr(second_repository, "teams")


def test_sql_identity_api_denies_user_and_allows_editor(sql_identity):
    repository, _sessions = sql_identity
    app = create_app(
        settings=Settings(environment="test", synthetic_repository=True),
        repository=SyntheticRadarRepository(),
        identity_repository=repository,
    )
    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={
                "email": "editor@example.com",
                "password": "a sufficiently strong password",
                "display_name": "Editor",
            },
        )
        assert registered.status_code == 201
        token = client.post(
            "/api/v1/auth/login",
            json={
                "email": "editor@example.com",
                "password": "a sufficiently strong password",
            },
        ).json()["access_token"]
        endpoint = "/api/v1/internal/events/atlas-2-inference-efficiency/publication-check"
        assert (
            client.post(endpoint, headers={"Authorization": f"Bearer {token}"}).status_code == 403
        )

        repository.set_role(UUID(registered.json()["id"]), "editor")
        assert (
            client.post(endpoint, headers={"Authorization": f"Bearer {token}"}).status_code == 200
        )


def test_production_create_app_fails_closed_without_identity_repository():
    settings = Settings(
        environment="production",
        app_secret_key="a-production-secret-key-with-32-characters",
        database_url="postgresql+psycopg://user:password@postgres/radar",
        s3_access_key="production-access-key",
        s3_secret_key="a-production-s3-secret-key",
        llm_api_key="production-llm-key",
        llm_model="production-model",
        public_base_url="https://radar.example",
        synthetic_repository=False,
    )
    with pytest.raises(RuntimeError, match="IdentityRepository"):
        create_app(settings=settings, repository=SyntheticRadarRepository())

    with pytest.raises(RuntimeError, match="persistent IdentityRepository"):
        create_app(
            settings=settings,
            repository=SyntheticRadarRepository(),
            identity_repository=IdentityStore(),
        )
