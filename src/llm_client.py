"""Gemini and DeepSeek HTTP adapters; defaults live in config/api.json."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import requests

from settings import load_api_settings, load_environment

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Lỗi khi cả engine chính và fallback đều thất bại."""


@dataclass
class LLMResponse:
    text: str
    engine: str  # "gemini" | "deepseek"
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    model: Optional[str] = None


class LLMClient:
    """Gọi Gemini trước; nếu lỗi/429/thiếu key thì fallback DeepSeek.

    Engine có thể override qua biến môi trường LLM_ENGINE=gemini|deepseek để
    test hoặc ép dùng 1 engine cụ thể.
    """

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        deepseek_api_key: Optional[str] = None,
        forced_engine: Optional[str] = None,
        timeout_s: Optional[int] = None,
    ) -> None:
        load_environment()
        self.config = load_api_settings()
        self.gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
        self.deepseek_api_key = deepseek_api_key or os.environ.get(
            "DEEPSEEK_API_KEY"
        )
        self.forced_engine = forced_engine or self.config["engine"]
        if self.forced_engine not in ("auto", "gemini", "deepseek"):
            raise ValueError("Engine phải là auto, gemini hoặc deepseek")
        self.timeout_s = timeout_s if timeout_s is not None else self.config["timeout_seconds"]

    def generate(self, prompt: str, system: Optional[str] = None) -> LLMResponse:
        """Sinh text từ prompt. Thử Gemini trước, fallback DeepSeek khi cần.

        Raises:
            LLMError: khi không có engine nào khả dụng/thành công.
        """
        engines_to_try = self._engine_order()
        last_error: Optional[Exception] = None

        for engine in engines_to_try:
            try:
                if engine == "gemini":
                    return self._call_gemini(prompt, system)
                if engine == "deepseek":
                    return self._call_deepseek(prompt, system)
            except Exception as exc:  # noqa: BLE001 - muốn bắt mọi lỗi để fallback
                logger.warning("LLM engine %s thất bại: %s", engine, exc)
                last_error = exc
                continue

        raise LLMError(
            f"Tất cả LLM engine đều thất bại (đã thử: {engines_to_try}). "
            f"Lỗi cuối: {last_error}"
        )

    def _engine_order(self) -> list[str]:
        if self.forced_engine in ("gemini", "deepseek"):
            return [self.forced_engine]
        order = []
        if self.gemini_api_key:
            order.append("gemini")
        if self.deepseek_api_key:
            order.append("deepseek")
        return order

    def _call_gemini(self, prompt: str, system: Optional[str]) -> LLMResponse:
        if not self.gemini_api_key:
            raise LLMError("Thiếu GEMINI_API_KEY")

        provider = self.config["providers"]["gemini"]
        models = [provider["model"], *provider.get("fallback_models", [])]
        for model in models:
            try:
                response = self._call_gemini_model(prompt, system, model)
                logger.info("Gemini model thành công: %s", model)
                return response
            except (requests.RequestException, LLMError, ValueError, TypeError) as exc:
                # Log the failure type, not exception URLs that may contain a key.
                logger.warning("Gemini model %s thất bại (%s)", model, type(exc).__name__)
        raise LLMError(f"Không gọi được các model Gemini: {', '.join(models)}")

    def _call_gemini_model(self, prompt: str, system: Optional[str], model: str) -> LLMResponse:
        provider = self.config["providers"]["gemini"]
        url = provider["endpoint"].format(model=model)
        contents = [{"role": "user", "parts": [{"text": prompt}]}]

        payload: dict = {
            "contents": contents,
            "generationConfig": {"temperature": self.config["temperature"]},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        resp = requests.post(
            url,
            params={"key": self.gemini_api_key},
            json=payload,
            timeout=self.timeout_s,
        )
        if resp.status_code == 429:
            raise LLMError("Gemini rate-limited (429)")
        resp.raise_for_status()
        data = resp.json()

        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        except (KeyError, IndexError) as exc:
            raise LLMError("Gemini response không đúng format") from exc
        if not text.strip():
            raise LLMError("Gemini trả nội dung rỗng")

        usage = data.get("usageMetadata", {})
        return LLMResponse(
            text=text,
            engine="gemini",
            model=model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )

    def _call_deepseek(self, prompt: str, system: Optional[str]) -> LLMResponse:
        if not self.deepseek_api_key:
            raise LLMError("Thiếu DEEPSEEK_API_KEY")

        headers = {
            "x-api-key": self.deepseek_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.config["providers"]["deepseek"]["model"],
            "max_tokens": self.config["max_tokens"],
            "temperature": self.config["temperature"],
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        resp = requests.post(
            self.config["providers"]["deepseek"]["endpoint"], headers=headers, json=payload, timeout=self.timeout_s
        )
        if resp.status_code == 429:
            raise LLMError("DeepSeek rate-limited (429)")
        resp.raise_for_status()
        data = resp.json()

        try:
            text = "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            )
        except (KeyError, IndexError) as exc:
            raise LLMError(f"DeepSeek response không đúng format: {data}") from exc

        usage = data.get("usage", {})
        return LLMResponse(
            text=text,
            engine="deepseek",
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )


if __name__ == "__main__":
    # Smoke test thủ công, không chạy trong CI bước 1.
    logging.basicConfig(level=logging.INFO)
    client = LLMClient()
    if not client._engine_order():
        print("Không có API key nào trong env (GEMINI_API_KEY/DEEPSEEK_API_KEY).")
    else:
        t0 = time.time()
        res = client.generate("Nói 'xin chào' bằng tiếng Việt, ngắn gọn.")
        print(f"[{res.engine}] {res.text} ({time.time() - t0:.1f}s)")
