"""Artifact：工程产物的**引用**（V1-A）。

设计边界（docs/09-v1a-design.md §3）：

- **只存 reference**：`kind` + `locator`，不存内容。没有 blob / CAS / snapshot / upload。
- **绝不修改被引用文件**：Artifact 是引用，Project Tool 的任何写路径都不会
  copy / move / delete / rename / rewrite locator 指向的工程文件。
- **关系放在 Artifact 上**（`related_*_ids`）：`artifact.attach --task` 只写一个文件，
  与并发编辑 Task 的操作不冲突（低冲突、merge-friendly）。
- `kind=file` 的 locator 必须是 **project-relative POSIX 路径**：绝对路径属于
  `.pjt/local/`，`..` 逃逸与 `.pjt/**` 一律拒绝。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from project_tool.domain.base import BaseObject
from project_tool.domain.enums import ArtifactKind

RELATION_FIELDS = (
    ("task", "related_task_ids"),
    ("decision", "related_decision_ids"),
    ("milestone", "related_milestone_ids"),
    ("goal", "related_goal_ids"),
)


class Artifact(BaseObject):
    type: Literal["artifact"] = "artifact"

    name: str
    description: str = ""

    kind: ArtifactKind
    locator: str

    related_task_ids: list[str] = Field(default_factory=list)
    related_decision_ids: list[str] = Field(default_factory=list)
    related_milestone_ids: list[str] = Field(default_factory=list)
    related_goal_ids: list[str] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)
