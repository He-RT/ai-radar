from __future__ import annotations

from celery import Celery

from zhenfu_api.config import Settings, get_settings


def create_celery(settings: Settings | None = None) -> Celery:
    runtime = settings or get_settings()
    app = Celery("zhenfu", broker=runtime.valkey_url, backend=None)
    app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_default_queue="radar-realtime",
        task_routes={
            "radar.ingest.*": {"queue": "radar-ingest"},
            "radar.enrichment.*": {"queue": "radar-enrichment"},
        },
        task_annotations={
            "radar.ingest.*": {
                "soft_time_limit": 55,
                "time_limit": 60,
                "max_retries": 5,
                "default_retry_delay": 30,
            },
            "radar.enrichment.*": {
                "soft_time_limit": 285,
                "time_limit": 300,
                "max_retries": 3,
                "default_retry_delay": 60,
            },
        },
        task_serializer="json",
        accept_content=["json"],
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_publish_retry=True,
        task_publish_retry_policy={
            "max_retries": 3,
            "interval_start": 0,
            "interval_step": 0.5,
            "interval_max": 2,
        },
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        worker_concurrency=1,
        worker_max_tasks_per_child=100,
        worker_cancel_long_running_tasks_on_connection_loss=True,
    )
    return app


celery_app = create_celery()


@celery_app.task(name="radar.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "worker": "zhenfu"}
