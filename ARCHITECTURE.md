# 架构演进：自研 DAG 执行器 → LangGraph

> agency-orchestrator（TS，2.1k★）核心引擎的 LangGraph 重写原型。
> 本文是迁移决策记录——不是"新框架好所以换"，每一条都对着上游真实代码（src/core/executor.ts、src/types.ts）。

## 概念映射表

| 上游（自研 TS） | LangGraph 版 | 迁移收益 |
|---|---|---|
| `core/dag.ts` 手写 DAG 调度 + concurrency 参数 | `StateGraph` + `add_edge`，同超步自动并发 | 删掉整个调度器；并发度不再需要手工配置 |
| `output` 变量池（executor 串场） | `State.vars` + dict 合并 reducer | 并行步写不同 key 天然无冲突，框架保证 |
| `type: approval / human_input` 轮询等待 | `interrupt()` + `Command(resume=)` | **暂停即持久化**：进程可以退出，明天在另一台机器恢复审批——自研版做不到 |
| `loop.back_to + max_iterations` 手工计数 | 条件边回跳 + iters 计数 + `recursion_limit` | 双保险：业务上限之外还有图级硬止损 |
| 断点：无（挂了重跑全流程） | checkpointer（Memory/Sqlite/Postgres） | 每个超步自动存档，失败从断点重放；这是生产级工作流的分水岭 |
| `{{var}}` 模板（core/template.ts） | 原样保留 | **YAML 前端格式不变**，存量 workflows/ 兼容是硬约束 |
| 11 种 connector（connectors/*.ts） | `LLM` Protocol（Fake / DeepSeek 先行） | 接口抽象保留，逐家搬 |

## 保留什么（兼容承诺）
YAML 字段名、`{{var}}` 模板语法、condition 的 `contains` 语法——**用户的工作流文件一行不改**。迁移的是引擎，不是生态。

## v0.1 刻意不做
- `acceptance` 自动核验 + 返工（下一步：LangGraph 条件边天然表达"核验不过→回本步"）
- `assert` 机械断言、`skills` 注入、image 节点、角色人设完整加载（现为 system prompt 存根）
- SqliteSaver 持久化落盘（MemorySaver 先证明模型，换 saver 是一行事）

## 为什么值得迁（一句话版）
自研执行器 80% 的代码在解决 LangGraph 已经解决的问题（调度/状态/恢复），而剩下 20%（YAML 前端、角色库、connector 生态）才是这个项目真正的差异化——迁移让维护面积缩到差异化本身。

## 真机运行发现的两个坑（2026-08-22，本地 claude CLI 后端）

引擎跑通只是第一步，接上真实 LLM 才暴露出来的两个问题——都不是框架的问题，是"把 agent 当纯 LLM 用"的认知错误：

**① CLI 后端会泄漏项目上下文。** claude CLI 不是纯 LLM，它是带工具和项目感知的 agent：
在项目目录里跑会读到 CLAUDE.md 和源码，导致节点"知道"自己在哪个仓库，输出被污染
（实测：定稿节点反问"当前项目是 orchestrator-lg，要我从项目里提取数据吗"）。
三重隔离：cwd 指向空沙箱 + `--allowedTools ""` + prompt 走 stdin（变参 flag 会吞掉位置参数）。

**② 助手人格会切断工作流。** 通用 chat 模型默认会寒暄、复盘自己、并在信息不足时**反问用户**——
但工作流里的产出是被下游步骤消费的，没有人会回答它，一句反问整条链就废了。
修法：引擎层统一注入 `_NODE_GUARD`（只输出成品 / 禁止反问 / 信息不足按假设产出并标注 / 不建议后续动作）。
上游 agency-orchestrator 是在每份 YAML 里逐条手写这段守则——引擎层注入更可靠，且新工作流零成本继承。
实测修复后：模型改为在结果末尾标注"以下数值基于推演，如有真实数据可替换"，正是守则期望的行为。

## 验证
`uv run pytest -q`：7 项全绿（FakeLLM，零外部依赖）——线性流变量传递 / 并行分支汇聚 / **审批中断→跨调用恢复** / 循环达标退出 / **max_iterations 硬止损** / YAML 校验 / 节点守则注入。

真机端到端：`uv run python scripts/run_demo.py`——4 步工作流（含审批节点）接本地 claude CLI 跑通，全程约 90 秒，演示中断→checkpoint 恢复→定稿。
