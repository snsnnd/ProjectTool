"""领域枚举：所有对象的状态与类型常量。"""

from __future__ import annotations

from enum import StrEnum


class Lifecycle(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ProjectStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class GoalStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    ACHIEVED = "achieved"
    DROPPED = "dropped"


class MilestoneStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    INBOX = "inbox"
    READY = "ready"
    DOING = "doing"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class DecisionStatus(StrEnum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class DependencyRelation(StrEnum):
    DEPENDS_ON = "depends_on"
    RELATES_TO = "relates_to"
    DUPLICATES = "duplicates"


class LinkKind(StrEnum):
    LOCAL_PROJECT = "local_project"
    REMOTE_PROJECT = "remote_project"
    GIT_REPOSITORY = "git_repository"
    EXTERNAL = "external"


class LinkMode(StrEnum):
    REFERENCE = "reference"
    AGGREGATE = "aggregate"


class ArtifactKind(StrEnum):
    FILE = "file"
    URL = "url"
    GIT_COMMIT = "git_commit"
    GIT_BRANCH = "git_branch"
    RELEASE = "release"
    BUILD = "build"
    REPORT = "report"
    DATASET = "dataset"
    MODEL = "model"
    DOCUMENT = "document"
    DESIGN = "design"
    HARDWARE = "hardware"
    IMAGE = "image"
    OTHER = "other"


class ObjectType(StrEnum):
    PROJECT = "project"
    GOAL = "goal"
    MILESTONE = "milestone"
    TASK = "task"
    MEMBER = "member"
    UPDATE = "update"
    DECISION = "decision"
    ARTIFACT = "artifact"
    LINK = "link"
