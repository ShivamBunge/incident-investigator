"""LLM provider abstraction. v1 target: OpenRouter (OpenAI-compatible).

The orchestrator depends only on LLMProvider; swapping providers touches
nothing else (spec Section 12 maintainability).
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

import httpx
from pydantic import ValidationError

from app.config import settings

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You are an incident investigator analyzing why a service is failing.

Rules:
- Reason ONLY over the evidence provided. Never invent production state.
- Every finding (a factual claim) must cite evidence IDs from the provided evidence list.
- Hypotheses are explanations of the root cause, not facts. Label each with a
  confidence between 0.0 and 1.0. Confidence is not certainty.
- State the most likely root cause explicitly and concisely in the first
  hypothesis, naming the failure category (for example: "database connection
  pool exhaustion", "downstream dependency failure", "recent deployment
  regression").
- When the observed symptom pattern matches a retrieved runbook or postmortem
  chunk, cite that chunk's evidence ID as supporting evidence for the
  hypothesis it supports.
- Recommendations are next diagnostic steps only. Never remediation actions.
- If evidence is missing or a source was unavailable, say so explicitly in
  missing_information.
- Output STRICT JSON only, with exactly these keys:
{"summary": string, "findings": [{"statement": string, "evidence_ids": [string]}],
 "hypotheses": [{"statement": string, "confidence": number,
   "supporting_evidence_ids": [string], "contradicting_evidence_ids": [string]}],
 "recommendations": [{"statement": string, "reason": string}],
 "missing_information": [string]}"""


class LLMSynthesisError(Exception):
    """LLM synthesis could not be completed."""


class LLMProvider(ABC):
    @abstractmethod
    async def complete_json(self, system: str, user: str) -> dict: ...


class OpenRouterProvider(LLMProvider):
    """OpenAI-compatible chat completions via OpenRouter."""

    def __init__(
        self, api_key: str, base_url: str, model: str, timeout_seconds: float = 60.0
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self.last_usage: dict | None = None  # token usage from the latest call

    async def complete_json(self, system: str, user: str) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions", headers=headers, json=body
                )
                response.raise_for_status()
                data = response.json()
                self.last_usage = data.get("usage")
                content = data["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise LLMSynthesisError(f"LLM request failed: {exc}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMSynthesisError(f"unexpected LLM response shape: {exc}") from exc
        return _parse_json(content)


def _parse_json(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Tolerant fallback: extract the outermost JSON object.
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMSynthesisError("LLM returned non-JSON output")


def get_llm_provider() -> LLMProvider:
    if not settings.openrouter_api_key:
        raise LLMSynthesisError("OPENROUTER_API_KEY is not configured")
    return OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
    )


__all__ = [
    "LLMProvider",
    "LLMSynthesisError",
    "OpenRouterProvider",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "get_llm_provider",
]