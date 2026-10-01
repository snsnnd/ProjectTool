"""接口契约服务：工作树里的 markdown 文件 + Artifact 注册（V1-C）。

## 设计要点

**文件在工作树里，不在 `.pjt` 里。** 接口文档的正文是人写的散文，
硬塞进 JSON 只会让人绕过工具；而且 diff / blame / 历史 Git 已经做得比
任何自建机制好，不该重复造。ProjectTool 在这里只提供两件事：
**固定模板**和**检查**。

**注册成 Artifact（`kind=file`）**，这样就能复用已有的 locator 安全校验
（必须 project-relative、禁止 `..`）和 `artifact.verify`（文件还在不在），
不用重新发明一遍「这个路径可信吗」。

**不新增事件类型。** 建接口 = `artifact.added` + 写文件；改接口内容 = 人用
编辑器改文件（Git 记录）；`interface.sync` 只在 front-matter 改了 area 时
补一条 `artifact.updated`。事件语义因此保持干净：Artifact 就是 Artifact。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from project_tool.domain import interfaces as iface
from project_tool.domain.artifact import Artifact
from project_tool.domain.artifact_locator import check_locator
from project_tool.domain.enums import ArtifactKind
from project_tool.domain.errors import InvalidArgument, NotFound, ProjectToolError
from project_tool.domain.ids import new_id
from project_tool.domain.timeutil import now_local
from project_tool.domain.validation import optional_text, require_title
from project_tool.integrations import filesystem

INTERFACE_KIND = "interface"


def _slug(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name).strip()).strip("-.")
    return text or "interface"


def _artifact_id_for(ctx, locator: str | None = None, name: str | None = None) -> str | None:
    """按 locator 或 name 找已注册的 interface artifact。"""
    for record in ctx.store.list_raw("artifact", include_deleted=False):
        if not (record.get("metadata") or {}).get("interface"):
            continue
        if locator is not None and (record.get("locator") or "") == locator:
            return str(record.get("id"))
        if name is not None and record.get("name") == name:
            return str(record.get("id"))
    return None


def _relative(ctx, path: Path) -> str:
    root = Path(ctx.paths.root).resolve()
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise InvalidArgument(
            f"{path} is outside the project root; interface documents must live inside it"
        ) from exc


class InterfaceService:
    def __init__(self, ctx):
        self.ctx = ctx

    # ------------------------------------------------------------------ 读

    def interface_list(self, area=None, status=None) -> list[dict[str, Any]]:
        """列出已注册的接口，含从文件读到的 front-matter 摘要。

        **文件读不到不算错**——被登记的接口文件可能还没写（`init` 之前），
        也可能被人删了。`document: null` + `read_error` 如实报告，
        由 `interface_check` 决定严重程度。
        """
        wanted_area = self.ctx.area_id(area) if area else None
        rows: list[dict[str, Any]] = []
        for record in self.ctx.store.list_raw("artifact", include_deleted=False):
            if (record.get("metadata") or {}).get("interface") is not True:
                continue
            if wanted_area is not None and wanted_area not in (
                record.get("related_area_ids") or []
            ):
                continue
            rows.append(self._summarize(record, status))
        rows.sort(key=lambda item: (item.get("name") or "", item.get("id") or ""))
        return rows

    def _summarize(self, record: dict[str, Any], status_filter: str | None) -> dict[str, Any]:
        locator = str(record.get("locator") or "")
        summary: dict[str, Any] = {
            "id": record.get("id"),
            "name": record.get("name"),
            "locator": locator,
            "area_ids": list(record.get("related_area_ids") or []),
            "area_names": [
                self._area_name(item) for item in (record.get("related_area_ids") or [])
            ],
            "rev": record.get("rev"),
            "document": None,
            "read_error": None,
        }
        path = self.ctx.paths.root / locator
        if not path.is_file():
            summary["read_error"] = "file not found"
            return summary
        text = path.read_text(encoding="utf-8")
        data, _, error = iface.parse_front_matter(text)
        if error is not None:
            summary["read_error"] = error
            return summary
        summary["document"] = {
            "name": data.get("name"),
            "kind": data.get("kind"),
            "status": data.get("status"),
            "area": data.get("area"),
            "owners": data.get("owners") or [],
            "consumers": data.get("consumers") or [],
            "version": data.get("version", 1),
        }
        if status_filter and summary["document"].get("status") != status_filter:
            return {}
        return summary

    def interface_show(self, name=None, artifact=None) -> dict[str, Any]:
        """返回文档全文（给人看 / 给脚本读）。"""
        record = self._resolve(artifact or name)
        locator = str(record.get("locator") or "")
        path = self.ctx.paths.root / locator
        if not path.is_file():
            raise NotFound(
                f"interface document is missing: {locator} "
                f"(artifact {record.get('id')} still points at it)"
            )
        return {
            "id": record.get("id"),
            "name": record.get("name"),
            "locator": locator,
            "text": path.read_text(encoding="utf-8"),
        }

    def _area_name(self, area_id: str | None) -> str:
        if not area_id:
            return ""
        record = self.ctx.store.get_raw("area", area_id) or {}
        return str(record.get("name") or area_id)

    def _resolve(self, ref) -> dict[str, Any]:
        text = str(ref or "").strip()
        if not text:
            raise InvalidArgument("interface reference must not be empty")
        # `pjt interface list` 展示的是**名字**，所以 `interface show <name>`
        # 必须也认名字——否则界面教用户输入一个命令却不接受的东西。
        by_name = _artifact_id_for(self.ctx, None, name=text)
        if by_name is not None:
            return self.ctx.store.get_raw("artifact", by_name) or {}
        # ref_or_none 只在 ref 为空时返回 None；不存在的引用会抛，
        # 所以这里捕获后换成一条能指导下一步的 NotFound。
        try:
            artifact_id = self.ctx.ref_or_none("artifact", text)
        except ProjectToolError as exc:
            raise NotFound(
                f"no interface artifact {ref!r} ({exc.message}); "
                "try 'pjt interface list'"
            ) from None
        if artifact_id is None:
            raise NotFound(f"no interface artifact {ref!r} (try 'pjt interface list')")
        record = self.ctx.store.get_raw("artifact", artifact_id) or {}
        if (record.get("metadata") or {}).get("interface") is not True:
            raise InvalidArgument(f"artifact {artifact_id} is not an interface document")
        return record

    # ------------------------------------------------------------------ 写

    def interface_init(
        self,
        name,
        area=None,
        kind: str | None = None,
        path=None,
        owners=None,
        consumers=None,
        summary: str = "",
        change_rule: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        """从固定模板生成接口文档，并注册成 Artifact。

        刻意**不覆盖**已存在的文件（除非 --force）：接口文档是多方沟通的
        产物，被一次 `init` 静默清空是最坏的结果。
        """
        display_name = require_title(name, "interface name")
        area_id = ""
        area_name = ""
        if area:
            area_id = self.ctx.area_id(area)
            # front-matter 存**名字**不是 id：这份文档是给人看的沟通材料，
            # `ARA-01M3T…` 对读者没有信息量。名字万一不唯一，sync/check 时
            # area_id() 会报错并列出候选——正好在需要的时候把 V1-A 记下的
            # 「Area 名不唯一」这笔债暴露出来。
            area_name = self._area_name(area_id)
        target = (
            Path(str(path))
            if path
            else self.ctx.paths.root / iface.DEFAULT_DIR / f"{_slug(display_name)}.md"
        )
        if not target.is_absolute():
            target = self.ctx.paths.root / target
        target = target.resolve()
        locator = _relative(self.ctx, target)

        if target.exists() and not force:
            raise InvalidArgument(
                f"{locator} already exists; pass force=True to overwrite "
                "(it holds other people's content)"
            )

        owner_refs = [str(item) for item in (owners or []) if str(item).strip()]
        consumer_refs = [str(item).strip() for item in (consumers or []) if str(item).strip()]
        owner_ids = []
        for ref in owner_refs:
            owner_ids.append(self.ctx.member_id(ref))

        text = iface.render_template(
            display_name,
            kind=str(kind or ""),
            area=area_name,
            owners=owner_refs,
            consumers=consumer_refs,
            summary=optional_text(summary, "summary"),
            change_rule=change_rule,
        )
        # 自己写出来的模板自己先验一遍——不允许 init 产出非法文档
        iface.require_valid(text, what=f"generated interface {display_name!r}")
        filesystem.atomic_write_text(target, text if text.endswith("\n") else text + "\n")

        existing = _artifact_id_for(self.ctx, locator=locator)
        if existing is not None:
            return self.interface_sync(artifact=existing, expected_rev=None)

        checked = check_locator(ArtifactKind.FILE, locator)
        now = now_local()
        artifact = Artifact(
            id=new_id("artifact"),
            project_id=self.ctx.opened.project.id,
            name=display_name,
            description=optional_text(
                summary or (f"interface contract ({kind})" if kind else "interface contract"),
                "description",
            ),
            kind=ArtifactKind.FILE,
            locator=checked,
            related_area_ids=[area_id] if area_id else [],
            metadata=(
                {INTERFACE_KIND: True, "interface_kind": str(kind)}
                if kind
                else {INTERFACE_KIND: True}
            ),
            created_at=now,
            updated_at=now,
        )
        record = self.ctx.save(artifact, None, "artifact.added", {"name": display_name}, is_create=True)
        return record

    def interface_register(self, path, name=None, kind=None) -> dict[str, Any]:
        """把一份**已经存在的** markdown 登记成接口（迁移 / 手工维护的场景）。

        `interface.init` 只能从模板新建；但现实中很多接口文档是手写的、或者
        从别的工具迁过来的。不给这条路，就只能去手改 artifact 的 JSON——
        而那会被 rev 校验判成 `PROJECT_CORRUPTED`（§13 的读即校验，
        正好挡住了这个「后门」，所以必须提供正规的入口）。

        **不因为 `check` 有 error 就拒绝登记**：登记的用途恰恰是把已有的、
        可能还不完整的文档纳入管理。硬拦会让迁移做不成。
        但 front-matter 必须能解析——那才叫接口文档，没有它只是普通笔记。
        """
        target = Path(str(path))
        if not target.is_absolute():
            target = self.ctx.paths.root / target
        target = target.resolve()
        locator = _relative(self.ctx, target)
        if not target.is_file():
            raise NotFound(f"{locator} does not exist")

        text = target.read_text(encoding="utf-8")
        data, _, error = iface.parse_front_matter(text)
        if error is not None:
            raise InvalidArgument(
                f"{locator} is not an interface document: {error}. "
                "Scaffold one with 'pjt interface init' or add front-matter "
                "(--- / name / kind / status / area). See docs/03-data-model.md §4.7c."
            )

        display_name = str(name or data.get("name") or target.stem)
        existing = _artifact_id_for(self.ctx, locator=locator)
        if existing is not None:
            return self.interface_sync(artifact=existing, expected_rev=None)

        area_ref = str(data.get("area") or "").strip()
        area_id = self.ctx.area_id(area_ref) if area_ref else ""
        doc_kind = str(kind or data.get("kind") or "").strip()
        now = now_local()
        artifact = Artifact(
            id=new_id("artifact"),
            project_id=self.ctx.opened.project.id,
            name=require_title(display_name, "interface name"),
            description=optional_text(
                f"interface contract ({doc_kind})" if doc_kind else "interface contract",
                "description",
            ),
            kind=ArtifactKind.FILE,
            locator=check_locator(ArtifactKind.FILE, locator),
            related_area_ids=[area_id] if area_id else [],
            metadata={INTERFACE_KIND: True, "interface_kind": doc_kind} if doc_kind
            else {INTERFACE_KIND: True},
            created_at=now,
            updated_at=now,
        )
        record = self.ctx.save(
            artifact, None, "artifact.added", {"name": display_name}, is_create=True
        )
        # 把当前体检结果一起带回去，让人知道登记进来之后还差什么
        record = dict(record)
        record["check"] = self.interface_check(artifact=record["id"])
        return record

    def interface_sync(self, artifact=None, name=None, expected_rev=None) -> dict[str, Any]:
        """把 front-matter 与 Artifact 对齐（**只**同步 area 与 interface_kind）。

        刻意不做的事：不校验 status、不改正文、不动 name。文件是人写的，
        工具只维护「这份文件归哪个 Area 管」这一个双向关系。
        校验交给 `interface_check`——那是报告，不是自动改写。
        """
        record = self._resolve(artifact or name)
        loaded = self.ctx.load("artifact", record["id"])
        base = self.ctx.require_expected_rev("artifact", loaded, expected_rev)

        locator = str(loaded.locator)
        path = self.ctx.paths.root / locator
        if not path.is_file():
            raise NotFound(
                f"interface document is missing: {locator}; nothing to sync "
                "(restore the file or 'pjt artifact remove' the registration)"
            )
        data = iface.parse_front_matter(path.read_text(encoding="utf-8"))[0]

        fields: list[str] = []
        area_from_doc = str(data.get("area") or "").strip()
        if area_from_doc:
            resolved = self.ctx.area_id(area_from_doc)
            if loaded.related_area_ids != [resolved]:
                loaded.related_area_ids = [resolved]
                fields.append("related_area_ids")
        kind = str(data.get("interface_kind") or data.get("kind") or "").strip()
        if kind and (loaded.metadata or {}).get("interface_kind") != kind:
            loaded.metadata = {**(loaded.metadata or {}), "interface_kind": kind}
            fields.append("metadata.interface_kind")

        if not fields:
            return loaded.model_dump(mode="json")
        return self.ctx.save(loaded, base, "artifact.updated", {"fields": fields})

    # ------------------------------------------------------------------ 检查

    def interface_check(self, name=None, artifact=None) -> dict[str, Any]:
        """校验一份或全部接口文档。**只报告，不改写。**"""
        if name or artifact:
            targets = [self._summarize(self._resolve(artifact or name), None)]
        else:
            targets = [row for row in self.interface_list() if row]

        results: list[dict[str, Any]] = []
        errors = warnings = 0
        for row in targets:
            findings: list[dict[str, str]] = []
            if row.get("read_error"):
                findings.append(
                    {"level": "error", "message": f"cannot read document: {row['read_error']}"}
                )
            else:
                path = self.ctx.paths.root / row["locator"]
                text = path.read_text(encoding="utf-8")
                for item in iface.check_document(text):
                    findings.append({"level": item.level, "message": item.message})
            errors += sum(1 for item in findings if item["level"] == "error")
            warnings += sum(1 for item in findings if item["level"] == "warning")
            results.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "locator": row["locator"],
                    "area": ", ".join(row.get("area_names") or []),
                    "status": (row.get("document") or {}).get("status"),
                    "findings": findings,
                    "ok": not any(item["level"] == "error" for item in findings),
                }
            )
        return {"ok": errors == 0, "errors": errors, "warnings": warnings, "interfaces": results}
