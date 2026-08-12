import pytest
from pydantic import ValidationError

from zhenfu_api.config import Settings
from zhenfu_api.jobs import create_celery


def production_settings(**overrides: str | bool) -> Settings:
    values: dict[str, str | bool] = {
        "environment": "production",
        "log_format": "json",
        "service_role": "enrichment-worker",
        "app_secret_key": "production-app-secret-with-32-characters",
        "database_url": "postgresql+psycopg://user:password@postgres/radar",
        "valkey_url": "redis://:password@valkey:6379/0",
        "s3_endpoint": "http://minio:9000",
        "s3_access_key": "access-key",
        "s3_secret_key": "production-s3-secret-with-24-characters",
        "s3_bucket": "radar",
        "s3_public_endpoint": "",
        "smtp_url": "smtp://mailpit:1025",
        "llm_api_key": "llm-key",
        "llm_base_url": "https://api.openai.com/v1",
        "llm_model": "approved-model",
        "public_base_url": "https://radar.example",
        "synthetic_repository": False,
    }
    values.update(overrides)
    return Settings(**values)  # pyright: ignore[reportArgumentType]


def test_development_defaults_are_complete_local_stubs():
    settings = Settings()

    assert settings.environment == "development"
    assert settings.app_secret_key
    assert settings.valkey_url == "redis://localhost:6379/0"
    assert settings.s3_secret_key
    assert settings.llm_api_key
    assert settings.llm_model


@pytest.mark.parametrize(
    ("service_role", "field"),
    [
        ("migrate", "database_url"),
        ("api", "app_secret_key"),
        ("api", "database_url"),
        ("api", "valkey_url"),
        ("api", "smtp_url"),
        ("ingest-worker", "database_url"),
        ("ingest-worker", "valkey_url"),
        ("ingest-worker", "s3_endpoint"),
        ("ingest-worker", "s3_access_key"),
        ("ingest-worker", "s3_secret_key"),
        ("ingest-worker", "s3_bucket"),
        ("enrichment-worker", "database_url"),
        ("enrichment-worker", "valkey_url"),
        ("enrichment-worker", "s3_endpoint"),
        ("enrichment-worker", "s3_access_key"),
        ("enrichment-worker", "s3_secret_key"),
        ("enrichment-worker", "s3_bucket"),
        ("enrichment-worker", "llm_api_key"),
        ("enrichment-worker", "llm_base_url"),
        ("enrichment-worker", "llm_model"),
    ],
)
def test_production_rejects_blank_required_runtime_values(service_role: str, field: str):
    with pytest.raises(ValidationError, match=field):
        production_settings(service_role=service_role, **{field: "  "})


def test_migration_role_does_not_receive_unrelated_application_secrets() -> None:
    settings = Settings(
        environment="production",
        service_role="migrate",
        database_url="postgresql+psycopg://migrate:password@postgres/radar",
        synthetic_repository=False,
    )

    assert settings.service_role == "migrate"


def test_celery_uses_settings_and_constrains_worker_execution():
    settings = Settings(valkey_url="redis://broker.internal:6379/7")
    app = create_celery(settings)

    assert app.conf.broker_url == settings.valkey_url
    assert app.conf.task_routes["radar.ingest.*"]["queue"] == "radar-ingest"
    assert app.conf.task_routes["radar.enrichment.*"]["queue"] == "radar-enrichment"
    assert app.conf.task_annotations["radar.ingest.*"]["time_limit"] == 60
    assert app.conf.task_annotations["radar.enrichment.*"]["time_limit"] == 300
    assert app.conf.task_publish_retry is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.worker_concurrency == 1
    assert app.conf.worker_cancel_long_running_tasks_on_connection_loss is True


@pytest.mark.parametrize(
    ("service_role", "field", "value"),
    [
        ("api", "app_secret_key", "development-only-secret-key"),
        ("ingest-worker", "s3_access_key", "development-s3-access-key"),
        ("ingest-worker", "s3_secret_key", "development-s3-secret-key"),
        ("enrichment-worker", "llm_api_key", "development-llm-api-key"),
        ("enrichment-worker", "llm_model", "development-llm-model"),
        ("api", "secure_cookies", False),
    ],
)
def test_production_rejects_development_security_defaults(
    service_role: str, field: str, value: str | bool
):
    with pytest.raises(ValidationError, match="production"):
        production_settings(service_role=service_role, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_api_key", "REPLACE_WITH_APPROVED_LLM_API_KEY"),
        ("llm_model", "REPLACE_WITH_APPROVED_MODEL_ID"),
    ],
)
def test_production_rejects_unresolved_placeholders(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        production_settings(service_role="enrichment-worker", **{field: value})
