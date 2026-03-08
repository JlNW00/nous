"""Tests for the unified reasoning_core module."""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock

from packages.common.reasoning_core import (
    call_reasoning_service,
    _parse_llm_response,
    _call_ollama,
    _call_anthropic,
    NOUS_SYSTEM_PROMPT,
    INVESTIGATION_SYSTEM_PROMPT,
)


class TestParseLLMResponse:
    """Test JSON parsing from LLM responses."""

    def test_parse_plain_json(self):
        """Test parsing plain JSON without markdown."""
        raw = '{"summary": "test", "confidence": 0.8}'
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["summary"] == "test"
        assert result["confidence"] == 0.8

    def test_parse_json_with_markdown_fences(self):
        """Test parsing JSON wrapped in markdown code fences."""
        raw = '```json\n{"summary": "test", "confidence": 0.8}\n```'
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["summary"] == "test"

    def test_parse_json_with_markdown_fences_no_lang(self):
        """Test parsing JSON in markdown without 'json' language specifier."""
        raw = '```\n{"summary": "test", "confidence": 0.8}\n```'
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["summary"] == "test"

    def test_parse_invalid_json(self):
        """Test that invalid JSON returns None."""
        raw = "not valid json"
        result = _parse_llm_response(raw)
        assert result is None

    def test_parse_empty_string(self):
        """Test that empty string returns None."""
        result = _parse_llm_response("")
        assert result is None

    def test_parse_none_returns_none(self):
        """Test that None returns None."""
        result = _parse_llm_response(None)
        assert result is None

    def test_parse_complex_json_structure(self):
        """Test parsing complex JSON with multiple fields."""
        raw = json.dumps({
            "summary": "Test summary",
            "supporting_findings": ["Finding 1", "Finding 2"],
            "contradictions": ["Contradiction 1"],
            "open_questions": ["Question 1"],
            "verdict_suggestion": "suspicious",
            "confidence": 0.75,
        })
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["summary"] == "Test summary"
        assert len(result["supporting_findings"]) == 2
        assert result["verdict_suggestion"] == "suspicious"


class TestCallOllama:
    """Test Ollama reasoning service."""

    @patch("packages.common.reasoning_core.httpx.Client")
    def test_ollama_success(self, mock_client_class):
        """Test successful Ollama call."""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        # Mock models response
        models_response = Mock()
        models_response.json.return_value = {
            "models": [
                {"name": "mistral"},
                {"name": "llama3:8b"},
            ]
        }

        # Mock generate response
        generate_response = Mock()
        generate_response.json.return_value = {
            "response": '{"summary": "test", "confidence": 0.8}'
        }

        mock_client.get.return_value = models_response
        mock_client.post.return_value = generate_response

        result = _call_ollama(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test evidence",
            system_prompt="test prompt",
        )

        assert result is not None
        assert result["summary"] == "test"

    @patch("packages.common.reasoning_core.httpx.Client")
    def test_ollama_connection_error(self, mock_client_class):
        """Test graceful handling of Ollama connection error."""
        mock_client_class.return_value.__enter__.side_effect = Exception(
            "Connection refused"
        )

        result = _call_ollama(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test evidence",
            system_prompt="test prompt",
        )

        assert result is None

    @patch("packages.common.reasoning_core.httpx.Client")
    def test_ollama_no_models_available(self, mock_client_class):
        """Test graceful handling when no Ollama models available."""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        # Mock models response with empty list
        models_response = Mock()
        models_response.json.return_value = {"models": []}

        mock_client.get.return_value = models_response

        result = _call_ollama(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test evidence",
            system_prompt="test prompt",
        )

        assert result is None

    @patch("packages.common.reasoning_core.httpx.Client")
    def test_ollama_empty_response(self, mock_client_class):
        """Test handling of empty response from Ollama."""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        # Mock models response
        models_response = Mock()
        models_response.json.return_value = {
            "models": [{"name": "mistral"}]
        }

        # Mock generate response with empty text
        generate_response = Mock()
        generate_response.json.return_value = {"response": ""}

        mock_client.get.return_value = models_response
        mock_client.post.return_value = generate_response

        result = _call_ollama(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test evidence",
            system_prompt="test prompt",
        )

        assert result is None


class TestCallAnthropic:
    """Test Anthropic API reasoning service."""

    @patch("packages.common.reasoning_core.anthropic.Anthropic")
    @patch("packages.common.reasoning_core.settings")
    def test_anthropic_success(self, mock_settings, mock_anthropic_class):
        """Test successful Anthropic API call."""
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.llm_model = "claude-opus-4.6"

        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client

        # Mock response
        mock_message = Mock()
        mock_message.text = '{"summary": "test", "confidence": 0.9}'
        mock_response = Mock()
        mock_response.content = [mock_message]

        mock_client.messages.create.return_value = mock_response

        result = _call_anthropic(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test evidence",
            system_prompt="test prompt",
        )

        assert result is not None
        assert result["summary"] == "test"
        assert result["confidence"] == 0.9

    @patch("packages.common.reasoning_core.settings")
    def test_anthropic_no_api_key(self, mock_settings):
        """Test graceful handling when no API key configured."""
        mock_settings.anthropic_api_key = None

        result = _call_anthropic(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test evidence",
            system_prompt="test prompt",
        )

        assert result is None

    @patch("packages.common.reasoning_core.anthropic.Anthropic")
    @patch("packages.common.reasoning_core.settings")
    def test_anthropic_api_error(self, mock_settings, mock_anthropic_class):
        """Test graceful handling of Anthropic API errors."""
        mock_settings.anthropic_api_key = "test-key"
        mock_anthropic_class.side_effect = Exception("API Error")

        result = _call_anthropic(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test evidence",
            system_prompt="test prompt",
        )

        assert result is None


class TestCallReasoningService:
    """Test unified reasoning service."""

    @patch("packages.common.reasoning_core._call_ollama")
    @patch("packages.common.reasoning_core._call_anthropic")
    def test_ollama_called_first(self, mock_anthropic, mock_ollama):
        """Test that Ollama is tried before Anthropic."""
        mock_ollama.return_value = {"summary": "ollama result", "confidence": 0.8}
        mock_anthropic.return_value = {"summary": "anthropic result", "confidence": 0.9}

        result = call_reasoning_service(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test",
        )

        assert result is not None
        assert result["summary"] == "ollama result"
        # Anthropic should not have been called
        mock_anthropic.assert_not_called()

    @patch("packages.common.reasoning_core._call_ollama")
    @patch("packages.common.reasoning_core._call_anthropic")
    def test_fallback_to_anthropic(self, mock_anthropic, mock_ollama):
        """Test fallback to Anthropic when Ollama unavailable."""
        mock_ollama.return_value = None
        mock_anthropic.return_value = {"summary": "anthropic result", "confidence": 0.9}

        result = call_reasoning_service(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test",
        )

        assert result is not None
        assert result["summary"] == "anthropic result"
        mock_ollama.assert_called_once()
        mock_anthropic.assert_called_once()

    @patch("packages.common.reasoning_core._call_ollama")
    @patch("packages.common.reasoning_core._call_anthropic")
    def test_both_services_unavailable(self, mock_anthropic, mock_ollama):
        """Test graceful handling when both services unavailable."""
        mock_ollama.return_value = None
        mock_anthropic.return_value = None

        result = call_reasoning_service(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test",
        )

        assert result is None

    @patch("packages.common.reasoning_core._call_ollama")
    def test_custom_system_prompt(self, mock_ollama):
        """Test that custom system prompt is passed to Ollama."""
        mock_ollama.return_value = {"summary": "test", "confidence": 0.8}
        custom_prompt = "Custom system prompt"

        call_reasoning_service(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test",
            system_prompt=custom_prompt,
        )

        # Verify custom prompt was passed
        mock_ollama.assert_called_once()
        call_kwargs = mock_ollama.call_args[1]
        assert call_kwargs["system_prompt"] == custom_prompt

    @patch("packages.common.reasoning_core._call_ollama")
    def test_default_nous_prompt(self, mock_ollama):
        """Test that NOUS prompt is used by default."""
        mock_ollama.return_value = {"summary": "test", "confidence": 0.8}

        call_reasoning_service(
            project_json='{"name": "Test"}',
            signals_json='[]',
            evidence_summary="test",
        )

        # Verify NOUS prompt was used
        mock_ollama.assert_called_once()
        call_kwargs = mock_ollama.call_args[1]
        assert call_kwargs["system_prompt"] == NOUS_SYSTEM_PROMPT


class TestSystemPrompts:
    """Test system prompt constants."""

    def test_nous_prompt_exists(self):
        """Test NOUS system prompt is defined."""
        assert NOUS_SYSTEM_PROMPT is not None
        assert len(NOUS_SYSTEM_PROMPT) > 0
        assert "NOUS" in NOUS_SYSTEM_PROMPT
        assert "clinical" in NOUS_SYSTEM_PROMPT

    def test_investigation_prompt_exists(self):
        """Test INVESTIGATION system prompt is defined."""
        assert INVESTIGATION_SYSTEM_PROMPT is not None
        assert len(INVESTIGATION_SYSTEM_PROMPT) > 0
        assert "investigation" in INVESTIGATION_SYSTEM_PROMPT.lower()

    def test_prompts_are_different(self):
        """Test that NOUS and INVESTIGATION prompts are different."""
        assert NOUS_SYSTEM_PROMPT != INVESTIGATION_SYSTEM_PROMPT
