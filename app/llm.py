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


class ClaudeCliLlm:
    """    本地 claude CLI 作为纯 LLM 后端。

    ⚠️ 关键隔离（2026-08-22 实测发现的真 bug）：claude CLI 不是纯 LLM，
    它是带工具和项目上下文的 agent——在项目目录里跑会读到 CLAUDE.md 和源码，
    导致它"知道"自己在哪个仓库里，污染回答（实测：agent 会反问"要我从项目里提取数据吗"）。
    三重隔离：① cwd 指向空沙箱目录 ② --allowedTools "" 禁用全部工具
    ③ prompt 走 stdin（变参 flag 会吞掉位置参数）。

    引擎是同步的，用 subprocess.run 阻塞调用即可
    （LangGraph 会把同一超步里的独立节点放线程池并行执行）。
    """

    def __init__(self, model: str = "haiku", timeout: int = 180) -> None:
        self._model = model
        self._timeout = timeout

    def chat(self, system: str, user: str) -> str:
        import subprocess
        import tempfile
        from pathlib import Path

        sandbox = Path(tempfile.gettempdir()) / "claude-llm-sandbox"
        sandbox.mkdir(exist_ok=True)
        r = subprocess.run(
            ["claude", "-p", "--model", self._model,
             "--allowedTools", "", "--append-system-prompt", system],
            input=user, capture_output=True, text=True,
            timeout=self._timeout, cwd=sandbox,
        )
        if r.returncode != 0:
            raise RuntimeError(f"claude CLI 失败: {r.stderr[:200]}")
        return r.stdout.strip()
