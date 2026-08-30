"""OpenAI 兼容适配层：httpx 直连 {base_url}/chat/completions，不绑定任何 SDK。

兼容 OpenAI / DeepSeek / 智谱 / Kimi / Ollama(openai 兼容端点) 等第三方。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx


class AIError(Exception):
    """AI 调用失败。kind: auth / rate_limit / timeout / bad_request / server / network / parse"""

    def __init__(self, message: str, kind: str = "server"):
        super().__init__(message)
        self.kind = kind


@dataclass
class ChatMessage:
    role: str  # system / user / assistant
    content: str


def _base_url(cfg: dict) -> str:
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise AIError("base_url 未配置", "bad_request")
    if not base.endswith("/v1") and "/v1" not in base.split("//")[-1]:
        # 习惯上用户填 https://api.deepseek.com 即可用；填了 /v1 也兼容
        base = base + "/v1"
    return base


def _headers(cfg: dict) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    key = cfg.get("api_key") or ""
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def chat(cfg: dict, messages: list[ChatMessage], *, temperature: float = 0.7,
         timeout: float = 90.0) -> str:
    """非流式对话，返回首条回复文本。"""
    url = _base_url(cfg) + "/chat/completions"
    payload = {
        "model": cfg.get("model", ""),
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "temperature": temperature,
        "stream": False,
    }
    try:
        resp = httpx.post(url, headers=_headers(cfg), json=payload, timeout=timeout)
    except httpx.TimeoutException as e:
        raise AIError(f"AI 请求超时（{timeout}s）", "timeout") from e
    except httpx.HTTPError as e:
        raise AIError(f"AI 网络错误: {e}", "network") from e

    if resp.status_code in (401, 403):
        raise AIError(f"鉴权失败（HTTP {resp.status_code}），检查 api_key", "auth")
    if resp.status_code == 429:
        raise AIError("触发限速（HTTP 429），稍后重试", "rate_limit")
    if resp.status_code >= 400:
        raise AIError(f"AI 请求失败 HTTP {resp.status_code}: {resp.text[:200]}", "bad_request")
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""
    except Exception as e:
        raise AIError(f"AI 响应格式无法解析: {resp.text[:200]}", "parse") from e


def chat_stream(cfg: dict, messages: list[ChatMessage], *, temperature: float = 0.7,
                timeout: float = 120.0):
    """流式对话：yield 增量文本（SSE data: 行解析）。"""
    url = _base_url(cfg) + "/chat/completions"
    payload = {
        "model": cfg.get("model", ""),
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "temperature": temperature,
        "stream": True,
    }
    try:
        with httpx.stream("POST", url, headers=_headers(cfg), json=payload, timeout=timeout) as resp:
            if resp.status_code in (401, 403):
                raise AIError(f"鉴权失败（HTTP {resp.status_code}），检查 api_key", "auth")
            if resp.status_code == 429:
                raise AIError("触发限速（HTTP 429）", "rate_limit")
            if resp.status_code >= 400:
                raise AIError(f"AI 请求失败 HTTP {resp.status_code}", "bad_request")
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {}).get("content")
                except Exception:
                    continue
                if delta:
                    yield delta
    except httpx.TimeoutException as e:
        raise AIError("AI 流式请求超时", "timeout") from e
    except httpx.HTTPError as e:
        raise AIError(f"AI 网络错误: {e}", "network") from e


def list_models(cfg: dict, timeout: float = 15.0) -> list[str]:
    """探测 {base_url}/models（部分服务可能不支持，失败返回空表）。"""
    url = _base_url(cfg) + "/models"
    try:
        resp = httpx.get(url, headers=_headers(cfg), timeout=timeout)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


def extract_json(text: str) -> dict:
    """从模型回复中提取 JSON 对象（容忍 ```json 包裹与前后杂文）。"""
    if not text:
        raise AIError("AI 返回为空", "parse")
    s = text.strip()
    if "```" in s:
        for part in s.split("```"):
            p = part.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                s = p
                break
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1:
        raise AIError(f"AI 未返回 JSON: {s[:120]}", "parse")
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError as e:
        raise AIError(f"JSON 解析失败: {e}", "parse") from e
