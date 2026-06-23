from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .workspace_answer_log import JsonlAnswerLog
from .workspace_grep import GrepFilters, GrepRequest
from .workspace_lethe import LetheProjectionApi


@dataclass(frozen=True)
class McpToolLimits:
    grep_limit: int = 50


class WorkspaceMcpTools:
    def __init__(
        self,
        lethe: LetheProjectionApi,
        *,
        projection_id: str,
        answer_log: JsonlAnswerLog | None = None,
        limits: McpToolLimits | None = None,
    ):
        self.lethe = lethe
        self.projection_id = projection_id
        self.answer_log = answer_log
        self.limits = limits or McpToolLimits()

    def grep_search(
        self,
        pattern: str,
        *,
        filters: dict[str, Any] | None = None,
        cursor: str = "",
        slack_user_id: str = "",
    ) -> dict[str, Any]:
        filters = filters or {}
        response = self.lethe.grep(
            self.projection_id,
            GrepRequest(
                pattern=pattern,
                limit=self.limits.grep_limit,
                cursor=cursor,
                filters=GrepFilters(
                    types=frozenset(str(item) for item in filters.get("types", [])),
                    channel_ids=frozenset(str(item) for item in filters.get("channel_ids", [])),
                    container_ids=frozenset(str(item) for item in filters.get("container_ids", [])),
                    from_ts=str(filters.get("from", "")),
                    to_ts=str(filters.get("to", "")),
                ),
            ),
            slack_user_id=slack_user_id,
        )
        return response.to_dict()

    def get_record(self, record_id: str, *, slack_user_id: str = "") -> dict[str, Any]:
        return self.lethe.get_record(self.projection_id, record_id, slack_user_id=slack_user_id).to_dict()

    def get_thread(self, *, thread_ts: str = "", permalink: str = "", slack_user_id: str = "") -> dict[str, Any]:
        records = self.lethe.get_thread(
            self.projection_id,
            thread_ts=thread_ts,
            permalink=permalink,
            slack_user_id=slack_user_id,
        )
        return {"records": [record.to_dict() for record in records]}

    def resolve_link(self, url: str, *, slack_user_id: str = "") -> dict[str, Any]:
        return self.lethe.resolve_link(self.projection_id, url, slack_user_id=slack_user_id).to_dict()

    def prior_qa_search(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        if self.answer_log is None:
            return {"primary_source": False, "results": []}
        return {
            "primary_source": False,
            "message": "prior_qa_search results are scaffolding only; re-verify citations against primary sources.",
            "results": [entry.to_dict() for entry in self.answer_log.search(query, limit=limit)],
        }
