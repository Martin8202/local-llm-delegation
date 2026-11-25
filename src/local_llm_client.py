"""OpenAI 相容地端模型 HTTP Client（僅使用 Python 標準庫）。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from src.config_loader import ModelProfile, VALID_REASONING_EFFORTS


class LocalLLMError(RuntimeError):
    """地端模型呼叫失敗的基底例外。"""


class LocalLLMConnectionError(LocalLLMError):
    """無法連線至地端服務或連線逾時。"""


class LocalLLMResponseError(LocalLLMError):
    """地端服務回傳非預期狀態碼或無法解析的回應。"""


@dataclass
class LLMResponse:
    content: str
    reasoning_content: str
    model: str
    finish_reason: str
    usage: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)
    elapsed_sec: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


class LocalLLMClient:
    """透過 OpenAI 相容 API 呼叫任意地端模型（llama.cpp / Ollama / vLLM 等）。"""

    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.profile.api_key:
            headers["Authorization"] = f"Bearer {self.profile.api_key}"
        return headers

    def check_health(self, timeout: int = 5) -> dict[str, Any]:
        """檢查地端服務是否存活；若 /health 不可用則自動退回 /v1/models。"""
        urls = [self.profile.health_url]
        models_url = f"{self.profile.base_url}/models"
        if models_url not in urls:
            urls.append(models_url)

        last_err: Exception | None = None
        for url in urls:
            req = urllib.request.Request(url, headers=self._headers(), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if 200 <= resp.status < 300:
                        body = resp.read().decode("utf-8", errors="replace")
                        return {"ok": True, "url": url, "status": resp.status, "body": body}
            except Exception as exc:  # noqa: BLE001 - 統一封裝連線與 HTTP 錯誤
                last_err = exc

        raise LocalLLMConnectionError(
            f"無法連線至地端模型服務（profile={self.profile.name}, base_url={self.profile.base_url}）：{last_err}"
        ) from last_err

    def build_chat_payload(
        self,
        messages: list[dict[str, str]],
        *,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """組裝 /v1/chat/completions 請求內容並進行基本型別驗證。"""
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages 必須為非空串列")

        payload: dict[str, Any] = {
            "model": self.profile.model,
            "messages": messages,
            "stream": False,
        }

        effort = reasoning_effort if reasoning_effort is not None else self.profile.default_reasoning_effort
        if effort is not None and self.profile.supports_reasoning_effort:
            normalized = str(effort).strip().lower()
            if normalized not in VALID_REASONING_EFFORTS:
                raise ValueError(
                    f"無效的 reasoning_effort '{effort}'，允許值：{sorted(VALID_REASONING_EFFORTS)}"
                )
            payload["reasoning_effort"] = normalized

        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens is not None:
            if int(max_tokens) <= 0:
                raise ValueError("max_tokens 必須大於 0")
            payload["max_tokens"] = int(max_tokens)

        return payload

    def chat_complete(
        self,
        messages: list[dict[str, str]],
        *,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> LLMResponse:
        """發送單次對話補全請求並解析回應內容與速度指標。"""
        payload = self.build_chat_payload(
            messages,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = f"{self.profile.base_url}/chat/completions"
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")

        effective_timeout = timeout or self.profile.timeout_sec
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                raw_text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise LocalLLMResponseError(
                f"HTTP {exc.code} 錯誤（{url}）：{err_body[:500]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LocalLLMConnectionError(
                f"呼叫地端模型失敗或逾時（{url}, timeout={effective_timeout}s）：{exc}"
            ) from exc
        elapsed = time.perf_counter() - started

        try:
            parsed: dict[str, Any] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise LocalLLMResponseError(f"回應非合法 JSON：{raw_text[:300]}") from exc

        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LocalLLMResponseError(f"回應缺少 choices 欄位：{parsed}")

        first = choices[0]
        message = first.get("message") or {}
        return LLMResponse(
            content=str(message.get("content") or ""),
            reasoning_content=str(message.get("reasoning_content") or ""),
            model=str(parsed.get("model") or self.profile.model),
            finish_reason=str(first.get("finish_reason") or ""),
            usage=dict(parsed.get("usage") or {}),
            timings=dict(parsed.get("timings") or {}),
            elapsed_sec=round(elapsed, 3),
            raw=parsed,
        )
