"""link.* 方法：多项目关联（禁止绝对路径）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from project_tool.application.context import (
    UNSET,
    WINDOWS_DRIVE_RE,
    ServiceContext,
    enum_value,
)
from project_tool.domain.enums import Lifecycle, LinkKind, LinkMode
from project_tool.domain.errors import AlreadyExists, InvalidArgument, ProjectToolError
from project_tool.domain.ids import new_id
from project_tool.domain.link import Link, LinkTarget
from project_tool.domain.timeutil import now_local
from project_tool.domain.validation import require_title
from project_tool.integrations import filesystem


class LinkService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    def link_add(
        self,
        name,
        locator=None,
        kind=None,
        mode="reference",
        project_id=None,
    ) -> dict[str, Any]:
        link_name = require_title(name, "link name")
        if self._find_link_by_name(link_name, include_deleted=True) is not None:
            raise AlreadyExists(f"link {link_name!r} already exists")
        link_kind = self._infer_link_kind(kind, locator)
        self._validate_locator(link_kind, locator)
        now = now_local()
        link = Link(
            id=new_id("link"),
            project_id=self.ctx.opened.project.id,
            name=link_name,
            target=LinkTarget(kind=link_kind, project_id=project_id, locator=locator),
            mode=enum_value(LinkMode, mode, "mode"),
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        return self.ctx.save(
            link,
            None,
            "link.added",
            {"name": link.name, "kind": link_kind.value},
            is_create=True,
        )

    def link_get(self, name) -> dict[str, Any]:
        return self._link(name).model_dump(mode="json")

    def link_list(self, include_archived=False, include_deleted=False) -> list[dict[str, Any]]:
        result = []
        for link in self.ctx.store.list_models("link", include_deleted=include_deleted):
            if link.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if link.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            result.append(link.model_dump(mode="json"))
        return result

    def link_update(
        self,
        name,
        locator=UNSET,
        kind=None,
        mode=None,
        enabled=None,
        project_id=UNSET,
        expected_rev=None,
    ) -> dict[str, Any]:
        link = self._link(name)
        base = self.ctx.require_expected_rev("link", link, expected_rev)
        fields: list[str] = []
        if locator is not UNSET:
            self._validate_locator(link.target.kind, locator)
            link.target.locator = locator
            fields.append("target.locator")
        if kind is not None:
            link.target.kind = enum_value(LinkKind, kind, "kind")
            self._validate_locator(link.target.kind, link.target.locator)
            fields.append("target.kind")
        if mode is not None:
            link.mode = enum_value(LinkMode, mode, "mode")
            fields.append("mode")
        if enabled is not None:
            link.enabled = bool(enabled)
            fields.append("enabled")
        if project_id is not UNSET:
            link.target.project_id = project_id
            fields.append("target.project_id")
        if not fields:
            return link.model_dump(mode="json")
        return self.ctx.save(link, base, "link.updated", {"fields": fields})

    def link_remove(self, name, expected_rev=None) -> dict[str, Any]:
        link = self._link(name)
        base = self.ctx.require_expected_rev("link", link, expected_rev)
        if link.lifecycle == Lifecycle.DELETED:
            return link.model_dump(mode="json")
        link.lifecycle = Lifecycle.DELETED
        return self.ctx.save(link, base, "link.removed", {})

    def link_resolve(self, name) -> dict[str, Any]:
        """解析一个 link 目标。

        `resolved` 的语义是**真的能拿到对方项目的数据**，不是「我填了地址」。
        Project Tool 没有服务器也不发网络请求（docs/06 §V2），所以只有
        `local_project` 能真正解析；其它 kind 一律 `resolved=false` 并说明原因——
        报告一个自己没验证过的 `true` 比报 `false` 更糟。
        """
        link = self._link(name)
        result: dict[str, Any] = {
            "id": link.id,
            "name": link.name,
            "kind": link.target.kind.value,
            "mode": link.mode.value,
            "enabled": link.enabled,
            "locator": link.target.locator,
            "project_id": link.target.project_id,
            "resolved": False,
        }
        if link.target.kind == LinkKind.LOCAL_PROJECT:
            mapped = self.ctx.opened.local.links.get(link.name, {}).get("path")
            locator = mapped or link.target.locator
            if locator:
                target_root = Path(locator)
                if not target_root.is_absolute():
                    target_root = self.ctx.paths.root / target_root
                target_root = target_root.resolve()
                result["path"] = str(target_root)
                project_file = target_root / ".pjt" / "project.json"
                if project_file.is_file():
                    try:
                        data = filesystem.read_json(project_file)
                        result["resolved"] = True
                        result["project"] = {"id": data.get("id"), "name": data.get("name")}
                    except ProjectToolError as exc:
                        result["error"] = exc.message
            if not result["resolved"] and "error" not in result:
                result["error"] = "no .pjt/project.json at the local path"
        else:
            # remote_project / git_repository / external：记录是有效的，但无法解析。
            result["resolved"] = False
            result["verifiable"] = False
            result["error"] = (
                f"{link.target.kind.value} links are recorded but not dereferenceable: "
                "Project Tool has no server and makes no network requests "
                "(docs/06 §V2). Use kind=local_project for a resolvable link."
            )
            if not (link.target.locator or link.target.project_id):
                result["error"] = "link has neither locator nor project_id"
        if not result["resolved"] and "error" not in result:
            result["error"] = "target not found"
        return result

    def link_status(self, name) -> dict[str, Any]:
        return self.link_resolve(name)

    # ----------------------------------------------------------------- 内部

    def _find_link_by_name(self, name: str, include_deleted: bool = False):
        wanted = str(name or "").strip().lower()
        for model in self.ctx.store.list_models("link", include_deleted=include_deleted):
            link = cast(Link, model)
            if link.name.lower() == wanted:
                return link
        return None

    def _link(self, ref) -> Link:
        text = str(ref or "").strip()
        if not text:
            raise InvalidArgument("link reference must not be empty")
        by_name = self._find_link_by_name(text, include_deleted=True)
        if by_name is not None:
            return by_name
        return self.ctx.load("link", text)

    @staticmethod
    def _infer_link_kind(kind, locator) -> LinkKind:
        if kind:
            return enum_value(LinkKind, kind, "kind")
        text = str(locator or "")
        if text.startswith("http://") or text.startswith("https://"):
            return LinkKind.REMOTE_PROJECT
        return LinkKind.LOCAL_PROJECT

    @staticmethod
    def _validate_locator(kind: LinkKind, locator) -> None:
        if kind != LinkKind.LOCAL_PROJECT:
            return
        text = str(locator or "").strip()
        if not text:
            raise InvalidArgument("local_project link requires a relative locator path")
        if Path(text).is_absolute() or WINDOWS_DRIVE_RE.match(text) or text.startswith("\\\\"):
            raise InvalidArgument(
                "absolute paths are not allowed in .pjt objects; "
                "map machine-specific paths in .pjt/local/local.toml"
            )
