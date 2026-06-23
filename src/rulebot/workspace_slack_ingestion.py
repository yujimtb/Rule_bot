from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .workspace_config import SlackIngestionConfig
from .workspace_lethe import LetheLakeWriter
from .workspace_records import Observation, WorkspaceRecord, stable_record_id


class SlackHistoryClient(Protocol):
    def conversations_history(
        self,
        *,
        channel: str,
        cursor: str = "",
        oldest: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class IngestionStatus:
    channel_id: str
    last_ingested_ts: str
    next_run_at: str
    failure_count: int = 0


class SlackIngestor:
    def __init__(self, writer: LetheLakeWriter, config: SlackIngestionConfig | None = None):
        self.writer = writer
        self.config = config or SlackIngestionConfig()
        self.status: dict[str, IngestionStatus] = {}

    def ingest_export(self, export_dir: str | Path) -> int:
        created = 0
        for path in sorted(Path(export_dir).glob("**/*.json")):
            if path.name in {"channels.json", "users.json", "integration_logs.json"}:
                continue
            channel_name = path.parent.name
            messages = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(messages, list):
                continue
            for message in messages:
                observation = observation_from_slack_message(message, channel_id=channel_name, channel_name=channel_name)
                if self.writer.put_observation(observation):
                    created += 1
        return created

    def poll_channel(self, client: SlackHistoryClient, *, channel_id: str, channel_name: str, oldest: str = "") -> int:
        cursor = ""
        created = 0
        latest_ts = oldest
        failures = 0
        try:
            while True:
                page = client.conversations_history(channel=channel_id, cursor=cursor, oldest=oldest, limit=200)
                for message in page.get("messages", []):
                    observation = observation_from_slack_message(message, channel_id=channel_id, channel_name=channel_name)
                    if self.writer.put_observation(observation):
                        created += 1
                    latest_ts = max(latest_ts, str(message.get("ts", latest_ts)))
                cursor = str(page.get("response_metadata", {}).get("next_cursor", ""))
                if not cursor:
                    break
        except Exception:
            failures = self.status.get(channel_id, IngestionStatus(channel_id, oldest, "", 0)).failure_count + 1
            raise
        finally:
            self.status[channel_id] = IngestionStatus(
                channel_id=channel_id,
                last_ingested_ts=latest_ts,
                next_run_at=_next_run_iso(self.config.interval_for(channel_id)),
                failure_count=failures,
            )
        return created

    def status_for(self, channel_id: str) -> IngestionStatus | None:
        return self.status.get(channel_id)


def observation_from_slack_message(message: dict[str, Any], *, channel_id: str, channel_name: str) -> Observation:
    ts = str(message.get("ts", ""))
    thread_ts = str(message.get("thread_ts") or ts)
    message_id = str(message.get("client_msg_id") or message.get("subtype") or ts)
    idempotency = f"slack:{channel_id}:{ts}:{thread_ts}:{message_id}"
    payload = {"channel": channel_id, "ts": ts, "thread_ts": thread_ts, "message_id": message_id}
    user = str(message.get("user") or message.get("bot_id") or "")
    record = WorkspaceRecord(
        record_id=stable_record_id("slack", payload),
        source_type="slack",
        text=str(message.get("text", "")),
        anchor_url=str(message.get("permalink") or f"slack://channel/{channel_id}/p{ts.replace('.', '')}"),
        timestamp=ts,
        source_title=channel_name,
        source_location=thread_ts,
        container_id=channel_id,
        author_id=user,
        metadata={
            "channel_name": channel_name,
            "is_public_channel": bool(message.get("is_public_channel", True)),
            "is_bot": bool(message.get("bot_id")) or message.get("subtype") == "bot_message",
            "thread_ts": thread_ts,
            "raw_ts": ts,
        },
    )
    return Observation(schema="slack-message-v1", source="slack", idempotency_key=idempotency, record=record)


def _next_run_iso(interval_seconds: int) -> str:
    now = datetime.now(timezone.utc).timestamp()
    return datetime.fromtimestamp(now + interval_seconds, timezone.utc).isoformat()
