from __future__ import annotations

import re

from .workspace_config import WorkspaceSearchConfig
from .workspace_records import WorkspaceRecord, sharing_satisfies


class AccessControlledProjection:
    def __init__(self, config: WorkspaceSearchConfig):
        self.config = config
        self._channel_allow_re = re.compile(config.channel_allow_regex)

    def project(self, records: list[WorkspaceRecord]) -> list[WorkspaceRecord]:
        projected: list[WorkspaceRecord] = []
        for record in records:
            exposed = self.project_one(record)
            if exposed is not None:
                projected.append(exposed)
        return projected

    def project_one(self, record: WorkspaceRecord) -> WorkspaceRecord | None:
        if record.source_type == "slack":
            return record if self._slack_visible(record) else None
        if record.source_type in {"doc", "sheet", "form", "form_response", "slide", "drive_file"}:
            return self._project_drive_record(record)
        return None

    def _slack_visible(self, record: WorkspaceRecord) -> bool:
        metadata = record.metadata
        if not bool(metadata.get("is_public_channel")):
            return False
        channel_name = str(metadata.get("channel_name", ""))
        channel_id = record.container_id
        if channel_id not in self.config.channel_opt_in and not self._channel_allow_re.search(channel_name):
            return False
        if self.config.exclude_bot_authors and bool(metadata.get("is_bot")):
            return False
        return record.author_id not in self.config.opt_out_person_ids

    def _project_drive_record(self, record: WorkspaceRecord) -> WorkspaceRecord | None:
        metadata = record.metadata
        if record.metadata.get("file_id") in self.config.excluded_drive_file_ids:
            return None
        if record.author_id in self.config.opt_out_person_ids or str(metadata.get("owner_id", "")) in self.config.opt_out_person_ids:
            return None
        folder_ids = {str(item) for item in metadata.get("folder_ids", [])}
        if self.config.allowed_folder_ids and not (folder_ids & set(self.config.allowed_folder_ids)):
            return None
        if not sharing_satisfies(str(metadata.get("sharing_level", "private")), self.config.broad_visibility_threshold):
            return None
        if self.config.exclude_form_response_sheets and bool(metadata.get("is_form_response_sheet")):
            return None
        if record.source_type == "form_response":
            return self._redact_form_response(record)
        return record

    def _redact_form_response(self, record: WorkspaceRecord) -> WorkspaceRecord:
        metadata = dict(record.metadata)
        responder = str(metadata.get("responder_id") or metadata.get("responder_email") or "unknown")
        form_title = str(metadata.get("form_title") or record.source_title or "Form")
        answered_at = record.timestamp
        safe_text = f"{responder} answered {form_title} at {answered_at}."
        metadata.pop("answers", None)
        metadata["form_response_content_redacted"] = True
        return record.with_text(safe_text, metadata=metadata)
