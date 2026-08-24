# orchestrator-lg

[agency-orchestrator](https://github.com/jnMetaCode/agency-orchestrator) 核心引擎的 **LangGraph 重写原型**：
YAML 工作流 → StateGraph，带 checkpoint、人工审批中断（HITL）、循环硬止损。

> **迁移的理由是维护面积，不是框架新旧**：自研执行器 80% 的代码在重造调度、状态合并、失败恢复——
> 而项目真正的差异化是 YAML 前端、267 个角色库与 connector 生态。迁移让维护面积缩回差异化本身。
> 硬约束：**用户的 YAML 工作流一行不改**。

```bash
uv sync && uv run pytest -q                    # 7 项全绿，零外部依赖（FakeLLM）
uv run python scripts/run_demo.py              # 真机跑：4 步工作流 + 审批中断→checkpoint 恢复（本地 claude CLI，免 key）
```

**接上真实模型才暴露的两个坑**（任何 mock 都测不出来）：
① CLI 后端**泄漏项目上下文**——claude CLI 不是纯 LLM 而是带工具的 agent，在项目目录里会读到源码，污染节点输出；
修法：空沙箱 cwd + `--allowedTools ""` + prompt 走 stdin。
② **助手人格会切断工作流**——模型信息不足时会反问用户，但下游是程序、没人回答，一句反问整条链就废；
修法：引擎层统一注入输出守则（只输出成品 / 禁止反问 / 按假设产出并标注）。

迁移决策与概念映射见 **ARCHITECTURE.md**（这是本项目的主要产出——代码是它的证明）。

接 DeepSeek 真跑：`app/llm.py` 的 `DeepSeekLLM`，环境变量给 key 即可。
