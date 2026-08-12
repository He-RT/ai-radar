from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin
from uuid import UUID
from xml.etree import ElementTree

from zhenfu_api.domain.services import canonicalize_url


@dataclass(frozen=True, slots=True)
class Candidate:
    source_id: UUID
    external_id: str
    url: str
    title: str
    published_at: datetime | None = None
    summary: str = ""
    content_text: str = ""


class Connector(Protocol):
    def discover(self, payload: bytes, *, source_id: UUID, base_url: str) -> list[Candidate]: ...


MAX_CANDIDATES = 100
MAX_HTML_TEXT_CHARS = 100_000
MAX_SUMMARY_CHARS = 2_000


def _text(node: ElementTree.Element | None, *names: str) -> str:
    if node is None:
        return ""
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def _published(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class RSSConnector:
    """Parse RSS 2.0 and Atom without executing embedded content."""

    def discover(self, payload: bytes, *, source_id: UUID, base_url: str) -> list[Candidate]:
        root = ElementTree.fromstring(payload)
        entries = root.findall("./channel/item")
        atom = False
        if not entries:
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")
            atom = True
        values: list[Candidate] = []
        for index, entry in enumerate(entries[:MAX_CANDIDATES]):
            if atom:
                title = _text(entry, "{http://www.w3.org/2005/Atom}title")
                identifier = _text(entry, "{http://www.w3.org/2005/Atom}id")
                link_node = entry.find("{http://www.w3.org/2005/Atom}link")
                link = link_node.attrib.get("href", "") if link_node is not None else identifier
                published = _text(
                    entry,
                    "{http://www.w3.org/2005/Atom}published",
                    "{http://www.w3.org/2005/Atom}updated",
                )
            else:
                title = _text(entry, "title")
                link = _text(entry, "link")
                identifier = _text(entry, "guid") or link
                published = _text(entry, "pubDate")
            if not title or not link:
                continue
            url = canonicalize_url(urljoin(base_url, link))
            values.append(
                Candidate(
                    source_id=source_id,
                    external_id=identifier or f"{url}#{index}",
                    url=url,
                    title=title,
                    published_at=_published(published),
                )
            )
        return values


class SitemapConnector:
    def discover(self, payload: bytes, *, source_id: UUID, base_url: str) -> list[Candidate]:
        root = ElementTree.fromstring(payload)
        namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        values: list[Candidate] = []
        for index, entry in enumerate(root.findall(f"{namespace}url")[:MAX_CANDIDATES]):
            location = _text(entry, f"{namespace}loc")
            if not location:
                continue
            modified = _text(entry, f"{namespace}lastmod")
            url = canonicalize_url(urljoin(base_url, location))
            values.append(
                Candidate(
                    source_id=source_id,
                    external_id=url,
                    url=url,
                    title=url,
                    published_at=_published(modified),
                )
            )
        return values


class GitHubRepositoryConnector:
    """Normalize one previously fetched GitHub repository REST response."""

    def discover_json(
        self, repository: dict[str, object], *, source_id: UUID, base_url: str
    ) -> list[Candidate]:
        external_id = _clean_text(str(repository.get("node_id") or repository.get("id") or ""))
        url = _clean_text(str(repository.get("html_url") or ""))
        title = _clean_text(str(repository.get("full_name") or repository.get("name") or ""))
        if not external_id or not url or not title:
            return []
        return [
            Candidate(
                source_id=source_id,
                external_id=external_id,
                url=canonicalize_url(urljoin(base_url, url)),
                title=title[:500],
                published_at=_published(
                    str(repository.get("pushed_at") or repository.get("updated_at") or "")
                ),
                summary=_clean_text(str(repository.get("description") or ""))[
                    :MAX_SUMMARY_CHARS
                ],
            )
        ]


class GitHubReleaseConnector:
    """Normalize a previously fetched GitHub Releases JSON response."""

    def discover_json(
        self, releases: list[dict[str, object]], *, source_id: UUID, base_url: str
    ) -> list[Candidate]:
        values: list[Candidate] = []
        for release in releases[:MAX_CANDIDATES]:
            if not isinstance(release, dict):
                continue
            url = str(release.get("html_url") or "")
            title = str(release.get("name") or release.get("tag_name") or "")
            external_id = str(release.get("id") or release.get("tag_name") or url)
            if not url or not title:
                continue
            values.append(
                Candidate(
                    source_id=source_id,
                    external_id=external_id,
                    url=canonicalize_url(urljoin(base_url, url)),
                    title=title,
                    published_at=_published(str(release.get("published_at") or "")),
                    summary=_clean_text(str(release.get("body") or ""))[:MAX_SUMMARY_CHARS],
                )
            )
        return values


class GitHubAdvisoryConnector:
    """Normalize GitHub repository security-advisory REST responses."""

    def discover_json(
        self, advisories: list[dict[str, object]], *, source_id: UUID, base_url: str
    ) -> list[Candidate]:
        values: list[Candidate] = []
        for advisory in advisories[:MAX_CANDIDATES]:
            if not isinstance(advisory, dict):
                continue
            identifier = str(advisory.get("ghsa_id") or advisory.get("cve_id") or "")
            url = str(advisory.get("html_url") or "")
            summary = _clean_text(str(advisory.get("summary") or ""))
            title = summary or identifier
            if not identifier or not url or not title:
                continue
            values.append(
                Candidate(
                    source_id=source_id,
                    external_id=identifier,
                    url=canonicalize_url(urljoin(base_url, url)),
                    title=title[:500],
                    published_at=_published(
                        str(advisory.get("published_at") or advisory.get("updated_at") or "")
                    ),
                    summary=_clean_text(str(advisory.get("description") or summary))[
                        :MAX_SUMMARY_CHARS
                    ],
                )
            )
        return values


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\x00", " ").split())


class _HTMLDocumentParser(HTMLParser):
    """Extract bounded visible text and metadata; markup is never rendered or executed."""

    _BLOCKED = frozenset({"script", "style", "template", "noscript", "svg", "math"})
    _TITLE_KEYS = frozenset({"og:title", "twitter:title"})
    _DESCRIPTION_KEYS = frozenset({"description", "og:description", "twitter:description"})
    _PUBLISHED_KEYS = frozenset(
        {"article:published_time", "date", "datepublished", "date-published", "pubdate"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self._in_title = False
        self._in_heading = False
        self._text_length = 0
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.text_parts: list[str] = []
        self.metadata_title = ""
        self.description = ""
        self.published = ""

    @staticmethod
    def _attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key.casefold(): value or "" for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in self._BLOCKED:
            self._blocked_depth += 1
            return
        if self._blocked_depth:
            return
        if normalized_tag == "title":
            self._in_title = True
        elif normalized_tag == "h1" and not self.heading_parts:
            self._in_heading = True
        elif normalized_tag == "meta":
            values = self._attributes(attrs)
            key = (
                values.get("property") or values.get("name") or values.get("itemprop") or ""
            ).casefold()
            content = _clean_text(values.get("content", ""))
            if key in self._TITLE_KEYS and content and not self.metadata_title:
                self.metadata_title = content
            elif key in self._DESCRIPTION_KEYS and content and not self.description:
                self.description = content
            elif key in self._PUBLISHED_KEYS and content and not self.published:
                self.published = content
        elif normalized_tag == "time" and not self.published:
            value = self._attributes(attrs).get("datetime", "")
            if value:
                self.published = _clean_text(value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() in self._BLOCKED:
            self._blocked_depth -= 1

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in self._BLOCKED:
            if self._blocked_depth:
                self._blocked_depth -= 1
            return
        if self._blocked_depth:
            return
        if normalized_tag == "title":
            self._in_title = False
        elif normalized_tag == "h1":
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._blocked_depth:
            return
        value = _clean_text(data)
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        if self._in_heading:
            self.heading_parts.append(value)
        if self._text_length >= MAX_HTML_TEXT_CHARS:
            return
        remaining = MAX_HTML_TEXT_CHARS - self._text_length
        bounded = value[:remaining]
        self.text_parts.append(bounded)
        self._text_length += len(bounded) + 1


class HTMLConnector:
    """Convert one fetched HTML page into one inert, cleaned candidate."""

    def discover(self, payload: bytes, *, source_id: UUID, base_url: str) -> list[Candidate]:
        parser = _HTMLDocumentParser()
        # UTF-8 with replacement is deterministic and cannot execute document code.
        parser.feed(payload.decode("utf-8", errors="replace"))
        parser.close()

        content_text = _clean_text(" ".join(parser.text_parts))[:MAX_HTML_TEXT_CHARS]
        document_title = _clean_text(" ".join(parser.title_parts))
        heading = _clean_text(" ".join(parser.heading_parts))
        title = (parser.metadata_title or document_title or heading).strip()
        if not title and content_text:
            title = content_text[:200]
        title = re.sub(r"\s+", " ", title)[:500]
        if not title:
            return []

        url = canonicalize_url(base_url)
        summary = (parser.description or content_text)[:MAX_SUMMARY_CHARS]
        return [
            Candidate(
                source_id=source_id,
                external_id=url,
                url=url,
                title=title,
                published_at=_published(parser.published),
                summary=summary,
                content_text=content_text,
            )
        ]
