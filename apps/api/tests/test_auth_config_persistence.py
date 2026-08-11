import pytest
from pydantic import ValidationError
from sqlalchemy import inspect

from zhenfu_api.auth import hash_password, verify_password
from zhenfu_api.config import Settings
from zhenfu_api.persistence import Base, build_engine, tables  # noqa: F401


def test_password_hash_is_argon2id_and_verifies():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect horse battery staple", encoded)


def test_short_password_is_rejected():
    with pytest.raises(ValueError, match="at least 12"):
        hash_password("too-short")


@pytest.mark.parametrize(
    "override",
    [
        {"database_url": "sqlite:///prod.db", "synthetic_repository": False, "public_base_url": "https://radar.example"},
        {"database_url": "postgresql+psycopg://db/radar", "synthetic_repository": True, "public_base_url": "https://radar.example"},
        {"database_url": "postgresql+psycopg://db/radar", "synthetic_repository": False, "public_base_url": "http://radar.example"},
    ],
)
def test_production_rejects_unsafe_configuration(override):
    with pytest.raises(ValidationError):
        Settings(environment="production", **override)


def test_sqlalchemy_metadata_builds_all_domain_tables_in_sqlite():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        names = set(inspect(engine).get_table_names())
        assert {
            "sources",
            "source_items",
            "evidence",
            "claims",
            "events",
            "event_versions",
            "score_snapshots",
            "action_recipes",
            "briefing_snapshots",
            "corrections",
            "users",
            "identity_sessions",
            "watches",
            "teams",
            "outbox",
            "job_receipts",
        } <= names
        briefing_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("briefing_snapshots")
        }
        assert "event_snapshots" in briefing_columns
        assert briefing_columns["event_snapshots"]["nullable"] is True
    finally:
        engine.dispose()
