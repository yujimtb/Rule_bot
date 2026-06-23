from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .workspace_config import DriveCrawlConfig
from .workspace_lethe import LetheLakeWriter
from .workspace_records import Observation, WorkspaceRecord, stable_record_id


WORKSPACE_OBJECT_SNAPSHOT_SCHEMA = "workspace-object-snapshot"


class DriveApi(Protocol):
    def list_files(self, *, folder_ids: set[str]) -> list[dict[str, Any]]:
        ...


class WorkspaceApi(Protocol):
    def get_document(self, file_id: str) -> dict[str, Any]:
        ...

    def get_sheet(self, file_id: str) -> dict[str, Any]:
        ...

    def get_form(self, file_id: str) -> dict[str, Any]:
        ...

    def get_slides(self, file_id: str) -> dict[str, Any]:
        ...

    def get_file_text(self, file_id: str) -> str:
        ...


@dataclass
class RevisionTracker:
    seen_revisions: dict[str, str] = field(default_factory=dict)

    def changed(self, file_id: str, revision_id: str) -> bool:
        return self.seen_revisions.get(file_id) != revision_id

    def mark_seen(self, file_id: str, revision_id: str) -> None:
        self.seen_revisions[file_id] = revision_id


class DriveCrawler:
    def __init__(
        self,
        writer: LetheLakeWriter,
        config: DriveCrawlConfig,
        *,
        revision_tracker: RevisionTracker | None = None,
    ):
        self.writer = writer
        self.config = config
        self.revision_tracker = revision_tracker or RevisionTracker()

    def crawl(self, drive_api: DriveApi, workspace_api: WorkspaceApi) -> int:
        created = 0
        files = drive_api.list_files(folder_ids=set(self.config.allowed_folder_ids))
        for file_info in files:
            file_id = str(file_info["id"])
            revision_id = str(file_info.get("revisionId", file_info.get("modifiedTime", "")))
            if revision_id and not self.revision_tracker.changed(file_id, revision_id):
                continue
            for observation in observations_from_drive_file(file_info, workspace_api):
                if self.writer.put_observation(observation):
                    created += 1
            if revision_id:
                self.revision_tracker.mark_seen(file_id, revision_id)
        return created


def observations_from_drive_file(file_info: dict[str, Any], workspace_api: WorkspaceApi) -> list[Observation]:
    mime_type = str(file_info.get("mimeType", ""))
    file_id = str(file_info["id"])
    if mime_type.endswith("document"):
        data = workspace_api.get_document(file_id)
        return [_doc_observation(file_info, data)]
    if mime_type.endswith("spreadsheet"):
        data = workspace_api.get_sheet(file_id)
        return _sheet_observations(file_info, data)
    if mime_type.endswith("form"):
        data = workspace_api.get_form(file_id)
        return _form_observations(file_info, data)
    if mime_type.endswith("presentation"):
        data = workspace_api.get_slides(file_id)
        return _slide_observations(file_info, data)
    text = workspace_api.get_file_text(file_id)
    return [_generic_file_observation(file_info, text)]


def _doc_observation(file_info: dict[str, Any], data: dict[str, Any]) -> Observation:
    text = "\n".join([str(data.get("title", "")), *[str(item) for item in data.get("headings", [])], str(data.get("body", ""))])
    return _snapshot(file_info, "doc", text, str(data.get("url", file_info.get("webViewLink", ""))), metadata={"links": data.get("links", [])})


def _sheet_observations(file_info: dict[str, Any], data: dict[str, Any]) -> list[Observation]:
    headers = [str(item) for item in data.get("headers", [])]
    rows = data.get("rows", [])
    observations: list[Observation] = []
    for index, row in enumerate(rows):
        values = [str(item) for item in row]
        text = " | ".join(f"{header}: {value}" for header, value in zip(headers, values, strict=False))
        observations.append(_snapshot(file_info, "sheet", text, str(data.get("url", file_info.get("webViewLink", ""))), location=f"row {index + 1}"))
    return observations


def _form_observations(file_info: dict[str, Any], data: dict[str, Any]) -> list[Observation]:
    questions = [str(item) for item in data.get("questions", [])]
    text = "\n".join([str(data.get("title", "")), str(data.get("description", "")), *questions])
    observations = [_snapshot(file_info, "form", text, str(data.get("url", file_info.get("webViewLink", ""))))]
    for response in data.get("responses", []):
        responder = str(response.get("responder_id") or response.get("responder_email", "unknown"))
        timestamp = str(response.get("timestamp", file_info.get("modifiedTime", "")))
        observations.append(
            _snapshot(
                file_info,
                "form_response",
                str(response.get("answers", {})),
                str(data.get("url", file_info.get("webViewLink", ""))),
                timestamp=timestamp,
                metadata={
                    "responder_id": responder,
                    "responder_email": response.get("responder_email", ""),
                    "answers": response.get("answers", {}),
                    "form_title": data.get("title", file_info.get("name", "")),
                },
            )
        )
    return observations


def _slide_observations(file_info: dict[str, Any], data: dict[str, Any]) -> list[Observation]:
    observations: list[Observation] = []
    for slide in data.get("slides", []):
        slide_id = str(slide.get("id", len(observations) + 1))
        text = "\n".join(str(item) for item in slide.get("text_blocks", []))
        observations.append(_snapshot(file_info, "slide", text, str(data.get("url", file_info.get("webViewLink", ""))), location=slide_id))
    return observations


def _generic_file_observation(file_info: dict[str, Any], text: str) -> Observation:
    return _snapshot(file_info, "drive_file", text, str(file_info.get("webViewLink", "")))


def _snapshot(
    file_info: dict[str, Any],
    source_type: str,
    text: str,
    url: str,
    *,
    location: str = "",
    timestamp: str = "",
    metadata: dict[str, Any] | None = None,
) -> Observation:
    file_id = str(file_info["id"])
    revision_id = str(file_info.get("revisionId", file_info.get("modifiedTime", "")))
    payload = {"file_id": file_id, "source_type": source_type, "location": location, "revision": revision_id, "text": text}
    merged_metadata = {
        "file_id": file_id,
        "folder_ids": [str(item) for item in file_info.get("parents", [])],
        "sharing_level": str(file_info.get("sharing_level", "private")),
        "owner_id": str(file_info.get("owner_id", "")),
        "sourceRevisionId": revision_id,
        "is_form_response_sheet": bool(file_info.get("is_form_response_sheet", False)),
    }
    merged_metadata.update(metadata or {})
    record = WorkspaceRecord(
        record_id=stable_record_id(source_type, payload),
        source_type=source_type,  # type: ignore[arg-type]
        text=text,
        anchor_url=url,
        timestamp=timestamp or str(file_info.get("modifiedTime", "")),
        source_title=str(file_info.get("name", "")),
        source_location=location,
        container_id=file_id,
        author_id=str(file_info.get("owner_id", "")),
        metadata=merged_metadata,
    )
    return Observation(
        schema=WORKSPACE_OBJECT_SNAPSHOT_SCHEMA,
        source="google-workspace",
        idempotency_key=f"drive:{file_id}:{source_type}:{location}:{revision_id}:{record.record_id}",
        record=record,
        source_revision_id=revision_id,
    )
