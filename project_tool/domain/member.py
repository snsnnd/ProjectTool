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

    # 自由字符串，但 `pjt member add --role` 只建议用 KNOWN_ROLES 里的值。
    #
    # V1-C 决策：**不在本地做权限门禁**。工具将来上服务器后权限以服务器为准；
    # 现在硬编码一个本地门禁只会制造「已经管住了」的错觉——`.pjt/objects/**`
    # 是可读 JSON 跟着 Git 走，谁都能改。所以 role 现在是**数据**：
    # 记录意图、供人和服务器去审，doctor 对未知 role 只报 warning（老项目
    # 可能已经有自由写的 role，不能因此判 corrupted）。
    roles: list[str] = Field(default_factory=list)
    git: GitIdentity = Field(default_factory=GitIdentity)
    external_ids: dict[str, str] = Field(default_factory=dict)

    active: bool = True

# 建议的角色词汇表。**不是白名单**——自由字符串仍然接受，只是未知值会
# 让 doctor 报 warning。理由见 Member.roles 的注释。
KNOWN_ROLES = ("leader", "member", "viewer")
