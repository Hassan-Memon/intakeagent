"""Tiny LLM provider abstraction.

Every backend we support speaks the OpenAI chat-completions dialect, so one ``ChatOpenAI``
with a different ``base_url`` covers OpenInfer, Ollama, Groq, Gemini and OpenRouter. The
important bit for a PHI product is the ``is_local`` flag: the graph only skips redaction when
the provider is local, and the ``private`` tag tells an OpenInfer router to never route the
request to a cloud backend.

Resolution order for ``LLM_PROVIDER=auto``: OpenInfer if configured, then Ollama if it answers
on the network, then Groq if a key exists, then the stub (rule-based extractor).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from intakeagent.config import Settings


@dataclass(frozen=True)
class LLMChoice:
    provider: str
    base_url: str | None
    api_key: str
    model: str
    is_local: bool
    extra_body: dict[str, Any] | None = None

    @property
    def is_stub(self) -> bool:
        return self.provider == "stub"


def _ollama_reachable(base_url: str) -> bool:
    try:
        r = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=0.6)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def resolve_provider(settings: Settings) -> LLMChoice:
    stub = LLMChoice("stub", None, "", "rules", True)
    if settings.demo_mode:
        return stub

    choice = settings.llm_provider
    if choice == "auto":
        if settings.openinfer_base_url:
            choice = "openinfer"
        elif _ollama_reachable(settings.ollama_base_url):
            choice = "ollama"
        elif settings.groq_api_key:
            choice = "groq"
        else:
            return stub

    if choice == "openinfer":
        return LLMChoice(
            "openinfer",
            settings.openinfer_base_url.rstrip("/"),
            settings.openinfer_api_key or "openinfer",
            settings.llm_model,
            is_local=True,
            # OpenInfer reads request tags; "private" pins the request to local hardware.
            extra_body={"tags": ["private"]},
        )
    if choice == "ollama":
        return LLMChoice(
            "ollama",
            f"{settings.ollama_base_url.rstrip('/')}/v1",
            "ollama",
            settings.llm_model,
            is_local=True,
        )
    if choice == "groq":
        return LLMChoice(
            "groq",
            "https://api.groq.com/openai/v1",
            settings.groq_api_key,
            settings.llm_model,
            is_local=False,
        )
    if choice == "gemini":
        return LLMChoice(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            settings.gemini_api_key,
            settings.llm_model or "gemini-2.0-flash",
            is_local=False,
        )
    if choice == "openrouter":
        return LLMChoice(
            "openrouter",
            "https://openrouter.ai/api/v1",
            settings.openrouter_api_key,
            settings.llm_model,
            is_local=False,
        )
    return stub


def get_chat_model(choice: LLMChoice):
    """Build a LangChain chat model for a resolved choice (None for the stub)."""
    if choice.is_stub:
        return None
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": choice.model,
        "base_url": choice.base_url,
        "api_key": choice.api_key,
        "temperature": 0,
        "timeout": 60,
    }
    if choice.extra_body:
        kwargs["extra_body"] = choice.extra_body
        kwargs["default_headers"] = {"X-OpenInfer-Tags": ",".join(choice.extra_body["tags"])}
    return ChatOpenAI(**kwargs)
