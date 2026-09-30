"""member.* 方法。"""

from __future__ import annotations

from typing import Any, cast

import project_tool.application.queries as queries
from project_tool.application.context import HANDLE_RE, ServiceContext, as_list, dedupe
from project_tool.domain.enums import Lifecycle
from project_tool.domain.errors import AlreadyExists, InvalidArgument
from project_tool.domain.ids import new_id
from project_tool.domain.member import GitIdentity, Member
from project_tool.domain.timeutil import now_local
from project_tool.domain.validation import check_handle, optional_title


class MemberService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    def member_add(
        self,
        handle,
        display_name=None,
        roles=None,
        git_names=None,
        git_emails=None,
        external_ids=None,
    ) -> dict[str, Any]:
        normalized = check_handle(handle)
        if not HANDLE_RE.match(normalized):
            raise InvalidArgument(
                f"invalid handle {handle!r}: use lowercase letters, digits, '.', '_' or '-'"
            )
        if self.ctx.store.find_by_handle(normalized) is not None:
            raise AlreadyExists(f"member handle {normalized!r} already exists")
        name_text = (
            optional_title(display_name, "display_name") if display_name else normalized
        )
        now = now_local()
        member = Member(
            id=new_id("member"),
            project_id=self.ctx.opened.project.id,
            display_name=name_text,
            handle=normalized,
            roles=dedupe([str(role) for role in as_list(roles)]),
            git=GitIdentity(
                names=dedupe([str(name) for name in as_list(git_names)]),
                emails=dedupe([str(email) for email in as_list(git_emails)]),
            ),
            external_ids={str(key): str(value) for key, value in dict(external_ids or {}).items()},
            active=True,
            created_at=now,
            updated_at=now,
        )
        record = self.ctx.save(
            member, None, "member.added", {"handle": member.handle}, is_create=True
        )
        if self.ctx.opened.local.actor is None:
            self.ctx.opened.local.actor = member.id
            self.ctx.opened.save_local()
        return record

    def member_get(self, member) -> dict[str, Any]:
        return self.ctx.load("member", self.ctx.member_id(member)).model_dump(mode="json")

    def member_list(
        self,
        include_inactive=True,
        include_archived=False,
        include_deleted=False,
    ) -> list[dict[str, Any]]:
        result = []
        for model in self.ctx.store.list_models("member", include_deleted=include_deleted):
            member = cast(Member, model)
            if member.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if member.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if not include_inactive and not member.active:
                continue
            result.append(member.model_dump(mode="json"))
        return result

    def member_update(
        self,
        member,
        display_name=None,
        roles=None,
        git_names=None,
        git_emails=None,
        external_ids=None,
        active=None,
        expected_rev=None,
    ) -> dict[str, Any]:
        loaded = self.ctx.load("member", self.ctx.member_id(member))
        base = self.ctx.require_expected_rev("member", loaded, expected_rev)
        fields: list[str] = []
        if display_name is not None:
            loaded.display_name = optional_title(display_name, "display_name")
            fields.append("display_name")
        if roles is not None:
            loaded.roles = dedupe([str(role) for role in as_list(roles)])
            fields.append("roles")
        if git_names is not None:
            loaded.git.names = dedupe([str(name) for name in as_list(git_names)])
            fields.append("git.names")
        if git_emails is not None:
            loaded.git.emails = dedupe([str(email) for email in as_list(git_emails)])
            fields.append("git.emails")
        if external_ids is not None:
            loaded.external_ids = {
                str(key): str(value) for key, value in dict(external_ids).items()
            }
            fields.append("external_ids")
        if active is not None:
            loaded.active = bool(active)
            fields.append("active")
        if not fields:
            return loaded.model_dump(mode="json")
        return self.ctx.save(loaded, base, "member.updated", {"fields": fields})

    def member_deactivate(self, member, expected_rev=None) -> dict[str, Any]:
        loaded = self.ctx.load("member", self.ctx.member_id(member))
        base = self.ctx.require_expected_rev("member", loaded, expected_rev)
        if not loaded.active:
            return loaded.model_dump(mode="json")
        loaded.active = False
        return self.ctx.save(loaded, base, "member.deactivated", {})

    def member_activate(self, member, expected_rev=None) -> dict[str, Any]:
        loaded = self.ctx.load("member", self.ctx.member_id(member))
        base = self.ctx.require_expected_rev("member", loaded, expected_rev)
        if loaded.active:
            return loaded.model_dump(mode="json")
        loaded.active = True
        return self.ctx.save(loaded, base, "member.activated", {})

    def member_workload(self, member) -> dict[str, Any]:
        return queries.member_workload(self.ctx, self.ctx.member_id(member))

    def member_activity(self, member, limit=20) -> dict[str, Any]:
        return queries.log_list(self.ctx, member=member, limit=limit)

    def member_use(self, member) -> dict[str, Any]:
        member_id = self.ctx.member_id(member)
        record = self.ctx.store.get_raw("member", member_id)
        self.ctx.opened.local.actor = member_id
        self.ctx.opened.save_local()
        self.ctx.actor_id = member_id
        return {"actor": member_id, "handle": record.get("handle") if record else None}

    def member_map_git_identity(
        self, member, name=None, email=None, expected_rev=None
    ) -> dict[str, Any]:
        loaded = self.ctx.load("member", self.ctx.member_id(member))
        base = self.ctx.require_expected_rev("member", loaded, expected_rev)
        if name and str(name) not in loaded.git.names:
            loaded.git.names.append(str(name))
        if email and str(email) not in loaded.git.emails:
            loaded.git.emails.append(str(email))
        return self.ctx.save(loaded, base, "member.updated", {"fields": ["git"]})
