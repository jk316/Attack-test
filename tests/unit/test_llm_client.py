"""Unit tests for src/llm/client.py — DeepSeek API client wrapper."""
import json
from unittest.mock import MagicMock, patch

import openai
import pytest

from src.llm.client import LLMClient, LLMClientError


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_api_key() -> str:
    return "sk-test-fake-key"


@pytest.fixture
def sample_response() -> dict:
    return {
        "params": {
            "dst_port": 8080,
            "duration_s": 5,
            "pps": 80,
            "packet_size": 128,
            "flow_count": 2,
            "iat_jitter_ms": 5,
        },
        "reasoning": "Increasing pps and flow_count based on positive RTT trend",
    }


# ── TestLLMClientInit ───────────────────────────────────────────────────────

class TestLLMClientInit:
    def test_raises_when_no_api_key(self, monkeypatch):
        """Should raise LLMClientError when DEEPSEEK_API_KEY is not set."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with pytest.raises(LLMClientError, match="DEEPSEEK_API_KEY"):
            LLMClient()

    def test_uses_env_var(self, monkeypatch, fake_api_key):
        """Should read api_key from DEEPSEEK_API_KEY env var."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", fake_api_key)
        client = LLMClient()
        assert client._client.api_key == fake_api_key

    def test_uses_constructor_arg(self, monkeypatch, fake_api_key):
        """Constructor argument should take precedence over env var."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        client = LLMClient(api_key=fake_api_key)
        assert client._client.api_key == fake_api_key

    def test_default_model(self, monkeypatch, fake_api_key):
        """Default model should be 'deepseek-chat'."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", fake_api_key)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        client = LLMClient()
        assert client._model == "deepseek-chat"

    def test_custom_model_from_env(self, monkeypatch, fake_api_key):
        """Should honour LLM_MODEL env var."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", fake_api_key)
        monkeypatch.setenv("LLM_MODEL", "deepseek-reasoner")
        client = LLMClient()
        assert client._model == "deepseek-reasoner"

    def test_custom_base_url(self, monkeypatch, fake_api_key):
        """Should use custom base_url when provided."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", fake_api_key)
        client = LLMClient(base_url="https://custom.api.com")
        assert client._client.base_url == "https://custom.api.com"


# ── TestParseJsonResponse ───────────────────────────────────────────────────

class TestParseJsonResponse:
    def test_parses_bare_json(self, sample_response):
        """Should parse a bare JSON object string."""
        content = json.dumps(sample_response)
        result = LLMClient._parse_json_response(content)
        assert result == sample_response

    def test_parses_fenced_json(self, sample_response):
        """Should extract JSON from a ```json ... ``` code block."""
        content = f"```json\n{json.dumps(sample_response)}\n```"
        result = LLMClient._parse_json_response(content)
        assert result == sample_response

    def test_parses_fenced_no_lang(self, sample_response):
        """Should extract JSON from a ``` ... ``` block without language tag."""
        content = f"```\n{json.dumps(sample_response)}\n```"
        result = LLMClient._parse_json_response(content)
        assert result == sample_response

    def test_parses_json_with_surrounding_text(self, sample_response):
        """Should find JSON amid surrounding prose."""
        content = (
            "Here is my recommendation:\n\n"
            + json.dumps(sample_response)
            + "\n\nLet me know if you have questions."
        )
        result = LLMClient._parse_json_response(content)
        assert result == sample_response

    def test_raises_on_no_braces(self):
        """Should raise LLMClientError when content has no JSON object."""
        with pytest.raises(LLMClientError, match="No JSON object found"):
            LLMClient._parse_json_response("no json here, just text")

    def test_raises_on_invalid_json(self):
        """Should raise LLMClientError when JSON is malformed."""
        with pytest.raises(LLMClientError, match="Failed to parse JSON"):
            LLMClient._parse_json_response('{"params": {"pps": 80,}}')

    def test_handles_nested_braces(self):
        """Should correctly identify the outermost JSON object with nested braces."""
        content = '{"outer": {"inner": {"key": "value"}}}'
        result = LLMClient._parse_json_response(content)
        assert result == {"outer": {"inner": {"key": "value"}}}

    def test_handles_json_array_root_ignored(self):
        """JSON arrays at root are not objects; should look for brace later."""
        content = '[1, 2, 3] {"valid": "object"}'
        result = LLMClient._parse_json_response(content)
        assert result == {"valid": "object"}

    def test_handles_empty_string(self):
        """Empty string should raise."""
        with pytest.raises(LLMClientError, match="No JSON object found"):
            LLMClient._parse_json_response("")


# ── TestChat ─────────────────────────────────────────────────────────────────

class TestChat:
    def test_chat_success(self, monkeypatch, fake_api_key, sample_response):
        """chat() should send messages, parse the response JSON, and return it."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", fake_api_key)
        client = LLMClient()

        # Build a fake OpenAI response
        fake_message = MagicMock()
        fake_message.content = json.dumps(sample_response)
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]

        with patch.object(
            client._client.chat.completions, "create", return_value=fake_completion
        ) as mock_create:
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Return JSON."},
            ]
            result = client.chat(messages)

        assert result == sample_response
        mock_create.assert_called_once_with(
            model="deepseek-chat",
            messages=messages,
        )

    def test_chat_api_error(self, monkeypatch, fake_api_key):
        """chat() should wrap OpenAIError in LLMClientError."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", fake_api_key)
        client = LLMClient()

        mock_request = MagicMock()
        with patch.object(
            client._client.chat.completions,
            "create",
            side_effect=openai.APIError("timeout", request=mock_request, body=None),
        ):
            with pytest.raises(LLMClientError, match="DeepSeek API call failed"):
                client.chat([{"role": "user", "content": "hi"}])

    def test_chat_empty_content(self, monkeypatch, fake_api_key):
        """chat() should raise when the model returns empty content."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", fake_api_key)
        client = LLMClient()

        fake_message = MagicMock()
        fake_message.content = ""
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]

        with patch.object(
            client._client.chat.completions, "create", return_value=fake_completion
        ):
            with pytest.raises(LLMClientError, match="No JSON object found"):
                client.chat([{"role": "user", "content": "hi"}])
