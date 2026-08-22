"""真实跑一遍工作流（本地 claude CLI，免 key），演示 HITL 中断→恢复。

用法: uv run python scripts/run_demo.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from langgraph.types import Command  # noqa: E402

from app.engine import run  # noqa: E402
from app.llm import ClaudeCliLlm  # noqa: E402
from app.workflow import load_workflow  # noqa: E402

wf = load_workflow((ROOT / "workflows/interview-prep.yaml").read_text(encoding="utf-8"))
llm = ClaudeCliLlm()

print(f"▶ 工作流: {wf.name}（{len(wf.steps)} 步，含 1 个人工审批节点）\n")
graph, state = run(wf, llm, {
    "role": "大模型应用开发工程师",
    "project": "中文知识库 RAG：bge-m3 检索 + 两层拒答 + 引用溯源，30 条测试集实测 hit@1 95.8%",
}, thread_id="demo")

if "__interrupt__" not in state:
    print("未触发审批中断，异常")
    sys.exit(1)

payload = state["__interrupt__"][0].value
print("⏸  图已暂停在审批节点（状态已持久化到 checkpoint）")
print("—" * 60)
print(payload["prompt"][:700])
print("—" * 60)

print("\n▶ 模拟人工放行 → 从 checkpoint 恢复...\n")
final = graph.invoke(
    Command(resume="同意，但每题必须带我项目里的真实数字，不要写通用模板"),
    {"configurable": {"thread_id": "demo"}},
)
print("✅ 工作流完成\n")
print(final["vars"]["card"][:1400])
print(f"\n步骤执行次数: {final['iters']}")
