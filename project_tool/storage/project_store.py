"""项目定位、初始化与打开。"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from project_tool.domain.enums import ProjectStatus
from project_tool.domain.errors import (
    AlreadyExists,
    NotFound,
    ProjectCorrupted,
    SchemaUnsupported,
)
from project_tool.domain.event import Event
from project_tool.domain.hashing import compute_rev
from project_tool.domain.ids import COLLECTION_BY_TYPE, new_id
from project_tool.domain.project import Project
from project_tool.domain.timeutil import now_local
from project_tool.integrations import filesystem
from project_tool.storage.local_state import LocalState, load_local, save_local
from project_tool.version import SCHEMA_VERSION

PJT_DIRNAME = ".pjt"
# 分组写入，便于给不同语义的文件各自加注释。
# 派生缓存这一组是 V1-C 加的：`state/state.json` 每次事务都重写，
# `refs/labels.json` 由重扫 task 生成——两者都是可重建的派生数据，
# 提交进 Git 会让**每一次**多人合并都冲突（探针实测 9 个场景里 8 个）。
#
# 刻意写具体文件而不是整个 `refs/` 目录：将来 refs/ 里可能放**规范**数据，
# 一旦整个目录被忽略就会静默丢失。
GITIGNORE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("# Project Tool local state", (".pjt/local/", ".pjt/transactions/")),
    (
        "# Project Tool derived caches (rebuilt on demand; never commit these)",
        (".pjt/state/", ".pjt/refs/labels.json"),
    ),
)
GITIGNORE_LINES = tuple(line for _, lines in GITIGNORE_GROUPS for line in lines)

# 派生缓存的相对路径——doctor 用它查「有没有被提交进 Git」
DERIVED_CACHE_PATHS = (".pjt/state/state.json", ".pjt/refs/labels.json")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class ProjectPaths:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    @property
    def pjt(self) -> Path:
        return self.root / PJT_DIRNAME

    @property
    def project_json(self) -> Path:
        return self.pjt / "project.json"

    @property
    def config_toml(self) -> Path:
        return self.pjt / "config.toml"

    @property
    def objects(self) -> Path:
        return self.pjt / "objects"

    @property
    def events(self) -> Path:
        return self.pjt / "events"

    @property
    def refs(self) -> Path:
        return self.pjt / "refs"

    @property
    def labels_json(self) -> Path:
        return self.refs / "labels.json"

    @property
    def state(self) -> Path:
        return self.pjt / "state"

    @property
    def state_json(self) -> Path:
        return self.state / "state.json"

    @property
    def local(self) -> Path:
        return self.pjt / "local"

    @property
    def local_toml(self) -> Path:
        return self.local / "local.toml"

    @property
    def transactions(self) -> Path:
        return self.pjt / "transactions"

    @property
    def locks(self) -> Path:
        return self.local / "locks"

    @property
    def conflicts(self) -> Path:
        return self.local / "conflicts"

    @property
    def backups(self) -> Path:
        return self.local / "backups"

    def object_dir(self, obj_type: str) -> Path:
        return self.objects / COLLECTION_BY_TYPE[obj_type]

    def event_dir(self, occurred_at) -> Path:
        return self.events / f"{occurred_at.year:04d}" / f"{occurred_at.month:02d}"


@dataclass
class OpenedProject:
    paths: ProjectPaths
    project: Project
    config: dict[str, Any]
    local: LocalState

    @property
    def device_id(self) -> str:
        return self.local.device_id

    def save_local(self) -> None:
        save_local(self.paths, self.local)


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "project"


def find_project_root(start: str | Path | None = None) -> Path | None:
    current = Path(start) if start is not None else Path.cwd()
    current = current.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / PJT_DIRNAME / "project.json").is_file():
            return candidate
    return None


def require_paths(start: str | Path | None = None) -> ProjectPaths:
    root = find_project_root(start)
    if root is None:
        raise NotFound("not inside a Project Tool project (.pjt not found); run 'pjt init'")
    return ProjectPaths(root)


def init_project(
    root: str | Path,
    name: str | None = None,
    description: str = "",
    slug: str | None = None,
) -> OpenedProject:
    paths = ProjectPaths(root)
    if paths.project_json.exists():
        raise AlreadyExists(f"project already initialized at {paths.root}")

    for collection in COLLECTION_BY_TYPE.values():
        filesystem.ensure_dir(paths.objects / collection)
    for directory in (
        paths.events,
        paths.refs,
        paths.state,
        paths.locks,
        paths.conflicts,
        paths.backups,
        paths.transactions,
    ):
        filesystem.ensure_dir(directory)

    now = now_local()
    project = Project(
        id=new_id("project"),
        name=name or paths.root.name,
        slug=slugify(slug or name or paths.root.name),
        description=description,
        status=ProjectStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    record = project.to_record()
    record["rev"] = compute_rev(record)
    project.rev = record["rev"]
    filesystem.write_json(paths.project_json, record)
    filesystem.atomic_write_text(
        paths.config_toml,
        f'[project]\nschema_version = "{SCHEMA_VERSION}"\n',
    )
    filesystem.write_json(paths.labels_json, {"schema_version": SCHEMA_VERSION, "labels": []})

    local = load_local(paths)

    txn_id = new_id("transaction")
    event = Event(
        id=new_id("event"),
        transaction_id=txn_id,
        event_type="project.initialized",
        project_id=project.id,
        entity_type="project",
        entity_id=project.id,
        actor_id=None,
        device_id=local.device_id,
        occurred_at=now,
        new_rev=project.rev,
        payload={"name": project.name, "slug": project.slug},
    )
    filesystem.write_json(paths.event_dir(now) / f"{event.id}.json", event.to_record())

    _append_gitignore(paths.root)
    write_state(paths, last_transaction_id=txn_id)

    return OpenedProject(paths=paths, project=project, config=_read_config(paths), local=local)


def open_project(root: str | Path | None = None) -> OpenedProject:
    paths = require_paths(root)
    try:
        raw = filesystem.read_json(paths.project_json)
        project = Project.model_validate(raw)
    except ProjectCorrupted:
        raise
    except (ValidationError, ValueError) as exc:
        raise ProjectCorrupted(f"cannot parse project.json: {exc}") from exc

    major = str(project.schema_version).split(".")[0]
    if major != SCHEMA_VERSION.split(".")[0]:
        raise SchemaUnsupported(
            f"project schema_version={project.schema_version} is not supported "
            f"by this tool (supports {SCHEMA_VERSION}.x); refusing to touch data"
        )

    return OpenedProject(
        paths=paths,
        project=project,
        config=_read_config(paths),
        local=load_local(paths),
    )


def write_state(paths: ProjectPaths, last_transaction_id: str | None = None) -> None:
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_local().isoformat(),
        "object_count": count_objects(paths),
        "event_count": count_events(paths),
    }
    if last_transaction_id:
        state["last_transaction_id"] = last_transaction_id
    filesystem.write_json(paths.state_json, state)


def count_objects(paths: ProjectPaths) -> int:
    total = 0
    if paths.objects.is_dir():
        for collection in paths.objects.iterdir():
            if collection.is_dir():
                total += sum(1 for _ in collection.glob("*.json"))
    return total


def count_events(paths: ProjectPaths) -> int:
    if not paths.events.is_dir():
        return 0
    return sum(1 for _ in paths.events.rglob("EVT-*.json"))


def _read_config(paths: ProjectPaths) -> dict[str, Any]:
    if not paths.config_toml.is_file():
        return {}
    try:
        return tomllib.loads(paths.config_toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProjectCorrupted(f"cannot parse config.toml: {exc}") from exc


def ensure_gitignore(root: Path) -> list[str]:
    """把 Project Tool 需要的 ignore 规则补进项目根的 `.gitignore`（幂等）。

    返回本次真正新增的行。老项目规则已在（V0/V0.1 写的 local/transactions）
    时只补新增的那些，不会重复写注释块。
    """
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    lines = existing.splitlines()
    added: list[str] = []
    for header, group in GITIGNORE_GROUPS:
        missing = [line for line in group if line not in lines]
        if not missing:
            continue
        if existing.strip():
            if not existing.endswith("\n"):
                existing += "\n"
            existing += "\n"
        if header not in lines:
            existing += header + "\n"
        existing += "\n".join(missing) + "\n"
        lines.extend(missing)
        added.extend(missing)
    if added:
        filesystem.atomic_write_text(gitignore, existing)
    return added


def _append_gitignore(root: Path) -> None:
    ensure_gitignore(root)
