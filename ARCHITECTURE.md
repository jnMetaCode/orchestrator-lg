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

## 验证
`uv run pytest -q`：6 项全绿（FakeLLM，零外部依赖）——线性流变量传递 / 并行分支汇聚 / **审批中断→跨调用恢复** / 循环达标退出 / **max_iterations 硬止损** / YAML 校验。
