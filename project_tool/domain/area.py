"""Area：稳定的项目分区 / 工作领域（V1-A）。

Area 回答「这个工作属于哪里？」（模块 / 子系统），
Milestone 回答「这个工作服务于哪个阶段？」（时间 / 交付节点）。

Area 刻意**没有** `status` / `progress` / `due_at`：
一旦给它加进度或截止时间，它就退化成第二个 Milestone，
V1-A 把「阶段」和「模块」分开的意义就没有了。

`owner_ids`（V1-C）是**例外，而且是有理由的例外**：V1-A 当初把 owner 和
status/progress/due_at 一起排除，理由是「加了时间维度就会变成第二个
Milestone」——但这个理由对 owner 不成立。owner 是**人**的维度，
和「哪个模块」「哪个阶段」正交。「这块归谁」不携带任何时间语义。
分区协作（每人负责一块 + 少量公共接口区）正是 Area 存在的意义，
没有 owner 的话归属只能靠口口相传。

**复数**是刻意的：一个 owner = 私有块；多个 owner = 公共接口区
（比如 core 那种被 UI/数据流/状态机共同依赖的模块）。不需要额外的
`shared: bool`，两个字段还可能互相矛盾。

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

    # 负责这块的成员（MBR-）。空 = 未分配；1 个 = 私有块；多个 = 公共接口区。
    # 引用不存在的 member 属于数据损坏，doctor 判 error。
    owner_ids: list[str] = []
