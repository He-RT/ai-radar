from fastapi.testclient import TestClient

from zhenfu_api.api import create_app
from zhenfu_api.config import Settings


class ExplodingLimiter:
    def check(self, _key: str, _limit: int, _window_seconds: int):
        raise AssertionError("oversized bodies must be rejected before rate limiting")


def test_oversized_login_body_is_rejected_before_rate_limiting() -> None:
    app = create_app(
        settings=Settings(environment="test"),
        rate_limiter=ExplodingLimiter(),  # type: ignore[arg-type]
    )
    response = TestClient(app).post(
        "/api/v1/auth/login",
        content=b"x" * 65_537,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Payload Too Large"


def test_identity_fields_have_bounded_lengths() -> None:
    client = TestClient(create_app(settings=Settings(environment="test")))

    long_email = client.post(
        "/api/v1/auth/login",
        json={"email": f"{'a' * 310}@example.com", "password": "valid-password"},
    )
    long_password = client.post(
        "/api/v1/auth/login",
        json={"email": "reader@example.com", "password": "x" * 257},
    )

    assert long_email.status_code == 422
    assert long_password.status_code == 422
