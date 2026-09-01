"""引擎测试：全部用 FakeLLM，零外部依赖。"""

from langgraph.types import Command

from app.engine import run
from app.llm import FakeLLM
from app.workflow import load_workflow

LINEAR = """
name: 线性三步
inputs:
  - name: topic
    required: true
steps:
  - id: research
    role: product/researcher
    task: "调研主题：{{topic}}"
    output: brief
  - id: outline
    role: eng/writer
    task: "基于调研写大纲：{{brief}}"
    output: outline_doc
    depends_on: [research]
  - id: draft
    role: eng/dev
    task: "基于 {{outline_doc}} 写正文"
    output: final
    depends_on: [outline]
"""


def test_linear_pipeline_vars_flow():
    wf = load_workflow(LINEAR)
    llm = FakeLLM({"调研主题": "调研结论A", "写大纲": "大纲B", "写正文": "正文C"})
    _, state = run(wf, llm, {"topic": "RAG"})
    assert state["vars"]["brief"] == "调研结论A"
    assert state["vars"]["final"] == "正文C"
    # 模板真的渲染了：第二步的 user prompt 含上一步产出
    assert "调研结论A" in llm.calls[1][1]
    # 每步各执行一次
    assert state["iters"] == {"research": 1, "outline": 1, "draft": 1}


PARALLEL = """
name: 并行分支
steps:
  - id: seed
    role: r
    task: "出发点"
    output: seed_out
  - id: branch_a
    role: a
    task: "A 路处理 {{seed_out}}"
    output: a_out
    depends_on: [seed]
  - id: branch_b
    role: b
    task: "B 路处理 {{seed_out}}"
    output: b_out
    depends_on: [seed]
  - id: merge
    role: m
    task: "合并 {{a_out}} 与 {{b_out}}"
    output: merged
    depends_on: [branch_a, branch_b]
"""


def test_parallel_branches_both_run_and_merge():
    wf = load_workflow(PARALLEL)
    llm = FakeLLM()
    _, state = run(wf, llm, {})
    assert "a_out" in state["vars"] and "b_out" in state["vars"]
    # 汇聚步看得到两路产出（vars 用 dict 合并 reducer，天然支持并行写不同 key）
    merged_prompt = next(u for _, u in llm.calls if u.startswith("合并"))
    assert state["vars"]["a_out"][:20] in merged_prompt


APPROVAL = """
name: 人工审批
steps:
  - id: plan
    role: pm
    task: "出方案"
    output: plan_doc
  - id: gate
    type: approval
    prompt: "方案如下，请审批：{{plan_doc}}"
    output: decision
    depends_on: [plan]
  - id: execute
    role: dev
    task: "按决定执行：{{decision}}"
    output: result
    depends_on: [gate]
"""


def test_approval_interrupt_and_resume():
    wf = load_workflow(APPROVAL)
    llm = FakeLLM({"出方案": "方案X"})
    graph, state = run(wf, llm, {}, thread_id="t1")
    # 走到审批点：图暂停，带出给人看的提示（含上游产出）
    assert "__interrupt__" in state
    payload = state["__interrupt__"][0].value
    assert payload["step"] == "gate"
    assert "方案X" in payload["prompt"]
    assert "result" not in state["vars"]
    # 人工放行 → 从 checkpoint 恢复继续
    config = {"configurable": {"thread_id": "t1"}}
    final = graph.invoke(Command(resume="同意，按 B 案执行"), config)
    assert final["vars"]["decision"] == "同意，按 B 案执行"
    assert "同意，按 B 案执行" in next(u for _, u in llm.calls if u.startswith("按决定执行"))


LOOP = """
name: 打磨循环
steps:
  - id: write
    role: writer
    task: "写稿"
    output: article
  - id: review
    role: editor
    task: "审稿：{{article}}"
    output: review_result
    depends_on: [write]
    loop:
      back_to: write
      max_iterations: 3
      exit_condition: "{{review_result}} contains 通过"
"""


def test_loop_until_exit_condition():
    wf = load_workflow(LOOP)

    class Editor(FakeLLM):
        def chat(self, system: str, user: str) -> str:
            super().chat(system, user)
            if user.startswith("审稿"):
                n = sum(1 for _, u in self.calls if u.startswith("审稿"))
                return "不行，重写" if n < 2 else "通过"
            return f"稿件v{sum(1 for _, u in self.calls if u.startswith('写稿'))}"

    llm = Editor()
    _, state = run(wf, llm, {})
    assert state["vars"]["review_result"] == "通过"
    assert state["iters"]["review"] == 2  # 第 2 轮通过
    assert state["iters"]["write"] == 2


def test_loop_hard_cap():
    wf = load_workflow(LOOP)
    llm = FakeLLM({"审稿": "不行，重写"})  # 永远不通过
    _, state = run(wf, llm, {})
    assert state["iters"]["review"] == 3  # max_iterations 硬止损，不会跑飞


def test_resume_across_process_restart_with_sqlite(tmp_path):
    """跨进程恢复：进程 A 跑到审批点后死掉，进程 B 仅凭 sqlite 文件续跑。

    "死掉"的模拟：丢弃 A 的 graph/llm/连接全部内存对象，B 用全新对象重建图。
    这是 MemorySaver 版讲不出的下半句——状态真的落了盘。
    """
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    from app.engine import resume

    wf = load_workflow(APPROVAL)
    db = tmp_path / "ckpt.db"

    # 进程 A：跑到审批中断，然后"崩溃"
    conn_a = sqlite3.connect(db, check_same_thread=False)  # LangGraph 节点跑在线程池里
    _, state = run(wf, FakeLLM({"出方案": "方案X"}), {}, thread_id="t-restart",
                   checkpointer=SqliteSaver(conn_a))
    assert "__interrupt__" in state
    assert "result" not in state["vars"]
    conn_a.close()
    del state

    # 进程 B：全新 LLM、全新图，只有 sqlite 文件是共享的
    conn_b = sqlite3.connect(db, check_same_thread=False)
    _, final = resume(wf, FakeLLM(), "同意，按 B 案执行", thread_id="t-restart",
                      checkpointer=SqliteSaver(conn_b))
    conn_b.close()
    assert final["vars"]["decision"] == "同意，按 B 案执行"
    assert "result" in final["vars"]  # 审批之后的步骤真的接着跑完了
    assert final["vars"]["plan_doc"] == "方案X"  # 审批之前的产出从 checkpoint 里回来了


def test_node_guard_injected():
    """每个 agent 节点的 system prompt 必须带输出约束——防模型反问用户导致链路断掉。"""
    wf = load_workflow(LINEAR)
    llm = FakeLLM()
    run(wf, llm, {"topic": "x"})
    for system, _user in llm.calls:
        assert "不要向用户提问" in system
        assert "只输出成品本身" in system


def test_validation_errors():
    import pytest

    with pytest.raises(ValueError):
        load_workflow("name: x\nsteps:\n  - id: a\n    task: t\n    depends_on: [ghost]")
    wf = load_workflow(LINEAR)
    with pytest.raises(ValueError, match="缺少必填输入"):
        run(wf, FakeLLM(), {})
