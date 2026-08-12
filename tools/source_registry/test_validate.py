import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import TypedDict, cast

sys.path.insert(0, str(Path(__file__).parent))
from validate import CATALOG, validate


class ValidationReport(TypedDict):
    count: int
    unique_ids: int
    unique_urls: int
    coverage: dict[str, dict[str, int]]


class RegistryValidationTests(unittest.TestCase):
    def assert_catalog_error(self, mutate, message: str) -> None:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        mutate(data["sources"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, message):
                validate(path)

    def test_catalog_is_valid_and_exactly_500(self) -> None:
        report = cast(ValidationReport, validate(CATALOG))
        self.assertEqual(report["count"], 500)
        self.assertEqual(report["unique_ids"], 500)
        self.assertEqual(report["unique_urls"], 500)

    def test_reports_required_coverage(self) -> None:
        report = cast(ValidationReport, validate(CATALOG))
        coverage = report["coverage"]
        for field in ("source_type", "language", "region", "priority", "connector",
                      "authority", "risk_level", "retention_policy"):
            self.assertTrue(coverage[field], field)

    def test_diversity_coverage(self) -> None:
        coverage = cast(ValidationReport, validate(CATALOG))["coverage"]
        self.assertGreaterEqual(coverage["authority"].get("first_party", 0), 100)
        self.assertGreaterEqual(coverage["authority"].get("regulator", 0), 50)
        self.assertGreaterEqual(coverage["authority"].get("research", 0), 50)
        self.assertGreaterEqual(coverage["authority"].get("media", 0), 50)
        self.assertGreaterEqual(coverage["language"].get("en", 0), 75)
        self.assertGreaterEqual(coverage["language"].get("zh", 0), 75)
        self.assertLessEqual(coverage["source_type"].get("github", 0), 250)

    def test_schedule_manual_and_retention_semantics(self) -> None:
        sources = json.loads(CATALOG.read_text(encoding="utf-8"))["sources"]
        maximum_interval = {"P0": 10, "P1": 30, "P2": 60, "P3": 360}
        for source in sources:
            with self.subTest(source_id=source["id"]):
                self.assertLessEqual(
                    source["poll_interval_minutes"], maximum_interval[source["priority"]]
                )
                self.assertTrue(source["retention_basis"].strip())
                if source["connector"] == "manual":
                    self.assertFalse(source["enabled"])
                    self.assertTrue(source["manual_reason"])
                else:
                    self.assertNotIn("manual_reason", source)

    def test_rejects_slow_priority_or_enabled_manual_source(self) -> None:
        def slow_p0(sources: list[dict[str, object]]) -> None:
            sources[0]["priority"] = "P0"
            sources[0]["poll_interval_minutes"] = 30

        self.assert_catalog_error(slow_p0, "P0 poll interval cannot exceed 10")

        def enabled_manual(sources: list[dict[str, object]]) -> None:
            manual = next(source for source in sources if source["connector"] == "manual")
            manual["enabled"] = True

        self.assert_catalog_error(enabled_manual, "manual sources must be disabled")

    def test_rejects_known_login_or_paywall_endpoints(self) -> None:
        urls = (
            "https://www.economist.com/science-and-technology",
            "https://www.ft.com/technology",
            "https://www.bloomberg.com/technology",
            "https://www.wsj.com/tech",
            "https://www.theinformation.com/tech/artificial-intelligence",
            "https://console.mistral.ai/",
            "https://dashboard.cohere.com/",
            "https://www.perplexity.ai/enterprise",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assert_catalog_error(
                    lambda sources, url=url: sources[450].update(url=url),
                    "login/paywall/access controlled",
                )

    def test_rejects_generic_numbered_name(self) -> None:
        def mutate(sources: list[dict[str, object]]) -> None:
            sources[400]["name"] = "Research platform 1"

        self.assert_catalog_error(mutate, "generic source name")

    def test_rejects_github_variant_inflation(self) -> None:
        def mutate(sources: list[dict[str, object]]) -> None:
            variant = deepcopy(sources[0])
            variant["id"] = "github-variant-test"
            variant["url"] = "https://github.com/openai/openai-python/"
            sources[2] = variant

        self.assert_catalog_error(mutate, "GitHub repository variant inflation")

    def test_rejects_github_query_and_url_credentials(self) -> None:
        self.assert_catalog_error(
            lambda sources: sources[0].update(url=f"{sources[0]['url']}?tab=readme"),
            "GitHub source URL cannot contain query",
        )
        self.assert_catalog_error(
            lambda sources: sources[450].update(url="https://user:secret@example.com/ai"),
            "must not contain credentials",
        )

    def test_rejects_incompatible_connector(self) -> None:
        def mutate(sources: list[dict[str, object]]) -> None:
            sources[450]["source_type"] = "rss"
            sources[450]["connector"] = "html"

        self.assert_catalog_error(mutate, "incompatible source_type/connector")


if __name__ == "__main__":
    unittest.main()
