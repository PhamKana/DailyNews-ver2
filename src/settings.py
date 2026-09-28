"""Shared API defaults and local environment loading (environment wins)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_environment(root: Path = REPO_ROOT) -> None:
    """Load canonical config/.env, then legacy root .env without overwriting."""
    load_dotenv(root / "config" / ".env", override=False)
    load_dotenv(root / ".env", override=False)


def load_api_settings() -> dict:
    with (REPO_ROOT / "config" / "api.json").open(encoding="utf-8") as file:
        config = json.load(file)
    config["engine"] = os.getenv("LLM_ENGINE") or config["engine"]
    if config["engine"] not in ("auto", "gemini", "deepseek"):
        raise ValueError("LLM_ENGINE phải là auto, gemini hoặc deepseek")
    config["temperature"] = float(os.getenv("LLM_TEMPERATURE") or config["temperature"])
    for name, provider in config["providers"].items():
        prefix = name.upper()
        provider["model"] = os.getenv(f"{prefix}_MODEL") or provider["model"]
        provider["endpoint"] = os.getenv(f"{prefix}_ENDPOINT") or provider["endpoint"]
    gemini = config["providers"]["gemini"]
    fallback_override = os.getenv("GEMINI_FALLBACK_MODELS")
    if fallback_override is not None:
        gemini["fallback_models"] = [m.strip() for m in fallback_override.split(",") if m.strip()]
    elif os.getenv("GEMINI_MODEL"):
        # An explicit single-model override must not silently try other models.
        gemini["fallback_models"] = []
    fallbacks = gemini.get("fallback_models", [])
    if not isinstance(fallbacks, list) or not all(isinstance(m, str) and m.strip() for m in fallbacks):
        raise ValueError("Gemini fallback_models phải là danh sách tên model")
    gemini["fallback_models"] = list(dict.fromkeys(m.strip() for m in fallbacks if m.strip() != gemini["model"]))
    return config
