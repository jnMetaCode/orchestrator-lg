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

---

### 关于这一组项目

这是三套**评估驱动**的 AI 应用系统，同期开源，可以单独用也可以对照看：

| | 做什么 | 关键实测 |
|---|---|---|
| [repo-rag](https://github.com/jnMetaCode/repo-rag) | 中文知识库 RAG：结构分块 + 两层拒答 + 引用溯源 | hit@1 95.8% · faithfulness 0.981 |
| [orchestrator-lg](https://github.com/jnMetaCode/orchestrator-lg) | 自研 DAG 引擎迁到 LangGraph：checkpoint + 可持久化审批中断 | 7/7 测试 · YAML 零改动兼容 |
| [llm-gateway](https://github.com/jnMetaCode/llm-gateway) | 多模型网关：SSE 取消链 + 三态熔断 + token 计费 | 10/10 测试 · Docker |

共同的方法论：**先建评估集，再写优化**——每个技术决策都由实测数据推导，包括那些「该做但做了反而更差」的决策。

### 关于作者

[@jnMetaCode](https://github.com/jnMetaCode) · 11 年 IT、8 年技术团队管理 · 公众号 **AI不止语**
其他开源：[agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh)（19.8k★，267 个 AI 专家角色 × 18 类工具链）·
[superpowers-zh](https://github.com/jnMetaCode/superpowers-zh)（7.8k★）· [agency-orchestrator](https://github.com/jnMetaCode/agency-orchestrator)（2.1k★，本项目的上游）

> 在看北京的 AI 技术负责人 / 交付负责人 / 技术合伙人机会 · jnMetaCode@qq.com
