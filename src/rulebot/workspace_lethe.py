from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from .workspace_grep import GrepRequest, GrepResponse
from .workspace_records import Observation, WorkspaceRecord


class LetheProjectionApi(Protocol):
    def grep(self, projection_id: str, request: GrepRequest, *, slack_user_id: str = "") -> GrepResponse:
        ...

    def get_record(self, projection_id: str, record_id: str, *, slack_user_id: str = "") -> WorkspaceRecord:
        ...

    def get_thread(
        self,
        projection_id: str,
        *,
        thread_ts: str = "",
        permalink: str = "",
        slack_user_id: str = "",
    ) -> list[WorkspaceRecord]:
        ...

    def resolve_link(self, projection_id: str, url: str, *, slack_user_id: str = "") -> WorkspaceRecord:
        ...


class LetheLakeWriter(Protocol):
    def put_observation(self, observation: Observation) -> bool:
        ...


class HttpLetheClient:
    def __init__(self, base_url: str, service_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token if service_token is not None else os.environ.get("LETHE_SERVICE_TOKEN", "")
        if not self.service_token:
            raise ValueError("LETHE_SERVICE_TOKEN must not be empty")

    def grep(self, projection_id: str, request: GrepRequest, *, slack_user_id: str = "") -> GrepResponse:
        from .workspace_grep import GrepMatch, GrepResponse

        data = self._request_json(
            "POST",
            f"/api/projections/{urllib.parse.quote(projection_id)}/grep",
            {
                "pattern": request.pattern,
                "limit": request.limit,
                "cursor": request.cursor,
                "timeout_ms": request.timeout_ms,
                "order": request.order,
                "filters": {
                    "types": sorted(request.filters.types),
                    "channel_ids": sorted(request.filters.channel_ids),
                    "container_ids": sorted(request.filters.container_ids),
                    "from": request.filters.from_ts,
                    "to": request.filters.to_ts,
                },
            },
            slack_user_id=slack_user_id,
        )
        return GrepResponse(
            matches=[
                GrepMatch(
                    record_id=str(item["record_id"]),
                    source_type=str(item["source_type"]),
                    anchor_url=str(item["anchor_url"]),
                    source_title=str(item.get("source_title", "")),
                    source_location=str(item.get("source_location", "")),
                    timestamp=str(item.get("timestamp", "")),
                    snippet=str(item.get("snippet", "")),
                    matched_ranges=[(int(start), int(end)) for start, end in item.get("matched_ranges", [])],
                    metadata=dict(item.get("metadata", {})),
                )
                for item in data.get("matches", [])
            ],
            next_cursor=str(data.get("next_cursor", "")),
            complete=bool(data.get("complete", True)),
            projection_watermark=str(data.get("projection_watermark", "")),
        )

    def get_record(self, projection_id: str, record_id: str, *, slack_user_id: str = "") -> WorkspaceRecord:
        data = self._request_json(
            "GET",
            f"/api/projections/{urllib.parse.quote(projection_id)}/records/{urllib.parse.quote(record_id)}",
            None,
            slack_user_id=slack_user_id,
        )
        return WorkspaceRecord.from_dict(data)

    def get_thread(
        self,
        projection_id: str,
        *,
        thread_ts: str = "",
        permalink: str = "",
        slack_user_id: str = "",
    ) -> list[WorkspaceRecord]:
        query = urllib.parse.urlencode({"thread_ts": thread_ts, "permalink": permalink})
        data = self._request_json(
            "GET",
            f"/api/projections/{urllib.parse.quote(projection_id)}/threads?{query}",
            None,
            slack_user_id=slack_user_id,
        )
        return [WorkspaceRecord.from_dict(item) for item in data.get("records", [])]

    def resolve_link(self, projection_id: str, url: str, *, slack_user_id: str = "") -> WorkspaceRecord:
        data = self._request_json(
            "POST",
            f"/api/projections/{urllib.parse.quote(projection_id)}/resolve-link",
            {"url": url},
            slack_user_id=slack_user_id,
        )
        return WorkspaceRecord.from_dict(data)

    def put_observation(self, observation: Observation) -> bool:
        data = self._request_json("POST", "/api/lake/observations", observation.to_dict(), slack_user_id="")
        return bool(data.get("created", True))

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        *,
        slack_user_id: str,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.service_token}",
                "Content-Type": "application/json; charset=utf-8",
                "X-Slack-User-Id": slack_user_id,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LETHE API returned {exc.code}: {detail}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("LETHE API returned non-object JSON")
        return data


class MemoryLetheClient:
    def __init__(self) -> None:
        self.observations: dict[str, Observation] = {}

    def put_observation(self, observation: Observation) -> bool:
        created = observation.idempotency_key not in self.observations
        self.observations.setdefault(observation.idempotency_key, observation)
        return created
