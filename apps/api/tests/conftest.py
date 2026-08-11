import pytest
from fastapi.testclient import TestClient

from zhenfu_api.api import create_app
from zhenfu_api.auth import IdentityStore
from zhenfu_api.config import Settings
from zhenfu_api.repository import SyntheticRadarRepository


@pytest.fixture
def repository() -> SyntheticRadarRepository:
    return SyntheticRadarRepository()


@pytest.fixture
def client(repository: SyntheticRadarRepository):
    app = create_app(
        settings=Settings(environment="test", synthetic_repository=True),
        repository=repository,
        identity_store=IdentityStore(ttl_seconds=3600),
    )
    with TestClient(app) as test_client:
        yield test_client
