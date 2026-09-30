"""git.* 方法：Git 只读感知（V1-B）。

**只读**——本模块除了 `git.link_commit`（写 `.pjt`，不碰 Git 仓库）之外
不修改任何东西。绝不 clone / add / commit / checkout / merge / reset / clean。

**只推导、不回写**：`git.status` 把改动的文件映射到「候选 Area」，
但**绝不自动改写 `Task.area_id`**。Area 是人工判断的结构信息，
从文件路径机械推导并回写会把跨 Area 的 commit 错误归类。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from project_tool.application.context import ServiceContext
from project_tool.domain.area import Area
from project_tool.domain.area_paths import match_any
from project_tool.domain.artifact import Artifact
from project_tool.domain.artifact_locator import GIT_ADAPTER_NOTE
from project_tool.domain.enums import ArtifactKind, Lifecycle
from project_tool.domain.errors import InvalidArgument
from project_tool.domain.ids import new_id
from project_tool.domain.timeutil import now_local
from project_tool.domain.validation import require_title
from project_tool.integrations import git as git_integration
from project_tool.integrations.git import GitRepo, GitUnavailable

# commit message 里的 trailer，用来把提交关联到任务
TASK_TRAILER = "PJT-Task"
MAX_LOG_LIMIT = 500
PJT_DIRNAME = ".pjt"


def _count_by_status(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


class GitService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    # ------------------------------------------------------------------ 探测

    def git_available(self) -> dict[str, Any]:
        info = git_integration.availability(self.ctx.paths.root)
        if not info["available"]:
            return {**info, "project_root": str(self.ctx.paths.root)}
        # project root != git root 是正常且常见的情况，必须显式说明
        project_root = str(self.ctx.paths.root)
        return {
            **info,
            "project_root": project_root,
            "project_root_is_git_root": info["work_tree"] == project_root,
            "project_subdir": self._subdir(info["work_tree"]),
        }

    def _subdir(self, work_tree: str) -> str | None:
        """project root 相对 git root 的子目录。

        EFW 场景 = `new/efw`；**同根目录时必须返回 None**——
        `Path.relative_to` 在两者相同时返回 `.`，若当成真实子目录前缀会把所有文件都过滤掉。
        """
        try:
            relative = Path(self.ctx.paths.root).resolve().relative_to(Path(work_tree))
        except ValueError:
            return None
        text = relative.as_posix()
        return None if text in ("", ".") else text

    def _repo(self) -> GitRepo:
        try:
            return git_integration.detect(self.ctx.paths.root)
        except GitUnavailable as exc:
            raise InvalidArgument(
                f"git is not available for this project: {exc}"
            ) from exc

    def _require_repo(self) -> GitRepo | None:
        try:
            return git_integration.detect(self.ctx.paths.root)
        except GitUnavailable:
            return None

    # ------------------------------------------------------------------ status

    def git_status(
        self, area=None, include_untracked=True, include_pjt=False
    ) -> dict[str, Any]:
        """改动的工程文件 + 候选 Area + 被哪些 Artifact 引用。

        `area` 只做过滤（按 name/id 解析），不会改写任何 Area 或 Task。

        `.pjt/**` 默认**折叠成一行摘要**：它是 Project Tool 自己的 canonical 数据
        （确实应该跟代码一起 commit），但逐个文件列出来只会淹没真正待 review 的
        工程文件。`include_pjt=True` 可以展开。
        """
        repo = self._require_repo()
        if repo is None:
            return {
                "available": False,
                "reason": git_integration.availability(self.ctx.paths.root)["reason"],
                "files": [],
            }

        wanted_area_id = self.ctx.require_area_id(area) if area else None
        areas = self._bindable_areas()
        artifacts = self._artifacts()

        subdir = self._subdir(str(repo.work_tree))
        entries = repo.status(subdir=subdir)
        files: list[dict[str, Any]] = []
        pjt_files: list[dict[str, Any]] = []
        for entry in entries:
            if entry.status == "ignored":
                continue
            if not include_untracked and entry.status == "untracked":
                continue
            relative = self._relative_to_project(entry.path, subdir)
            if relative is None:
                continue
            if relative == PJT_DIRNAME or relative.startswith(PJT_DIRNAME + "/"):
                pjt_files.append({"path": relative, "status": entry.status})
                if not include_pjt:
                    continue
            matched = [
                {
                    "id": area["id"],
                    "name": area["name"],
                    "patterns": list(area["path_patterns"]),
                }
                for area in areas
                if match_any(area["path_patterns"], relative)
            ]
            if wanted_area_id and not any(item["id"] == wanted_area_id for item in matched):
                continue
            files.append(
                {
                    "path": relative,
                    "git_path": entry.path,
                    "status": entry.status,
                    "old_path": entry.old_path,
                    "candidate_areas": matched,
                    "referenced_by_artifacts": [
                        {
                            "id": art["id"],
                            "name": art["name"],
                            "kind": art["kind"],
                            "relation": art["relation"],
                        }
                        for art in artifacts
                        if art["locator"] == relative
                    ],
                }
            )
        return {
            "available": True,
            "reason": None,
            "work_tree": str(repo.work_tree),
            "project_subdir": subdir,
            "count": len(files),
            "files": files,
            "pjt_changed": len(pjt_files),
            "pjt_status_counts": _count_by_status(pjt_files),
            "unbound_areas": [
                {"id": a["id"], "name": a["name"]} for a in self._all_areas() if not a["path_patterns"]
            ],
        }

    def _relative_to_project(self, git_path: str, subdir: str | None) -> str | None:
        """git root 相对路径 -> project root 相对路径。"""
        if subdir and (git_path == subdir or git_path.startswith(subdir + "/")):
            rest = git_path[len(subdir) :].lstrip("/")
            return rest or None
        if subdir is None:
            return git_path
        return None

    # ------------------------------------------------------------------ log

    def git_log(self, task=None, limit=30, path=None) -> dict[str, Any]:
        """按任务 trailer / 路径过滤提交历史（只读）。"""
        repo = self._require_repo()
        if repo is None:
            return {
                "available": False,
                "reason": git_integration.availability(self.ctx.paths.root)["reason"],
                "commits": [],
            }
        task_id = self.ctx.resolve_ref("task", task, allow_deleted=True) if task else None
        grep = f"{TASK_TRAILER}:" if task_id else None
        subdir = self._subdir(str(repo.work_tree))
        path_filter = self._git_relative(path) if path else subdir
        try:
            commits = repo.log(limit=min(int(limit), MAX_LOG_LIMIT), trailer=grep,
                               path_filter=path_filter)
        except GitUnavailable as exc:
            return {"available": False, "reason": str(exc), "commits": []}
        for commit in commits:
            commit["linked_task_ids"] = self._trailer_task_ids(repo, commit["sha"])
        return {
            "available": True,
            "reason": None,
            "task_id": task_id,
            "count": len(commits),
            "commits": commits,
        }

    def _git_relative(self, path: str) -> str:
        """project-relative 路径 -> git-root-relative 路径。"""
        repo = self._require_repo()
        subdir = self._subdir(str(repo.work_tree)) if repo else None
        if subdir:
            return f"{subdir}/{str(path).strip('/')}"
        return str(path)

    def _trailer_task_ids(self, repo: GitRepo, sha: str) -> list[str]:
        try:
            body = repo.commit_body(sha)
        except GitUnavailable:
            return []
        ids: list[str] = []
        for value in git_integration.trailer_values(body["trailers"], TASK_TRAILER):
            ids.extend(token for token in value.replace(",", " ").split() if token)
        return ids

    # ------------------------------------------------------- link commit（写 .pjt）

    def git_link_commit(self, commit, task=None, name=None, description="") -> dict[str, Any]:
        """把一个 commit 登记成 `git_commit` Artifact（可同时关联任务）。

        **只写 `.pjt`，不写 Git 仓库。**
        """
        repo = self._repo()
        sha = repo.resolve_commit(str(commit))
        body = repo.commit_body(sha)

        task_id = None
        if task:
            task_id = self.ctx.resolve_ref("task", task)
        elif git_integration.trailer_values(body["trailers"], TASK_TRAILER):
            first = git_integration.trailer_values(body["trailers"], TASK_TRAILER)[0]
            token = first.replace(",", " ").split()[0] if first.split() else ""
            if token:
                task_id = self.ctx.resolve_ref("task", token, allow_deleted=True)

        locator = sha[:12]
        existing = self._find_by_locator(ArtifactKind.GIT_COMMIT, locator)
        if existing is not None:
            # 幂等：同一个 commit 不重复登记；若这次带了新任务则只补关联
            if task_id and task_id not in existing.related_task_ids:
                self.ctx.save(
                    existing,
                    existing.rev,
                    "git.commit_linked",
                    {"sha": sha, "task_id": task_id, "created": False},
                )
            return {
                "artifact": existing.model_dump(mode="json"),
                "created": False,
                "commit": body,
            }

        now = now_local()
        artifact = Artifact(
            id=new_id("artifact"),
            project_id=self.ctx.opened.project.id,
            name=name or require_title(body["subject"] or sha[:12], "artifact name"),
            description=description or GIT_ADAPTER_NOTE,
            kind=ArtifactKind.GIT_COMMIT,
            locator=locator,
            related_task_ids=[task_id] if task_id else [],
            created_at=now,
            updated_at=now,
        )
        record = self.ctx.save(
            artifact,
            None,
            "git.commit_linked",
            {
                "sha": sha,
                "short_sha": sha[:12],
                "author": body["author"],
                "task_id": task_id,
                "created": True,
            },
            is_create=True,
        )
        return {"artifact": record, "created": True, "commit": body}

    def _find_by_locator(self, kind: ArtifactKind, locator: str):
        for model in self.ctx.store.list_models("artifact"):
            artifact = cast(Any, model)
            if artifact.kind == kind and artifact.locator == locator:
                return artifact
        return None

    # ------------------------------------------------------------------ verify

    def verify_locator(self, kind: str, locator: str) -> dict[str, Any] | None:
        """`git_commit` / `git_branch` 现在能真的解析了（V1-B 之前只校验格式）。

        返回 None 表示「不是 git kind，交给通用逻辑」。不可解析的返回 status=missing。
        """
        if kind not in (ArtifactKind.GIT_COMMIT.value, ArtifactKind.GIT_BRANCH.value):
            return None
        repo = self._require_repo()
        if repo is None:
            return {
                "status": "skipped",
                "exists": None,
                "path": None,
                "detail": "git unavailable; locator kept as an unverified reference",
            }
        ref = locator if kind == ArtifactKind.GIT_BRANCH.value else f"{locator}^{{commit}}"
        try:
            resolved = repo.resolve_commit(ref)
        except GitUnavailable:
            return {
                "status": "missing",
                "exists": False,
                "path": None,
                "detail": f"git cannot resolve {kind} {locator!r} in {repo.work_tree}",
            }
        return {
            "status": "ok",
            "exists": True,
            "path": resolved,
            "detail": f"resolved to {resolved[:12]} in {repo.work_tree}",
        }

    # ------------------------------------------------------------------ 内部

    def _all_areas(self) -> list[dict[str, Any]]:
        rows = []
        for model in self.ctx.store.list_models("area"):
            area = cast(Area, model)
            if area.lifecycle != Lifecycle.ACTIVE:
                continue
            rows.append(
                {
                    "id": area.id,
                    "name": area.name,
                    "path_patterns": list(area.path_patterns),
                }
            )
        return rows

    def _bindable_areas(self) -> list[dict[str, Any]]:
        return [row for row in self._all_areas() if row["path_patterns"]]

    def _artifacts(self) -> list[dict[str, Any]]:
        rows = []
        for model in self.ctx.store.list_models("artifact"):
            artifact = cast(Any, model)
            if artifact.lifecycle == Lifecycle.DELETED:
                continue
            if artifact.kind not in (ArtifactKind.FILE, ArtifactKind.DOCUMENT):
                continue
            relation = "artifact"
            if artifact.related_task_ids:
                relation = "task"
            rows.append(
                {
                    "id": artifact.id,
                    "name": artifact.name,
                    "kind": artifact.kind.value,
                    "locator": artifact.locator,
                    "relation": relation,
                }
            )
        return rows


__all__ = ["MAX_LOG_LIMIT", "TASK_TRAILER", "GitService", "GitUnavailable"]
