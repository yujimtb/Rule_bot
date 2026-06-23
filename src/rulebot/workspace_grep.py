from __future__ import annotations

import base64
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .workspace_records import WorkspaceRecord


UNSAFE_REGEX_RE = re.compile(r"(\\[1-9]|\(\?<?[=!])")


@dataclass(frozen=True)
class GrepFilters:
    types: frozenset[str] = frozenset()
    channel_ids: frozenset[str] = frozenset()
    container_ids: frozenset[str] = frozenset()
    from_ts: str = ""
    to_ts: str = ""


@dataclass(frozen=True)
class GrepRequest:
    pattern: str
    limit: int = 100
    cursor: str = ""
    filters: GrepFilters = field(default_factory=GrepFilters)
    timeout_ms: int = 500
    order: str = "date_desc"


@dataclass(frozen=True)
class GrepMatch:
    record_id: str
    source_type: str
    anchor_url: str
    source_title: str
    source_location: str
    timestamp: str
    snippet: str
    matched_ranges: list[tuple[int, int]]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_type": self.source_type,
            "anchor_url": self.anchor_url,
            "source_title": self.source_title,
            "source_location": self.source_location,
            "timestamp": self.timestamp,
            "snippet": self.snippet,
            "matched_ranges": [[start, end] for start, end in self.matched_ranges],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class GrepResponse:
    matches: list[GrepMatch]
    next_cursor: str
    complete: bool
    projection_watermark: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "matches": [match.to_dict() for match in self.matches],
            "next_cursor": self.next_cursor,
            "complete": self.complete,
            "projection_watermark": self.projection_watermark,
        }


class GrepIndex:
    def __init__(self, records: list[WorkspaceRecord], *, projection_watermark: str = ""):
        self.records = sorted(records, key=lambda record: record.timestamp, reverse=True)
        self.projection_watermark = projection_watermark
        self._normalized = {record.record_id: normalize_text(record.text) for record in self.records}
        self.trigram_index = self._build_trigram_index()
        self.by_id = {record.record_id: record for record in self.records}

    def grep(self, request: GrepRequest) -> GrepResponse:
        if not request.pattern.strip():
            raise ValueError("pattern must not be empty")
        if request.limit <= 0:
            raise ValueError("limit must be positive")
        if request.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        if request.order != "date_desc":
            raise ValueError("only date_desc order is supported")
        if UNSAFE_REGEX_RE.search(request.pattern):
            raise ValueError("regex pattern uses unsupported non-linear features")

        regex = re.compile(normalize_text(request.pattern), re.IGNORECASE)
        offset = _decode_cursor(request.cursor)
        candidates = self._filtered_records(request.filters)
        deadline = time.monotonic() + request.timeout_ms / 1000
        matches: list[GrepMatch] = []
        next_offset = len(candidates)

        for index in range(offset, len(candidates)):
            if time.monotonic() > deadline:
                raise TimeoutError("grep execution timed out")
            record = candidates[index]
            text = self._normalized[record.record_id]
            found = list(regex.finditer(text))
            if not found:
                continue
            matches.append(_match_from_record(record, found))
            if len(matches) >= request.limit:
                next_offset = index + 1
                break

        complete = next_offset >= len(candidates)
        return GrepResponse(
            matches=matches,
            next_cursor="" if complete else _encode_cursor(next_offset),
            complete=complete,
            projection_watermark=self.projection_watermark,
        )

    def get_record(self, record_id: str) -> WorkspaceRecord | None:
        return self.by_id.get(record_id)

    def get_thread(self, *, thread_ts: str = "", permalink: str = "") -> list[WorkspaceRecord]:
        return [
            record
            for record in self.records
            if record.source_type == "slack"
            and (
                (thread_ts and str(record.metadata.get("thread_ts", "")) == thread_ts)
                or (permalink and record.anchor_url.startswith(permalink))
            )
        ]

    def resolve_link(self, url: str) -> WorkspaceRecord | None:
        for record in self.records:
            if record.anchor_url == url or url.startswith(record.anchor_url) or record.anchor_url.startswith(url):
                return record
        return None

    def _filtered_records(self, filters: GrepFilters) -> list[WorkspaceRecord]:
        records = self.records
        if filters.types:
            records = [record for record in records if record.source_type in filters.types]
        if filters.channel_ids:
            records = [record for record in records if record.container_id in filters.channel_ids]
        if filters.container_ids:
            records = [record for record in records if record.container_id in filters.container_ids]
        if filters.from_ts:
            records = [record for record in records if record.timestamp >= filters.from_ts]
        if filters.to_ts:
            records = [record for record in records if record.timestamp <= filters.to_ts]
        return records

    def _build_trigram_index(self) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for record in self.records:
            text = self._normalized[record.record_id]
            for pos in range(max(0, len(text) - 2)):
                gram = text[pos : pos + 3]
                if gram.strip():
                    index.setdefault(gram, set()).add(record.record_id)
        return index


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def request_from_dict(data: dict[str, Any]) -> GrepRequest:
    filters_data = data.get("filters", {})
    if not isinstance(filters_data, dict):
        raise ValueError("filters must be a mapping")
    return GrepRequest(
        pattern=str(data.get("pattern", "")),
        limit=int(data.get("limit", 100)),
        cursor=str(data.get("cursor", "")),
        timeout_ms=int(data.get("timeout_ms", 500)),
        order=str(data.get("order", "date_desc")),
        filters=GrepFilters(
            types=frozenset(str(item) for item in filters_data.get("types", [])),
            channel_ids=frozenset(str(item) for item in filters_data.get("channel_ids", [])),
            container_ids=frozenset(str(item) for item in filters_data.get("container_ids", [])),
            from_ts=str(filters_data.get("from", "")),
            to_ts=str(filters_data.get("to", "")),
        ),
    )


def _match_from_record(record: WorkspaceRecord, found: list[re.Match[str]]) -> GrepMatch:
    first = found[0]
    ranges = [(match.start(), match.end()) for match in found]
    snippet = _snippet(record.text, first.start(), first.end())
    return GrepMatch(
        record_id=record.record_id,
        source_type=record.source_type,
        anchor_url=record.anchor_url,
        source_title=record.source_title,
        source_location=record.source_location,
        timestamp=record.timestamp,
        snippet=snippet,
        matched_ranges=ranges,
        metadata=record.metadata,
    )


def _snippet(text: str, start: int, end: int, *, radius: int = 80) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = "..." if left else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}".replace("\n", " ").strip()


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> int:
    if not cursor:
        return 0
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        offset = int(data["offset"])
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid cursor") from exc
    if offset < 0:
        raise ValueError("invalid cursor")
    return offset
