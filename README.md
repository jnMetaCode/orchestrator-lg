# orchestrator-lg

[agency-orchestrator](https://github.com/jnMetaCode/agency-orchestrator) 核心引擎的 **LangGraph 重写原型**：
YAML 工作流 → StateGraph，带 checkpoint、人工审批中断（HITL）、循环硬止损。

```bash
uv sync && uv run pytest -q     # 6 项全绿，零外部依赖（FakeLLM）
```

迁移决策与概念映射见 **ARCHITECTURE.md**（这是本项目的主要产出——代码是它的证明）。

接 DeepSeek 真跑：`app/llm.py` 的 `DeepSeekLLM`，环境变量给 key 即可。
