#!/usr/bin/env python3
"""Validate the AI Radar source registry using only the Python standard library."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config" / "sources" / "ai_radar_sources.json"

ENUMS = {
    "source_type": {"rss", "html", "api", "github", "arxiv", "research", "sitemap", "manual"},
    "language": {"en", "zh", "multilingual"},
    "region": {"us", "cn", "uk", "eu", "fr", "ca", "de", "nl", "bg", "ch", "global"},
    "priority": {"P0", "P1", "P2", "P3"},
    "connector": {"rss", "html", "api", "github", "arxiv", "sitemap", "manual"},
    "authority": {"first_party", "regulator", "research", "media", "discovery"},
    "risk_level": {"low", "medium", "high"},
    "retention_policy": {"30_days", "90_days", "365_days", "permanent"},
    "manual_reason": {
        "access_control", "legal", "not_automatable", "paywall", "policy_review", "robots", "tls",
    },
}
REQUIRED = {
    "id", "name", "url", "source_type", "language", "region", "priority",
    "poll_interval_minutes", "connector", "authority", "risk_level",
    "retention_policy", "retention_basis", "enabled", "notes",
}

MINIMUM_AUTHORITY_COVERAGE = {
    "first_party": 100,
    "regulator": 50,
    "research": 50,
    "media": 50,
}
MINIMUM_LANGUAGE_COVERAGE = {"en": 75, "zh": 75}
MAXIMUM_REPOSITORY_SIGNALS = 250
MAXIMUM_PRIORITY_INTERVAL = {"P0": 10, "P1": 30, "P2": 60, "P3": 360}

# Do not schedule endpoints that need a subscription, login, or access bypass.
# A path-specific entry is used where the vendor has other public pages.
BLOCKED_ENDPOINTS = {
    ("www.economist.com", None),
    ("www.ft.com", None),
    ("www.bloomberg.com", None),
    ("www.wsj.com", None),
    ("www.theinformation.com", None),
    ("console.mistral.ai", None),
    ("dashboard.cohere.com", None),
    ("www.perplexity.ai", "/enterprise"),
    ("bailian.console.aliyun.com", None),
}
GENERIC_NAME_PATTERNS = (
    re.compile(r"^(?:research platform|ai news and discovery)\s+\d+$", re.IGNORECASE),
    re.compile(r".+\s+—\s+official update$", re.IGNORECASE),
)
COMPATIBLE_CONNECTORS = {
    "rss": {"rss"},
    "html": {"html", "manual"},
    "api": {"api"},
    "github": {"github"},
    "arxiv": {"arxiv"},
    "research": {"html", "arxiv", "manual"},
    "sitemap": {"sitemap"},
    "manual": {"manual"},
}
GITHUB_REPOSITORY_PATH = re.compile(
    r"^/(?P<owner>[^/]+)/(?P<repository>[^/]+)(?:/(?P<variant>releases))?/?$"
)


def validate(catalog: Path = CATALOG) -> dict[str, object]:
    data = json.loads(catalog.read_text(encoding="utf-8"))
    sources = data.get("sources")
    errors: list[str] = []
    if not isinstance(sources, list):
        raise TypeError("sources must be a list")
    if len(sources) != 500:
        errors.append(f"expected exactly 500 sources, got {len(sources)}")

    ids: set[str] = set()
    urls: set[str] = set()
    github_variants: dict[str, list[str]] = {}
    for number, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            errors.append(f"#{number}: source must be an object")
            continue
        missing = REQUIRED - source.keys()
        if missing:
            errors.append(f"#{number}: missing {sorted(missing)}")
            continue
        source_id, url = source["id"], source["url"]
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"#{number}: id must be a non-empty string")
        elif source_id in ids:
            errors.append(f"#{number}: duplicate id {source_id}")
        ids.add(source_id)
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append(f"#{number}: URL must be a public HTTPS URL: {url}")
        elif parsed.username is not None or parsed.password is not None:
            errors.append(f"#{number}: URL must not contain credentials: {url}")
        elif url in urls:
            errors.append(f"#{number}: duplicate URL {url}")
        else:
            host = parsed.netloc.lower()
            path = parsed.path.rstrip("/") or "/"
            for blocked_host, blocked_path in BLOCKED_ENDPOINTS:
                if (
                    host == blocked_host
                    and (blocked_path is None or path == blocked_path)
                    and not (
                        source.get("connector") == "manual"
                        and source.get("enabled") is False
                        and source.get("manual_reason") in {"access_control", "paywall"}
                    )
                ):
                    errors.append(f"#{number}: URL is login/paywall/access controlled: {url}")
        urls.add(url)
        for field, allowed in ENUMS.items():
            if field == "manual_reason" and field not in source:
                continue
            if source.get(field) not in allowed:
                errors.append(f"#{number}: invalid {field}: {source[field]!r}")
        interval = source["poll_interval_minutes"]
        if not isinstance(interval, int) or not 10 <= interval <= 10080:
            errors.append(f"#{number}: poll interval must be an integer in 10..10080")
        elif interval > MAXIMUM_PRIORITY_INTERVAL[source["priority"]]:
            errors.append(
                f"#{number}: {source['priority']} poll interval cannot exceed "
                f"{MAXIMUM_PRIORITY_INTERVAL[source['priority']]} minutes"
            )
        if not isinstance(source["enabled"], bool):
            errors.append(f"#{number}: enabled must be boolean")
        if not isinstance(source["notes"], str) or not source["notes"].strip():
            errors.append(f"#{number}: notes must be non-empty")
        if not isinstance(source["retention_basis"], str) or not source["retention_basis"].strip():
            errors.append(f"#{number}: retention_basis must be non-empty")
        source_type, connector = source["source_type"], source["connector"]
        if connector not in COMPATIBLE_CONNECTORS.get(source_type, set()):
            errors.append(
                f"#{number}: incompatible source_type/connector: {source_type}/{connector}"
            )
        if connector == "github":
            if parsed.netloc.lower() != "github.com":
                errors.append(f"#{number}: GitHub connector must use github.com")
            if parsed.query or parsed.fragment or "%" in parsed.path:
                errors.append(
                    f"#{number}: GitHub source URL cannot contain query, fragment, or escapes: {url}"
                )
            match = GITHUB_REPOSITORY_PATH.match(parsed.path)
            if not match:
                errors.append(
                    f"#{number}: GitHub source must be a repository root or releases endpoint: {url}"
                )
            else:
                repository = f"{match['owner'].lower()}/{match['repository'].lower()}"
                github_variants.setdefault(repository, []).append(match["variant"] or "root")
        if connector == "manual":
            if source["enabled"] is not False:
                errors.append(f"#{number}: manual sources must be disabled")
            if source.get("manual_reason") not in ENUMS["manual_reason"]:
                errors.append(f"#{number}: manual sources require a valid manual_reason")
        elif "manual_reason" in source:
            errors.append(f"#{number}: manual_reason is only valid for manual sources")

        if any(pattern.fullmatch(source["name"].strip()) for pattern in GENERIC_NAME_PATTERNS):
            errors.append(f"#{number}: generic source name: {source['name']!r}")

    for repository, variants in sorted(github_variants.items()):
        if len(variants) > 2 or (len(variants) == 2 and set(variants) != {"root", "releases"}):
            errors.append(
                "GitHub repository variant inflation for "
                f"{repository}: {', '.join(sorted(variants))}"
            )

    authority_coverage = Counter(item["authority"] for item in sources)
    language_coverage = Counter(item["language"] for item in sources)
    repository_signals = sum(
        item["source_type"] == "github"
        or item["connector"] == "github"
        or urlparse(item["url"]).netloc in {"github.com", "huggingface.co", "modelscope.cn"}
        for item in sources
    )
    for authority, minimum in MINIMUM_AUTHORITY_COVERAGE.items():
        if authority_coverage[authority] < minimum:
            errors.append(f"expected at least {minimum} {authority} sources, got {authority_coverage[authority]}")
    for language, minimum in MINIMUM_LANGUAGE_COVERAGE.items():
        if language_coverage[language] < minimum:
            errors.append(f"expected at least {minimum} {language} sources, got {language_coverage[language]}")
    if repository_signals > MAXIMUM_REPOSITORY_SIGNALS:
        errors.append(
            f"expected at most {MAXIMUM_REPOSITORY_SIGNALS} GitHub/Hugging Face/ModelScope signals, got {repository_signals}"
        )

    if errors:
        raise ValueError("\n".join(errors))
    return {
        "count": len(sources),
        "unique_ids": len(ids),
        "unique_urls": len(urls),
        "coverage": {
            field: dict(sorted(Counter(item[field] for item in sources).items()))
            for field in ("source_type", "language", "region", "priority",
                          "connector", "authority", "risk_level", "retention_policy")
        },
    }


def main() -> int:
    try:
        report = validate()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
