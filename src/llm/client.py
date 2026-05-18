"""DeepSeek API client wrapper for LLM-based traffic parameter optimization."""
import json
import os
import re

import openai


class LLMClientError(Exception):
    """Raised when the LLM client encounters an unrecoverable error."""


class LLMClient:
    """Lightweight wrapper around the DeepSeek API (OpenAI-compatible).

    Reads ``DEEPSEEK_API_KEY`` from the environment; falls back to the
    ``api_key`` constructor argument.  The model is controlled by the
    ``LLM_MODEL`` env var (default ``deepseek-chat``).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise LLMClientError(
                "DEEPSEEK_API_KEY not set in environment or constructor"
            )
        self._model: str = os.environ.get("LLM_MODEL", "deepseek-chat")
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key)

    def chat(self, messages: list[dict]) -> dict:
        """Send a chat completion request and return the parsed JSON response.

        Raises:
            LLMClientError: if the API call fails or the response cannot be
                parsed as JSON.
        """
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
            )
        except openai.OpenAIError as exc:
            raise LLMClientError(f"DeepSeek API call failed: {exc}") from exc

        content = response.choices[0].message.content or ""
        return self._parse_json_response(content)

    @staticmethod
    def _parse_json_response(content: str) -> dict:
        """Extract and parse a JSON object from an LLM text response.

        Handles markdown-fenced code blocks (`` ```json ... ``` ``) and bare
        JSON objects.  Returns the parsed ``dict``.

        Raises:
            LLMClientError: if no JSON object can be extracted or parsed.
        """
        # Prefer a fenced json block
        fenced_match = re.search(
            r"```(?:json)?\s*([\s\S]*?)```", content, re.IGNORECASE
        )
        source = fenced_match.group(1) if fenced_match else content

        # Find the outermost { ... } object
        brace_match = re.search(r"\{[\s\S]*\}", source)
        if not brace_match:
            raise LLMClientError(
                f"No JSON object found in LLM response: {content[:200]}"
            )

        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMClientError(
                f"Failed to parse JSON from LLM response: {exc}"
            ) from exc
