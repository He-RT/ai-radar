from fastapi import FastAPI

from zhenfu_api.api import create_app
from zhenfu_api.config import Settings, get_settings
from zhenfu_api.persistence import (
    SqlIdentityRepository,
    SqlRadarRepository,
    build_engine,
    session_factory,
)


def create_application(*, settings: Settings | None = None) -> FastAPI:
    """Assemble the process-level application from its configured persistence mode."""
    settings = settings or get_settings()
    if settings.synthetic_repository:
        return create_app(settings=settings)

    engine = build_engine(settings.database_url)
    sessions = session_factory(engine)
    repository = SqlRadarRepository(sessions)
    identity_repository = SqlIdentityRepository(
        sessions,
        ttl_seconds=settings.session_ttl_seconds,
    )
    app = create_app(
        settings=settings,
        repository=repository,
        identity_repository=identity_repository,
    )
    app.state.database_engine = engine
    app.router.on_shutdown.append(engine.dispose)

    return app


app = create_application()
