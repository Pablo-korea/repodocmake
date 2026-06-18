"""LLM provider abstraction built on LiteLLM.

One interface, many backends. Switching provider is a single env var
(`DOCFORGEAI_LLM_PROVIDER`) with no code change — anthropic | openai | gemini |
ollama | openrouter | enterprise-gateway. The openrouter and enterprise-gateway
slots both route to an OpenAI-compatible endpoint.
"""
from __future__ import annotations

import os

# Default model per provider. Override with DOCFORGEAI_LLM_MODEL.
_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "gemini": "gemini/gemini-2.5-flash",
    "ollama": "ollama/llama3",
    "openrouter": "anthropic/claude-sonnet-4",  # OpenRouter model id (OpenAI-compatible)
    "enterprise-gateway": "openai/internal-default",
}

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class LLMClient:
    """Thin wrapper around litellm.completion with a no-network mock mode."""

    def __init__(self, provider: str, model: str | None = None, *, mock: bool = False):
        self.provider = provider
        self.model = (
            model
            or os.environ.get("DOCFORGEAI_LLM_MODEL")
            or _DEFAULT_MODELS.get(provider, "claude-sonnet-4-6")
        )
        self.mock = mock or os.environ.get("DOCFORGEAI_MOCK_LLM") == "1"

    def complete(self, system: str, user: str) -> str:
        if self.mock:
            return self._mock_response(user)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        if self.provider == "openrouter":
            return self._complete_openai_compatible(messages)

        import litellm  # imported lazily so --dry-run works without the dep

        kwargs: dict = {}
        if self.provider == "enterprise-gateway":
            kwargs["api_base"] = os.environ["DOCFORGEAI_GATEWAY_URL"]
            kwargs["api_key"] = os.environ.get("DOCFORGEAI_GATEWAY_API_KEY", "")

        resp = litellm.completion(
            model=self.model,
            messages=messages,
            temperature=0.2,
            **kwargs,
        )
        return resp["choices"][0]["message"]["content"]

    def _complete_openai_compatible(self, messages: list[dict]) -> str:
        """Call OpenRouter directly via the OpenAI SDK.

        OpenRouter is fully OpenAI-compatible, and calling it directly avoids
        litellm mis-routing a passthrough model id like `anthropic/...` to a
        native provider. The model id is sent to OpenRouter verbatim.
        """
        from openai import OpenAI

        client = OpenAI(
            base_url=_OPENROUTER_BASE,
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        )
        resp = client.chat.completions.create(
            model=self.model.removeprefix("openrouter/"),
            messages=messages,
            temperature=0.2,
        )
        return resp.choices[0].message.content

    @staticmethod
    def _mock_response(user: str) -> str:
        # Deterministic stub so the pipeline, tests and --dry-run run offline.
        return f"<!-- mock LLM output -->\n\n{user[:200]}\n"


def get_client(provider: str, model: str | None = None, *, mock: bool = False) -> LLMClient:
    return LLMClient(provider, model, mock=mock)
