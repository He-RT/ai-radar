from __future__ import annotations

from zhenfu_api.jobs import celery_app


def main() -> None:
    """Run evidence extraction, clustering, scoring, and publishing tasks."""
    celery_app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            "--queues=radar-enrichment,radar-realtime",
            "--concurrency=1",
            "--hostname=enrichment@%h",
        ]
    )


if __name__ == "__main__":
    main()
