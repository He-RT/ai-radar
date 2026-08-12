from uuid import UUID

from zhenfu_api.auth import IdentityStore


def test_health_and_openapi_are_available(client):
    assert client.get("/health").json()["status"] == "ok"
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "震幅 AI Radar API"
    assert "/api/v1/radar" in schema["paths"]


def test_public_endpoints_expose_structured_demo_data(client):
    radar = client.get("/api/v1/radar")
    assert radar.status_code == 200
    assert len(radar.json()["headline_events"]) == 2
    assert radar.json()["headline_events"][0]["claims"][0]["evidence_ids"]

    events = client.get("/api/v1/events?category=models").json()
    assert events["total"] == 1
    slug = events["items"][0]["slug"]
    detail = client.get(f"/api/v1/events/{slug}").json()
    assert len(detail["evidence"]) == 2
    assert detail["score"]["algorithm_version"] == "radar-score-v1"

    assert client.get("/api/v1/actions").json()["total"] == 2
    assert client.get("/api/v1/briefings/2026-08-12").status_code == 200
    assert client.get("/api/v1/corrections").json()["total"] == 1
    assert client.get("/api/v1/coverage").json()["evidence_coverage"] == 1.0


def test_search_and_ask_return_citable_results(client):
    result = client.get("/api/v1/search", params={"q": "inference evaluation"}).json()
    assert result["total"] == 1
    answer = client.post("/api/v1/ask", json={"question": "What changed in inference?"}).json()
    assert answer["generated_by"] == "extractive-stub-v1"
    assert answer["citations"][0]["url"].startswith("/api/v1/events/")


def test_unknown_public_resources_are_404(client):
    assert client.get("/api/v1/events/missing").status_code == 404
    assert client.get("/api/v1/briefings/2020-01-01").status_code == 404


def test_identity_team_flow_and_password_is_never_returned(client):
    credentials = {
        "email": "Editor@Example.com",
        "password": "correct horse battery staple",
        "display_name": "Radar Editor",
    }
    registered = client.post("/api/v1/auth/register", json=credentials)
    assert registered.status_code == 201
    assert registered.json()["email"] == "editor@example.com"
    assert "password" not in registered.text

    login = client.post(
        "/api/v1/auth/login",
        json={"email": credentials["email"], "password": credentials["password"]},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/users/me", headers=headers).status_code == 200
    team = client.post("/api/v1/teams", headers=headers, json={"name": "Research"})
    assert team.status_code == 201
    assert len(client.get("/api/v1/teams", headers=headers).json()) == 1


def test_protected_routes_reject_missing_or_bad_tokens(client):
    assert client.get("/api/v1/users/me").status_code == 401
    assert client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer invalid"}
    ).status_code == 401


def test_publication_check_requires_editor_and_uses_domain_gate(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "reviewer@example.com",
            "password": "a strong reviewer password",
            "display_name": "Reviewer",
        },
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "reviewer@example.com", "password": "a strong reviewer password"},
    ).json()["access_token"]
    result = client.post(
        "/api/v1/internal/events/atlas-2-inference-efficiency/publication-check",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert result.status_code == 403

    identity_repository = client.app.state.identity_repository
    assert isinstance(identity_repository, IdentityStore)
    identity_repository.set_role(UUID(registered.json()["id"]), "editor")
    result = client.post(
        "/api/v1/internal/events/atlas-2-inference-efficiency/publication-check",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert result.status_code == 200
    assert result.json() == {"valid": True, "automatic_publish_allowed": True, "reasons": []}
