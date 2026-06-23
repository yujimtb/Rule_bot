from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CHANNEL_ALLOW_REGEX = r"^\d{3}_"


@dataclass(frozen=True)
class AgentLimits:
    max_tool_calls: int = 30
    max_wall_clock_seconds: float = 120.0
    max_grep_pages_per_query: int = 10
    max_records_loaded: int = 200

    def __post_init__(self) -> None:
        for name, value in (
            ("max_tool_calls", self.max_tool_calls),
            ("max_grep_pages_per_query", self.max_grep_pages_per_query),
            ("max_records_loaded", self.max_records_loaded),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_wall_clock_seconds <= 0:
            raise ValueError("max_wall_clock_seconds must be positive")


@dataclass(frozen=True)
class SlackIngestionConfig:
    global_interval_seconds: int = 900
    channel_interval_overrides: dict[str, int] = field(default_factory=dict)

    def interval_for(self, channel_id: str) -> int:
        return self.channel_interval_overrides.get(channel_id, self.global_interval_seconds)


@dataclass(frozen=True)
class DriveCrawlConfig:
    allowed_folder_ids: frozenset[str] = frozenset()
    crawl_interval_seconds: int = 86_400

    def __post_init__(self) -> None:
        if self.crawl_interval_seconds <= 0:
            raise ValueError("crawl_interval_seconds must be positive")


@dataclass(frozen=True)
class WorkspaceSearchConfig:
    channel_allow_regex: str = DEFAULT_CHANNEL_ALLOW_REGEX
    channel_opt_in: frozenset[str] = frozenset()
    exclude_bot_authors: bool = True
    opt_out_person_ids: frozenset[str] = frozenset()
    allowed_folder_ids: frozenset[str] = frozenset()
    broad_visibility_threshold: str = "domain"
    excluded_drive_file_ids: frozenset[str] = frozenset()
    exclude_form_response_sheets: bool = True
    show_internal_metadata_to_user: bool = False
    slack: SlackIngestionConfig = field(default_factory=SlackIngestionConfig)
    drive: DriveCrawlConfig = field(default_factory=DriveCrawlConfig)
    agent: AgentLimits = field(default_factory=AgentLimits)

    def __post_init__(self) -> None:
        try:
            re.compile(self.channel_allow_regex)
        except re.error as exc:
            raise ValueError("channel_allow_regex must be a valid regex") from exc


def load_workspace_search_config(path: str | Path) -> WorkspaceSearchConfig:
    data = _load_mapping(Path(path))
    if "workspace_search" in data:
        data = _require_mapping(data["workspace_search"], "workspace_search")
    return workspace_search_config_from_dict(data)


def workspace_search_config_from_dict(data: dict[str, Any]) -> WorkspaceSearchConfig:
    slack_data = _require_mapping(data.get("slack", {}), "slack")
    drive_data = _require_mapping(data.get("drive", {}), "drive")
    agent_data = _require_mapping(data.get("agent", {}), "agent")

    allowed_folder_ids = _string_set(
        data.get("allowed_folder_ids", drive_data.get("allowed_folder_ids", [])),
        "allowed_folder_ids",
    )
    drive_config = DriveCrawlConfig(
        allowed_folder_ids=frozenset(allowed_folder_ids),
        crawl_interval_seconds=int(drive_data.get("crawl_interval_seconds", 86_400)),
    )

    return WorkspaceSearchConfig(
        channel_allow_regex=str(data.get("channel_allow_regex", DEFAULT_CHANNEL_ALLOW_REGEX)),
        channel_opt_in=frozenset(_string_set(data.get("channel_opt_in", []), "channel_opt_in")),
        exclude_bot_authors=bool(data.get("exclude_bot_authors", True)),
        opt_out_person_ids=frozenset(_string_set(data.get("opt_out_person_ids", []), "opt_out_person_ids")),
        allowed_folder_ids=drive_config.allowed_folder_ids,
        broad_visibility_threshold=str(data.get("broad_visibility_threshold", "domain")),
        excluded_drive_file_ids=frozenset(_string_set(data.get("excluded_drive_file_ids", []), "excluded_drive_file_ids")),
        exclude_form_response_sheets=bool(data.get("exclude_form_response_sheets", True)),
        show_internal_metadata_to_user=bool(data.get("show_internal_metadata_to_user", False)),
        slack=SlackIngestionConfig(
            global_interval_seconds=int(slack_data.get("global_interval_seconds", 900)),
            channel_interval_overrides={
                str(key): int(value)
                for key, value in _require_mapping(
                    slack_data.get("channel_interval_overrides", {}),
                    "slack.channel_interval_overrides",
                ).items()
            },
        ),
        drive=drive_config,
        agent=AgentLimits(
            max_tool_calls=int(agent_data.get("max_tool_calls", 30)),
            max_wall_clock_seconds=float(agent_data.get("max_wall_clock_seconds", 120.0)),
            max_grep_pages_per_query=int(agent_data.get("max_grep_pages_per_query", 10)),
            max_records_loaded=int(agent_data.get("max_records_loaded", 200)),
        ),
    )


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = _parse_yaml_subset(text)
    return _require_mapping(data, str(path))


def _parse_yaml_subset(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, sep, raw_value = line.strip().partition(":")
        if not sep or not key:
            raise ValueError(f"unsupported YAML line: {raw_line}")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        value = raw_value.strip()
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value)
    return result


def _parse_scalar(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",")]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _string_set(value: Any, name: str) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list | tuple | set | frozenset):
        raise ValueError(f"{name} must be a list of strings")
    return {str(item) for item in value if str(item)}
