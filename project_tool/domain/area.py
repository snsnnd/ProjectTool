"""Area：稳定的项目分区 / 工作领域（V1-A）。

Area 回答「这个工作属于哪里？」（模块 / 子系统），
Milestone 回答「这个工作服务于哪个阶段？」（时间 / 交付节点）。

Area 刻意**没有** `status` / `progress` / `due_at` / `owner`：
一旦给它加进度或截止时间，它就退化成第二个 Milestone，
V1-A 把「阶段」和「模块」分开的意义就没有了。
"""

from __future__ import annotations

from typing import Literal

from project_tool.domain.base import BaseObject


class Area(BaseObject):
    type: Literal["area"] = "area"

    name: str
    description: str = ""

    parent_area_id: str | None = None
