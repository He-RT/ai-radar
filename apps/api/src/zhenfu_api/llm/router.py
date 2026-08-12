from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Capability(StrEnum):
    TRIAGE = "triage"
    TRANSLATE = "translate"
    CLAIM_EXTRACTION = "claim_extraction"
    ANSWER = "answer"


class StructuredResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    payload: dict[str, object]


class ModelUnavailable(RuntimeError):
    pass


class ModelProvider(Protocol):
    name: str

    def generate(self, capability: Capability, text: str) -> StructuredResult: ...


class ModelRouter:
    """Capability routing with explicit fallback; providers never receive publish authority."""

    def __init__(self, routes: dict[Capability, list[ModelProvider]]) -> None:
        self.routes = routes

    def generate(self, capability: Capability, text: str) -> StructuredResult:
        if not text.strip():
            raise ValueError("model input cannot be empty")
        failures: list[str] = []
        for provider in self.routes.get(capability, []):
            try:
                return provider.generate(capability, text)
            except ModelUnavailable as exc:
                failures.append(f"{provider.name}: {exc}")
        raise ModelUnavailable("; ".join(failures) or f"no provider configured for {capability}")
