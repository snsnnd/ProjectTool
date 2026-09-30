"""Member：只是“这个人在这个项目中的身份”，不是账号。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from project_tool.domain.base import BaseObject


class GitIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)


class Member(BaseObject):
    type: Literal["member"] = "member"

    display_name: str
    handle: str

    roles: list[str] = Field(default_factory=list)
    git: GitIdentity = Field(default_factory=GitIdentity)
    external_ids: dict[str, str] = Field(default_factory=dict)

    active: bool = True
