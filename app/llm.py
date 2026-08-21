"""LLM 接口：与图引擎解耦。测试用 FakeLLM；生产接 DeepSeek（OpenAI 兼容）。"""

from typing import Protocol

import httpx


class LLM(Protocol):
    def chat(self, system: str, user: str) -> str: ...


class FakeLLM:
    """确定性假模型：回放预置脚本；未命中则回显任务摘要。测试与离线演示用。"""

    def __init__(self, script: dict[str, str] | None = None) -> None:
        self._script = script or {}
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        for key, reply in self._script.items():
            if key in user:
                return reply
        return f"[fake:{len(self.calls)}] " + user[:60].replace("\n", " ")


class DeepSeekLLM:
    def __init__(self, api_key: str, model: str = "deepseek-chat",
                 base_url: str = "https://api.deepseek.com") -> None:
        self._key, self._model, self._base = api_key, model, base_url

    def chat(self, system: str, user: str) -> str:
        r = httpx.post(
            f"{self._base}/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""
