from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from zhenfu_api.domain.models import Event


class Citation(BaseModel):
    event_slug: str
    title: str
    url: str


class Answer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    generated_by: str


class AnswerAdapter(Protocol):
    def answer(self, question: str, events: list[Event]) -> Answer: ...


class ExtractiveAnswerStub:
    """Deterministic local adapter; it never invokes an LLM or the network."""

    def answer(self, question: str, events: list[Event]) -> Answer:
        terms = {term.casefold() for term in question.split() if len(term) > 2}
        ranked = sorted(
            events,
            key=lambda event: sum(
                term in f"{event.title} {event.summary}".casefold() for term in terms
            ),
            reverse=True,
        )[:3]
        if not ranked:
            return Answer(
                answer="No published Radar evidence matches this question.",
                generated_by="extractive-stub-v1",
            )
        digest = " ".join(event.summary for event in ranked)
        return Answer(
            answer=digest,
            citations=[
                Citation(
                    event_slug=event.slug,
                    title=event.title,
                    url=f"/api/v1/events/{event.slug}",
                )
                for event in ranked
            ],
            generated_by="extractive-stub-v1",
        )
