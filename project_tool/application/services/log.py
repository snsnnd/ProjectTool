"""log.* 方法。"""

from __future__ import annotations

from typing import Any

import project_tool.application.queries as queries
from project_tool.application.context import ServiceContext


class LogService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    def log_list(self, **filters) -> dict[str, Any]:
        return queries.log_list(self.ctx, **filters)

    def log_get(self, event_id) -> dict[str, Any]:
        return self.ctx.events.get(event_id)

    def log_entity(self, entity_type, entity_id, **rest) -> dict[str, Any]:
        return queries.log_list(self.ctx, entity_type=entity_type, entity_id=entity_id, **rest)

    def log_member(self, member, **rest) -> dict[str, Any]:
        return queries.log_list(self.ctx, member=member, **rest)

    def log_since(self, since, **rest) -> dict[str, Any]:
        return queries.log_list(self.ctx, since=since, **rest)
