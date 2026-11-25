"""模型設定載入與覆寫模組（支援快速切換不同地端模型與引擎）。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VALID_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "max"}
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "models.json"


@dataclass(frozen=True)
class ModelProfile:
    name: str
    base_url: str
    health_url: str
    model: str
    api_key: str = ""
    default_reasoning_effort: str | None = None
    supports_reasoning_effort: bool = True
    timeout_sec: int = 120
    description: str = ""


def load_model_profile(
    profile_name: str | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    *,
    base_url_override: str | None = None,
    model_override: str | None = None,
    api_key_override: str | None = None,
    reasoning_effort_override: str | None = None,
) -> ModelProfile:
    """從 models.json 載入模型設定，並套用環境變數與參數覆寫。

    優先順序（高 → 低）：
      1. 函式參數 override（CLI 參數）
      2. 環境變數（LOCAL_LLM_BASE_URL / LOCAL_LLM_MODEL / LOCAL_LLM_API_KEY / LOCAL_LLM_REASONING_EFFORT）
      3. config/models.json 指定 profile
    """
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到模型設定檔：{path}")

    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    profiles: dict[str, Any] = raw.get("profiles", {})
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError(f"設定檔 {path} 缺少有效的 profiles 區塊")

    selected = profile_name or os.environ.get("LOCAL_LLM_PROFILE") or raw.get("default_profile")
    if not selected or selected not in profiles:
        available = ", ".join(sorted(profiles.keys()))
        raise KeyError(f"找不到模型 profile '{selected}'，可用選項：{available}")

    entry: dict[str, Any] = profiles[selected]

    base_url = (
        base_url_override
        or os.environ.get("LOCAL_LLM_BASE_URL")
        or str(entry.get("base_url", ""))
    ).rstrip("/")
    if not base_url:
        raise ValueError(f"profile '{selected}' 缺少 base_url")

    model = (
        model_override
        or os.environ.get("LOCAL_LLM_MODEL")
        or str(entry.get("model", ""))
    ).strip()
    if not model:
        raise ValueError(f"profile '{selected}' 缺少 model 名稱")

    api_key = (
        api_key_override
        if api_key_override is not None
        else os.environ.get("LOCAL_LLM_API_KEY", str(entry.get("api_key", "")))
    )

    health_url = str(entry.get("health_url") or f"{base_url}/models")
    if base_url_override or os.environ.get("LOCAL_LLM_BASE_URL"):
        health_url = f"{base_url}/models"

    effort = (
        reasoning_effort_override
        if reasoning_effort_override is not None
        else os.environ.get("LOCAL_LLM_REASONING_EFFORT", entry.get("default_reasoning_effort"))
    )
    if effort is not None:
        effort = str(effort).strip().lower()
        if effort and effort not in VALID_REASONING_EFFORTS:
            raise ValueError(
                f"無效的 reasoning_effort '{effort}'，允許值：{sorted(VALID_REASONING_EFFORTS)}"
            )
        if not effort:
            effort = None

    timeout_sec = int(entry.get("timeout_sec", 120))
    if timeout_sec <= 0:
        raise ValueError(f"timeout_sec 必須大於 0，目前為 {timeout_sec}")

    return ModelProfile(
        name=selected,
        base_url=base_url,
        health_url=health_url,
        model=model,
        api_key=api_key,
        default_reasoning_effort=effort,
        supports_reasoning_effort=bool(entry.get("supports_reasoning_effort", True)),
        timeout_sec=timeout_sec,
        description=str(entry.get("description", "")),
    )
