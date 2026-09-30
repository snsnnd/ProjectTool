"""Project Link：只允许相对路径 / URL / project ID，绝不保存绝对路径。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from project_tool.domain.base import BaseObject
from project_tool.domain.enums import LinkKind, LinkMode


class LinkTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: LinkKind
    project_id: str | None = None
    locator: str | None = None


class Link(BaseObject):
    type: Literal["link"] = "link"

    name: str
    target: LinkTarget
    mode: LinkMode = LinkMode.REFERENCE
    enabled: bool = True
