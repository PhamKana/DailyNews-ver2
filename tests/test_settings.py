"""Configuration precedence and HTTP adapter regression tests, no real API calls."""

import os
from unittest.mock import Mock

import pytest

import llm_client
from llm_client import LLMClient, LLMError
from settings import load_api_settings, load_environment


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("GEMINI_", "DEEPSEEK_", "LLM_")):
            monkeypatch.delenv(name)
    monkeypatch.setattr(llm_client, "load_environment", lambda: None)


def test_env_precedence_and_legacy_fallback(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/.env").write_text("GEMINI_API_KEY=canonical\nLLM_ENGINE=deepseek\n")
    (tmp_path / ".env").write_text("GEMINI_API_KEY=legacy\nDEEPSEEK_API_KEY=legacy\n")
    monkeypatch.setenv("LLM_ENGINE", "gemini")
    # Track additions from dotenv so pytest restores them too.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    load_environment(tmp_path)
    assert os.environ["GEMINI_API_KEY"] == "canonical"
    assert os.environ["DEEPSEEK_API_KEY"] == "legacy"
    assert os.environ["LLM_ENGINE"] == "gemini"


def test_settings_overrides(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    config = load_api_settings()
    assert config["providers"]["gemini"]["model"] == "custom-model"
    assert config["temperature"] == 0


def test_invalid_engine_fails_clearly(monkeypatch):
    monkeypatch.setenv("LLM_ENGINE", "typo")
    with pytest.raises(ValueError, match="LLM_ENGINE"):
        LLMClient()


def test_gemini_uses_configured_endpoint_and_model(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "custom")
    monkeypatch.setenv("GEMINI_ENDPOINT", "https://example.test/{model}")
    response = Mock(status_code=200)
    response.json.return_value = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(llm_client.requests, "post", post)
    assert LLMClient(gemini_api_key="fake").generate("hello").text == "ok"
    assert post.call_args.args[0] == "https://example.test/custom"
    assert post.call_args.kwargs["params"] == {"key": "fake"}


def test_fallback_preserves_deepseek_protocol(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "custom-deepseek")
    monkeypatch.setenv("DEEPSEEK_ENDPOINT", "https://example.test/messages")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    limited = Mock(status_code=429)
    success = Mock(status_code=200)
    success.json.return_value = {"content": [{"type": "text", "text": "fallback"}]}
    post = Mock(side_effect=[limited, success])
    monkeypatch.setattr(llm_client.requests, "post", post)
    result = LLMClient(gemini_api_key="fake-g", deepseek_api_key="fake-d", forced_engine="auto").generate("hello")
    assert result.engine == "deepseek"
    assert result.text == "fallback"
    assert post.call_args.args[0] == "https://example.test/messages"
    assert post.call_args.kwargs["json"]["model"] == "custom-deepseek"
    assert post.call_args.kwargs["headers"]["x-api-key"] == "fake-d"


def test_forced_engine_never_uses_other_provider(monkeypatch):
    post = Mock()
    monkeypatch.setattr(llm_client.requests, "post", post)
    with pytest.raises(LLMError):
        LLMClient(gemini_api_key="fake", forced_engine="deepseek").generate("hello")
    post.assert_not_called()


def test_default_does_not_spend_deepseek_on_gemini_failure(monkeypatch):
    limited = Mock(status_code=429)
    post = Mock(return_value=limited)
    monkeypatch.setattr(llm_client.requests, "post", post)
    with pytest.raises(LLMError):
        LLMClient(gemini_api_key="fake-g", deepseek_api_key="fake-d").generate("hello")
    assert post.call_count == 3
    assert all("generativelanguage.googleapis.com" in call.args[0] for call in post.call_args_list)


@pytest.mark.parametrize("failures", [0, 1, 2])
def test_gemini_fallback_order_and_stop_after_success(monkeypatch, failures):
    limited = Mock(status_code=429)
    success = Mock(status_code=200)
    success.json.return_value = {"candidates": [{"content": {"parts": [
        {"text": "internal", "thought": True}, {"text": "answer"}, {"text": " complete"}
    ]}}]}
    post = Mock(side_effect=[limited] * failures + [success])
    monkeypatch.setattr(llm_client.requests, "post", post)
    result = LLMClient(gemini_api_key="fake").generate("hello")
    models = ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
    assert result.model == models[failures]
    assert result.text == "answer complete"
    assert post.call_count == failures + 1
    for call, model in zip(post.call_args_list, models):
        assert f"/{model}:generateContent" in call.args[0]


def test_model_override_and_explicit_fallbacks(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "custom")
    assert load_api_settings()["providers"]["gemini"]["fallback_models"] == []
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", " backup, custom, backup, last ")
    assert load_api_settings()["providers"]["gemini"]["fallback_models"] == ["backup", "last"]


def test_gemini_falls_back_on_empty_content(monkeypatch):
    empty = Mock(status_code=200)
    empty.json.return_value = {"candidates": [{"content": {"parts": []}}]}
    success = Mock(status_code=200)
    success.json.return_value = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    post = Mock(side_effect=[empty, success])
    monkeypatch.setattr(llm_client.requests, "post", post)
    assert LLMClient(gemini_api_key="fake").generate("hello").model == "gemini-2.5-flash"
