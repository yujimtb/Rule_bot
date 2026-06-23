from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Literal


SourceType = Literal[
    "slack",
    "doc",
    "sheet",
    "form",
    "form_response",
    "slide",
    "drive_file",
]


SHARING_ORDER = {
    "private": 0,
    "restricted": 0,
    "group": 1,
    "domain": 2,
    "anyone_with_link": 3,
    "public": 4,
}


@dataclass(frozen=True)
class WorkspaceRecord:
    record_id: str
    source_type: SourceType
    text: str
    anchor_url: str
    timestamp: str
    source_title: str = ""
    source_location: str = ""
    container_id: str = ""
    author_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_text(self, text: str, *, metadata: dict[str, Any] | None = None) -> "WorkspaceRecord":
        return replace(self, text=text, metadata=self.metadata if metadata is None else metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_type": self.source_type,
            "text": self.text,
            "anchor_url": self.anchor_url,
            "timestamp": self.timestamp,
            "source_title": self.source_title,
            "source_location": self.source_location,
            "container_id": self.container_id,
            "author_id": self.author_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceRecord":
        source_type = str(data["source_type"])
        if source_type not in {"slack", "doc", "sheet", "form", "form_response", "slide", "drive_file"}:
            raise ValueError(f"unsupported source_type: {source_type}")
        return cls(
            record_id=str(data["record_id"]),
            source_type=source_type,  # type: ignore[arg-type]
            text=str(data.get("text", "")),
            anchor_url=str(data.get("anchor_url", "")),
            timestamp=str(data.get("timestamp", "")),
            source_title=str(data.get("source_title", "")),
            source_location=str(data.get("source_location", "")),
            container_id=str(data.get("container_id", "")),
            author_id=str(data.get("author_id", "")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class Observation:
    schema: str
    source: str
    idempotency_key: str
    record: WorkspaceRecord
    source_revision_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source": self.source,
            "idempotency_key": self.idempotency_key,
            "source_revision_id": self.source_revision_id,
            "record": self.record.to_dict(),
        }


def stable_record_id(prefix: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def sharing_satisfies(level: str, threshold: str) -> bool:
    if threshold not in SHARING_ORDER:
        raise ValueError(f"unknown sharing threshold: {threshold}")
    return SHARING_ORDER.get(level, -1) >= SHARING_ORDER[threshold]
