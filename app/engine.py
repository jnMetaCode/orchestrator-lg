"""图引擎：Workflow -> LangGraph StateGraph。

上游概念 -> LangGraph 原语的映射（详见 ARCHITECTURE.md）：
  depends_on DAG        -> add_edge（无依赖的并行步自动同超步并发）
  output 变量池          -> State.vars（dict 合并 reducer，天然支持并行写不同 key）
  type: approval        -> interrupt()（HITL：暂停等人，靠 checkpoint 可跨进程恢复）
  loop.max_iterations   -> 条件边回跳 + 迭代计数 + recursion_limit 双保险
  断点续跑               -> checkpointer（默认 MemorySaver；传 SqliteSaver 即得跨进程
                           恢复——见 resume() 与 tests 里的"杀进程重启"用例）
"""

from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .llm import LLM
from .workflow import StepDef, Workflow, eval_condition, render


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class WfState(TypedDict):
    vars: Annotated[dict[str, str], _merge]
    iters: Annotated[dict[str, int], _merge]  # loop 步的已执行次数


# 工作流节点的通用约束。存在的理由（2026-08-22 实测）：
# 通用 chat 模型默认是"助手人格"，会寒暄、复盘自己做了什么、并在信息不足时反问用户。
# 但在工作流里产出是被下游步骤消费的，没有人会回答它的提问——一句反问就让整条链断掉。
# （上游 agency-orchestrator 的 YAML 里逐条写这段守则；引擎层统一注入更可靠。）
_NODE_GUARD = (
    "\n\n严格输出约束："
    "① 只输出成品本身，不要开场白、寒暄、或「我做了什么」的说明；"
    "② 绝对不要向用户提问或请其确认——你的输出由下游程序消费，没有人会回答你；"
    "③ 信息不足时按最合理假设直接产出，并在结果内用一行标注该假设；"
    "④ 不要建议后续动作或说「需要我继续吗」。"
)


def _make_agent_node(step: StepDef, llm: LLM):
    def node(state: WfState) -> dict[str, Any]:
        task = render(step.task, state["vars"])
        # v0.1 角色系统降级为 system prompt 存根；完整人设加载见 ARCHITECTURE.md
        system = (
            f"你是「{step.name or step.role}」（{step.role}），按任务要求交付专业结果。"
            + _NODE_GUARD
        )
        content = llm.chat(system, task)
        out = {step.output: content} if step.output else {}
        return {"vars": out, "iters": {step.id: state["iters"].get(step.id, 0) + 1}}

    return node


def _make_approval_node(step: StepDef):
    def node(state: WfState) -> dict[str, Any]:
        # interrupt(): 图在此暂停并持久化，人工用 Command(resume=...) 继续。
        decision = interrupt(
            {"step": step.id, "prompt": render(step.prompt or "请审批", state["vars"])}
        )
        out = {step.output: str(decision)} if step.output else {}
        return {"vars": out, "iters": {}}

    return node


def build_graph(wf: Workflow, llm: LLM, checkpointer=None):
    g = StateGraph(WfState)
    dependents: dict[str, list[str]] = {s.id: [] for s in wf.steps}
    for s in wf.steps:
        for d in s.depends_on:
            dependents[d].append(s.id)

    for s in wf.steps:
        node = _make_approval_node(s) if s.type == "approval" else _make_agent_node(s, llm)
        g.add_node(s.id, node)

    for s in wf.steps:
        if not s.depends_on:
            g.add_edge(START, s.id)
        if s.loop:
            # 循环步：出边全部交给条件路由（回跳 or 顺流），不再加静态边
            loop = s.loop
            nxt = dependents[s.id] or [END]

            def route(state: WfState, _s: StepDef = s, _loop=loop, _nxt=nxt):
                done = state["iters"].get(_s.id, 0)
                if done >= _loop.max_iterations:
                    return _nxt  # 达上限强制出循环——防跑飞的硬止损
                if eval_condition(_loop.exit_condition, state["vars"]):
                    return _nxt
                return [_loop.back_to]

            g.add_conditional_edges(s.id, route)
        elif not dependents[s.id]:
            g.add_edge(s.id, END)
    for s in wf.steps:
        for d in s.depends_on:
            # 循环步的出边已由条件路由接管
            src = next(x for x in wf.steps if x.id == d)
            if not src.loop:
                g.add_edge(d, s.id)

    return g.compile(checkpointer=checkpointer or MemorySaver())


def run(wf: Workflow, llm: LLM, inputs: dict[str, str], *, thread_id: str = "main",
        recursion_limit: int = 50, checkpointer=None):
    """跑一个工作流。返回 (graph, final_state)。

    有 approval 步时 final_state 里会带 __interrupt__，用
    graph.invoke(Command(resume=...), config) 继续。
    """
    variables = dict(inputs)
    for inp in wf.inputs:
        if inp.name not in variables:
            if inp.required:
                raise ValueError(f"缺少必填输入: {inp.name}")
            if inp.default is not None:
                variables[inp.name] = inp.default
    graph = build_graph(wf, llm, checkpointer)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
    state = graph.invoke({"vars": variables, "iters": {}}, config)
    return graph, state


def resume(wf: Workflow, llm: LLM, decision: str, *, thread_id: str = "main",
           recursion_limit: int = 50, checkpointer=None):
    """从 checkpoint 恢复被 approval 打断的工作流——包括进程重启之后。

    跨进程恢复的分工：图拓扑不入库，从 YAML 重建（build_graph 是确定性的）；
    执行状态（vars/iters/停在哪个节点）由 checkpointer 提供。
    同进程续跑用原 graph.invoke(Command(...)) 即可；这个入口给"进程死过一回"的场景，
    此时必须传持久化的 checkpointer（如 SqliteSaver），MemorySaver 里什么都不剩。
    """
    graph = build_graph(wf, llm, checkpointer)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
    state = graph.invoke(Command(resume=decision), config)
    return graph, state
