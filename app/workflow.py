"""YAML 工作流定义（兼容 agency-orchestrator 的字段子集）。

v0.1 支持：inputs / steps(id, role, task 模板, output, depends_on, type=approval,
condition, loop)。暂不支持：acceptance 核验、assert、skills、image——见 ARCHITECTURE.md。
"""

import re
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class InputDef(BaseModel):
    name: str
    description: str = ""
    required: bool = False
    default: str | None = None


class LoopDef(BaseModel):
    back_to: str
    max_iterations: int = Field(ge=1, le=10)
    exit_condition: str


class StepDef(BaseModel):
    id: str
    role: str = ""
    name: str = ""
    task: str = ""
    output: str | None = None
    depends_on: list[str] = []
    type: Literal["normal", "approval"] = "normal"
    prompt: str = ""            # approval 节点给人看的提示
    loop: LoopDef | None = None


class Workflow(BaseModel):
    name: str
    description: str = ""
    inputs: list[InputDef] = []
    steps: list[StepDef] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_refs(self) -> "Workflow":
        ids = {s.id for s in self.steps}
        if len(ids) != len(self.steps):
            raise ValueError("步骤 id 重复")
        for s in self.steps:
            for d in s.depends_on:
                if d not in ids:
                    raise ValueError(f"步骤 {s.id} 依赖不存在的 {d}")
            if s.loop and s.loop.back_to not in ids:
                raise ValueError(f"步骤 {s.id} 的 loop.back_to 指向不存在的 {s.loop.back_to}")
        return self


def load_workflow(text: str) -> Workflow:
    return Workflow.model_validate(yaml.safe_load(text))


_VAR = re.compile(r"\{\{(\w+)\}\}")


def render(template: str, variables: dict[str, str]) -> str:
    """{{var}} 模板渲染。缺失变量原样保留（与上游行为一致，便于排错）。"""
    return _VAR.sub(lambda m: variables.get(m.group(1), m.group(0)), template)


def eval_condition(cond: str, variables: dict[str, str]) -> bool:
    """极简条件语法（与上游对齐）：'{{var}} contains 词'。"""
    rendered = render(cond, variables)
    if " contains " in rendered:
        left, _, right = rendered.partition(" contains ")
        return right.strip() in left
    raise ValueError(f"不支持的条件语法: {cond}")
