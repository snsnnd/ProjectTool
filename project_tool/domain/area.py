"""Area：稳定的项目分区 / 工作领域（V1-A）。

Area 回答「这个工作属于哪里？」（模块 / 子系统），
Milestone 回答「这个工作服务于哪个阶段？」（时间 / 交付节点）。

Area 刻意**没有** `status` / `progress` / `due_at` / `owner`：
一旦给它加进度或截止时间，它就退化成第二个 Milestone，
V1-A 把「阶段」和「模块」分开的意义就没有了。

`path_patterns`（V1-B，可选）：把 Area 和工程目录关联起来，让 Git Adapter
能把「改动的文件」映射到「候选 Area」。**默认空 = 纯语义 Area，行为完全不变**，
不填的人不需要关心这件事。
"""

from __future__ import annotations

from typing import Literal

from project_tool.domain.base import BaseObject


class Area(BaseObject):
    type: Literal["area"] = "area"

    name: str
    description: str = ""

    parent_area_id: str | None = None

    # 可选：相对 project root 的 glob 列表（POSIX 风格）。空列表 = 不做目录绑定。
    path_patterns: list[str] = []
