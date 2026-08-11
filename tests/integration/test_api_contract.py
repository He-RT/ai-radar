from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from zhenfu_api.api import create_app
from zhenfu_api.auth import IdentityStore
from zhenfu_api.config import Settings
from zhenfu_api.repository import SyntheticRadarRepository

ROUTES = json.loads(
    (ROOT / "packages" / "contracts" / "routes" / "v1" / "routes.json").read_text(
        encoding="utf-8"
    )
)
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def make_client() -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(environment="test", synthetic_repository=True),
            repository=SyntheticRadarRepository(),
            identity_store=IdentityStore(ttl_seconds=3600),
        )
    )


def runtime_validate(function_name: str, payload: Any) -> dict[str, Any]:
    script = f"""
import {{ {function_name} }} from './packages/contracts/src/index.js';
let source = '';
for await (const chunk of process.stdin) source += chunk;
process.stdout.write(JSON.stringify({function_name}(JSON.parse(source))));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def runtime_validate_args(function_name: str, *payloads: Any) -> dict[str, Any]:
    script = f"""
import {{ {function_name} }} from './packages/contracts/src/index.js';
let source = '';
for await (const chunk of process.stdin) source += chunk;
process.stdout.write(JSON.stringify({function_name}(...JSON.parse(source))));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        input=json.dumps(payloads),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def success_schema(
    openapi: dict[str, Any],
    method: str,
    path: str,
    status: int,
    media_type: str = "application/json",
) -> dict[str, Any]:
    return openapi["paths"][path][method.lower()]["responses"][str(status)]["content"][
        media_type
    ]["schema"]


def test_openapi_operation_inventory_matches_versioned_route_contract() -> None:
    with make_client() as client:
        openapi = client.get("/openapi.json").json()

    actual = {
        (method.upper(), path)
        for path, path_item in openapi["paths"].items()
        for method in path_item
        if method in HTTP_METHODS
    }
    expected = {(entry["method"], entry["path"]) for entry in ROUTES["api"]}
    assert actual == expected
    assert openapi["info"]["version"] == ROUTES["apiVersion"]

    for entry in ROUTES["api"]:
        schema = success_schema(
            openapi,
            entry["method"],
            entry["path"],
            entry["successStatus"],
            entry.get("responseMediaType", "application/json"),
        )
        assert schema, f"{entry['method']} {entry['path']} has no successful response schema"
        if expected_component := entry.get("openapiSchema"):
            assert schema.get("$ref") == f"#/components/schemas/{expected_component}"
        if expected_item_component := entry.get("openapiItemSchema"):
            assert schema.get("items", {}).get("$ref") == (
                f"#/components/schemas/{expected_item_component}"
            )


def test_generated_openapi_release_snapshot_has_not_drifted() -> None:
    exported = json.loads(
        (ROOT / "packages" / "contracts" / "openapi" / "api-0.1.0.json").read_text(
            encoding="utf-8"
        )
    )
    with make_client() as client:
        runtime = client.get("/openapi.json").json()
    assert runtime == exported, (
        "FastAPI OpenAPI drifted from packages/contracts/openapi/api-0.1.0.json; "
        "review the compatibility change and regenerate with export_openapi.py"
    )


def test_openapi_names_the_public_radar_briefing_and_coverage_shapes() -> None:
    with make_client() as client:
        openapi = client.get("/openapi.json").json()

    for method, path, status in [
        ("GET", "/api/v1/radar", 200),
        ("GET", "/api/v1/briefings/{briefing_date}", 200),
        ("GET", "/api/v1/coverage", 200),
    ]:
        schema = success_schema(openapi, method, path, status)
        assert "$ref" in schema or schema.get("properties"), (
            f"{method} {path} must expose a named or structured response instead of an unrestricted object"
        )

    event_schema = openapi["components"]["schemas"]["Event"]
    for field in ["confidence_grade", "evidence_status", "public_version"]:
        assert field in event_schema["properties"]

    radar_ref = success_schema(openapi, "GET", "/api/v1/radar", 200)["$ref"].split("/")[-1]
    radar_schema = openapi["components"]["schemas"][radar_ref]
    assert "knowledge_cutoff" in radar_schema["properties"]

    briefing_ref = success_schema(openapi, "GET", "/api/v1/briefings/{briefing_date}", 200)[
        "$ref"
    ].split("/")[-1]
    briefing_schema = openapi["components"]["schemas"][briefing_ref]
    assert "cutoff_at" in briefing_schema["properties"]
    assert "event_snapshots" in briefing_schema["properties"]
    assert (
        briefing_schema["properties"]["event_snapshots"]["items"]["$ref"]
        == "#/components/schemas/BriefingEventSnapshot"
    )

    markdown_schema = success_schema(
        openapi, "GET", "/api/v1/briefings/{briefing_date}.md", 200, "text/markdown"
    )
    rss_schema = success_schema(openapi, "GET", "/api/v1/feeds/daily.xml", 200, "application/rss+xml")
    assert markdown_schema == {"type": "string"}
    assert rss_schema == {"type": "string"}


def test_public_api_responses_satisfy_the_shared_runtime_contract() -> None:
    with make_client() as client:
        radar_response = client.get("/api/v1/radar")
        assert radar_response.status_code == 200
        radar = radar_response.json()
        assert runtime_validate("validateRadarResponse", radar) == {"ok": True, "errors": []}

        events_page = client.get("/api/v1/events").json()
        assert runtime_validate("validateEventPage", events_page) == {"ok": True, "errors": []}
        assert len(events_page["items"]) <= events_page["limit"]
        assert len(events_page["items"]) <= events_page["total"]
        for event in events_page["items"]:
            assert runtime_validate("validatePublicEvent", event) == {"ok": True, "errors": []}
            detail = client.get(f"/api/v1/events/{event['slug']}").json()
            assert detail == event

        actions = client.get("/api/v1/actions").json()
        assert runtime_validate("validateActionRecipePage", actions) == {"ok": True, "errors": []}

        if radar["latest_briefing"] is not None:
            briefing = client.get(
                f"/api/v1/briefings/{radar['latest_briefing']['briefing_date']}"
            ).json()
            assert briefing == radar["latest_briefing"]
            assert runtime_validate("validateBriefingSnapshot", briefing) == {
                "ok": True,
                "errors": [],
            }

        corrections = client.get("/api/v1/corrections").json()
        assert runtime_validate("validateCorrectionPage", corrections) == {
            "ok": True,
            "errors": [],
        }

        coverage = client.get("/api/v1/coverage").json()
        assert runtime_validate("validateCoverageSnapshot", coverage) == {
            "ok": True,
            "errors": [],
        }

        search = client.get("/api/v1/search", params={"q": "inference"}).json()
        assert runtime_validate("validateEventPage", search) == {"ok": True, "errors": []}

        answer = client.post(
            "/api/v1/ask", json={"question": "What changed in inference?"}
        ).json()
        assert runtime_validate("validateAnswer", answer) == {"ok": True, "errors": []}


def test_key_claim_contract_rejects_missing_or_dangling_evidence() -> None:
    with make_client() as client:
        event = client.get("/api/v1/events").json()["items"][0]

    key_claim_index = next(
        index for index, claim in enumerate(event["claims"]) if claim["importance"] == "key"
    )
    unsupported = copy.deepcopy(event)
    unsupported["claims"][key_claim_index]["evidence_ids"] = []
    unsupported_result = runtime_validate("validatePublicEvent", unsupported)
    assert "key_claim_without_evidence" in {
        error["code"] for error in unsupported_result["errors"]
    }

    dangling = copy.deepcopy(event)
    dangling["claims"][key_claim_index]["evidence_ids"] = [
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    ]
    dangling_result = runtime_validate("validatePublicEvent", dangling)
    assert "missing_evidence_reference" in {error["code"] for error in dangling_result["errors"]}


def test_personalized_lens_cannot_change_api_facts_versions_or_cutoff() -> None:
    with make_client() as client:
        radar = client.get("/api/v1/radar").json()

    baseline = {
        "contract_version": ROUTES["contractVersion"],
        "knowledge_cutoff": radar["knowledge_cutoff"],
        "events": radar["headline_events"],
    }
    personalized = {
        "contract_version": ROUTES["contractVersion"],
        "knowledge_cutoff": radar["knowledge_cutoff"],
        "items": [
            {
                "fact": copy.deepcopy(event),
                "lens": {
                    "relevance": 80 - index,
                    "explanation": "Reader-specific ordering over a shared fact.",
                },
            }
            for index, event in enumerate(reversed(radar["headline_events"]))
        ],
    }
    assert runtime_validate_args("validatePersonalizationBoundary", baseline, personalized) == {
        "ok": True,
        "errors": [],
    }

    changed_cutoff = copy.deepcopy(personalized)
    changed_cutoff["knowledge_cutoff"] = "2000-01-01T00:00:00Z"

    changed_confidence = copy.deepcopy(personalized)
    current_grade = changed_confidence["items"][0]["fact"]["confidence_grade"]
    changed_confidence["items"][0]["fact"]["confidence_grade"] = (
        "B" if current_grade == "A" else "A"
    )

    changed_evidence = copy.deepcopy(personalized)
    changed_evidence["items"][0]["fact"]["evidence"][0]["quote"] += " Personalized."

    changed_version = copy.deepcopy(personalized)
    changed_version["items"][0]["fact"]["public_version"] += 1
    changed_version["items"][0]["fact"]["versions"][-1]["version"] += 1

    for changed in [changed_cutoff, changed_confidence, changed_evidence, changed_version]:
        result = runtime_validate_args("validatePersonalizationBoundary", baseline, changed)
        assert result["ok"] is False
        assert {
            "personalized_cutoff_changed",
            "personalized_fact_changed",
        } & {error["code"] for error in result["errors"]}


def test_event_facts_are_identical_across_public_api_surfaces() -> None:
    with make_client() as client:
        radar = client.get("/api/v1/radar").json()
        ledger = client.get("/api/v1/events").json()["items"]

        ledger_by_id = {event["id"]: event for event in ledger}
        for headline in radar["headline_events"]:
            assert headline == ledger_by_id[headline["id"]]
            detail = client.get(f"/api/v1/events/{headline['slug']}").json()
            assert detail == headline
