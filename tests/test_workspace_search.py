from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

from rulebot.workspace_agent import ComposedAnswer, WorkspaceSearchAgent, build_regex_patterns, is_human_trigger
from rulebot.workspace_answer_log import AnswerLogEntry, Citation, JsonlAnswerLog
from rulebot.workspace_api import GrepApi, make_grep_handler
from rulebot.workspace_config import DriveCrawlConfig, SlackIngestionConfig, load_workspace_search_config, workspace_search_config_from_dict
from rulebot.workspace_drive_crawl import DriveCrawler, RevisionTracker
from rulebot.workspace_grep import GrepFilters, GrepIndex, GrepRequest
from rulebot.workspace_lethe import HttpLetheClient, MemoryLetheClient
from rulebot.workspace_mcp import WorkspaceMcpTools
from rulebot.workspace_projection import AccessControlledProjection
from rulebot.workspace_records import WorkspaceRecord
from rulebot.workspace_slack_ingestion import SlackIngestor, observation_from_slack_message


class WorkspaceSearchTest(unittest.TestCase):
    def test_projection_exposes_only_allowed_slack_messages(self) -> None:
        config = workspace_search_config_from_dict({"opt_out_person_ids": ["U2"]})
        records = [
            slack_record("ok", "123_event", "U1"),
            slack_record("wrong-name", "general", "U1"),
            slack_record("bot", "123_event", "B1", is_bot=True),
            slack_record("opt-out", "123_event", "U2"),
            slack_record("private", "123_event", "U1", is_public=False),
        ]

        projected = AccessControlledProjection(config).project(records)

        self.assertEqual([record.text for record in projected], ["ok"])

    def test_projection_exposes_only_allowed_drive_files_and_redacts_form_responses(self) -> None:
        config = workspace_search_config_from_dict(
            {
                "allowed_folder_ids": ["F1"],
                "broad_visibility_threshold": "domain",
                "excluded_drive_file_ids": ["D4"],
                "opt_out_person_ids": ["U2"],
            }
        )
        records = [
            drive_record("D1", "doc", "domain", ["F1"], "U1", text="visible"),
            drive_record("D2", "doc", "private", ["F1"], "U1", text="private"),
            drive_record("D3", "doc", "domain", ["F2"], "U1", text="outside"),
            drive_record("D4", "doc", "domain", ["F1"], "U1", text="excluded"),
            drive_record("D5", "doc", "domain", ["F1"], "U2", text="optout"),
            drive_record("D6", "sheet", "domain", ["F1"], "U1", text="sheet", extra={"is_form_response_sheet": True}),
            drive_record(
                "D7",
                "form_response",
                "domain",
                ["F1"],
                "U1",
                text="secret answer",
                extra={"answers": {"q": "secret answer"}, "responder_id": "U9", "form_title": "RSVP"},
            ),
            drive_record(
                "D8",
                "form_response",
                "domain",
                ["F1"],
                "U1",
                text="submitted",
                extra={"responder_email": "user@example.com", "form_title": "Survey"},
            ),
        ]

        projected = AccessControlledProjection(config).project(records)

        self.assertEqual([record.metadata["file_id"] for record in projected], ["D1", "D7", "D8"])
        self.assertNotIn("secret answer", projected[1].text)
        self.assertTrue(projected[1].metadata["form_response_content_redacted"])
        self.assertNotIn("answers", projected[1].metadata)
        self.assertIn("user@example.com answered Survey", projected[2].text)

    def test_grep_uses_nfkc_paginates_filters_and_rejects_unsafe_regex(self) -> None:
        records = [
            WorkspaceRecord("r1", "slack", "ＡＢＣ 忘れ物", "https://slack/r1", "2026-01-02", container_id="C1"),
            WorkspaceRecord("r2", "doc", "abc 落とし物", "https://doc/r2", "2026-01-01", container_id="D1"),
        ]
        index = GrepIndex(records, projection_watermark="wm1")

        first = index.grep(GrepRequest(pattern="ABC|落とし物", limit=1))
        second = index.grep(GrepRequest(pattern="ABC|落とし物", limit=1, cursor=first.next_cursor))
        filtered = index.grep(GrepRequest(pattern="abc", filters=GrepFilters(types=frozenset({"doc"}))))

        self.assertEqual(first.matches[0].record_id, "r1")
        self.assertFalse(first.complete)
        self.assertEqual(second.matches[0].record_id, "r2")
        self.assertTrue(second.complete)
        self.assertEqual(filtered.matches[0].record_id, "r2")
        self.assertEqual(index.projection_watermark, "wm1")
        self.assertTrue(index.trigram_index)
        with self.assertRaises(ValueError):
            index.grep(GrepRequest(pattern=r"(a)\1"))

    def test_grep_cursor_is_keyset_and_survives_newer_insertions(self) -> None:
        first_index = GrepIndex(
            [
                WorkspaceRecord("r1", "doc", "match one", "https://doc/r1", "2026-01-02T00:00:00Z"),
                WorkspaceRecord("r2", "doc", "match two", "https://doc/r2", "2026-01-01T00:00:00Z"),
            ]
        )
        first = first_index.grep(GrepRequest(pattern="match", limit=1))
        cursor_payload = json.loads(base64.urlsafe_b64decode(first.next_cursor.encode("ascii")).decode("utf-8"))
        changed_index = GrepIndex(
            [
                WorkspaceRecord("r0", "doc", "match newer", "https://doc/r0", "2026-01-03T00:00:00Z"),
                WorkspaceRecord("r1", "doc", "match one", "https://doc/r1", "2026-01-02T00:00:00Z"),
                WorkspaceRecord("r2", "doc", "match two", "https://doc/r2", "2026-01-01T00:00:00Z"),
            ]
        )

        second = changed_index.grep(GrepRequest(pattern="match", limit=1, cursor=first.next_cursor))

        self.assertEqual(cursor_payload, {"ts": "2026-01-02T00:00:00Z", "id": "r1"})
        self.assertEqual(second.matches[0].record_id, "r2")

    def test_resolve_link_matches_normalized_url_not_prefix(self) -> None:
        index = GrepIndex([WorkspaceRecord("r1", "doc", "body", "https://example.com/doc/123/", "2026")])

        self.assertEqual(index.resolve_link("https://example.com/doc/123").record_id, "r1")  # type: ignore[union-attr]
        self.assertIsNone(index.resolve_link("https://example.com/doc/1234"))
        self.assertIsNone(index.resolve_link("https://example.com/doc/123?view=1"))

    def test_grep_api_endpoint_shape(self) -> None:
        api = GrepApi({"public": GrepIndex([WorkspaceRecord("r1", "doc", "期限は金曜", "https://doc", "2026")])})

        status, payload = api.post_grep("public", {"pattern": "期限"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["matches"][0]["record_id"], "r1")

    def test_http_lethe_client_calls_grep_api_over_http(self) -> None:
        handler = make_grep_handler(
            GrepApi({"public": GrepIndex([WorkspaceRecord("r1", "doc", "期限は金曜", "https://doc", "2026")])})
        )
        with running_server(handler) as base_url:
            client = HttpLetheClient(base_url, service_token="token")

            response = client.grep("public", GrepRequest(pattern="期限"), slack_user_id="U1")

        self.assertEqual(response.matches[0].record_id, "r1")

    def test_http_lethe_client_surfaces_http_errors_and_timeouts(self) -> None:
        for status in (404, 500):
            with running_server(error_handler(status)) as base_url:
                client = HttpLetheClient(base_url, service_token="token")
                with self.assertRaisesRegex(RuntimeError, f"LETHE API returned {status}"):
                    client.grep("public", GrepRequest(pattern="期限"))

        client = HttpLetheClient("http://lethe.invalid", service_token="token", timeout_seconds=0.01)
        with patch("rulebot.workspace_lethe.urllib.request.urlopen", side_effect=TimeoutError("slow")):
            with self.assertRaisesRegex(RuntimeError, "LETHE API request failed"):
                client.grep("public", GrepRequest(pattern="期限"))

    def test_workspace_config_uses_yaml_parser_and_configured_variant_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workspace.yaml"
            path.write_text(
                """
workspace_search:
  variant_groups:
    lost:
      - 紛失
      - lost
  slack:
    channel_interval_overrides:
      C1: 30
""",
                encoding="utf-8",
            )

            config = load_workspace_search_config(path)

        self.assertEqual(config.variant_groups, (("紛失", "lost"),))
        self.assertEqual(config.slack.interval_for("C1"), 30)
        self.assertIn("紛失|lost", build_regex_patterns("lost item", config.variant_groups))

    def test_slack_export_and_poll_are_idempotent_and_observable(self) -> None:
        writer = MemoryLetheClient()
        ingestor = SlackIngestor(writer, SlackIngestionConfig(global_interval_seconds=60, channel_interval_overrides={"C1": 30}))
        message = {"ts": "1.1", "thread_ts": "1.1", "client_msg_id": "m1", "user": "U1", "text": "hello"}

        obs1 = observation_from_slack_message(message, channel_id="C1", channel_name="123_event")
        obs2 = observation_from_slack_message(message, channel_id="C1", channel_name="123_event")
        self.assertEqual(obs1.idempotency_key, obs2.idempotency_key)
        self.assertTrue(writer.put_observation(obs1))
        self.assertFalse(writer.put_observation(obs2))

        class Client:
            def conversations_history(self, **kwargs: Any) -> dict[str, Any]:
                return {"messages": [message], "response_metadata": {"next_cursor": ""}}

        self.assertEqual(ingestor.poll_channel(Client(), channel_id="C1", channel_name="123_event"), 0)
        status = ingestor.status_for("C1")
        self.assertIsNotNone(status)
        self.assertEqual(status.failure_count, 0)

    def test_drive_crawler_adapters_and_revision_tracking(self) -> None:
        writer = MemoryLetheClient()
        tracker = RevisionTracker()
        crawler = DriveCrawler(writer, DriveCrawlConfig(allowed_folder_ids=frozenset({"F1"})), revision_tracker=tracker)

        class Drive:
            def list_files(self, *, folder_ids: set[str]) -> list[dict[str, Any]]:
                return [
                    file_info("D1", "application/vnd.google-apps.document"),
                    file_info("S1", "application/vnd.google-apps.spreadsheet"),
                    file_info("F1", "application/vnd.google-apps.form"),
                    file_info("P1", "application/vnd.google-apps.presentation"),
                    file_info("X1", "text/plain"),
                ]

        class Workspace:
            def get_document(self, file_id: str) -> dict[str, Any]:
                return {"title": "Doc", "headings": ["H"], "body": "Body", "links": ["https://x"], "url": "https://doc"}

            def get_sheet(self, file_id: str) -> dict[str, Any]:
                return {"headers": ["name", "due"], "rows": [["A", "Friday"]], "url": "https://sheet"}

            def get_form(self, file_id: str) -> dict[str, Any]:
                return {
                    "title": "Form",
                    "description": "Desc",
                    "questions": ["Q1"],
                    "url": "https://form",
                    "responses": [{"responder_id": "U1", "timestamp": "2026", "answers": {"Q1": "secret"}}],
                }

            def get_slides(self, file_id: str) -> dict[str, Any]:
                return {"url": "https://slides", "slides": [{"id": "s1", "text_blocks": ["Slide text"]}]}

            def get_file_text(self, file_id: str) -> str:
                return "plain text"

        self.assertEqual(crawler.crawl(Drive(), Workspace()), 6)
        self.assertEqual(crawler.crawl(Drive(), Workspace()), 0)
        self.assertTrue(all(obs.schema == "workspace-object-snapshot" for obs in writer.observations.values()))

    def test_mcp_tools_agent_answer_log_and_user_output(self) -> None:
        index = GrepIndex([WorkspaceRecord("r1", "doc", "提出期限は金曜です", "https://doc", "2026", source_title="Doc")])

        class Lethe:
            def grep(self, projection_id: str, request: GrepRequest, *, slack_user_id: str = ""):
                return index.grep(request)

            def get_record(self, projection_id: str, record_id: str, *, slack_user_id: str = ""):
                record = index.get_record(record_id)
                if record is None:
                    raise PermissionError("not exposed")
                return record

            def get_thread(self, projection_id: str, *, thread_ts: str = "", permalink: str = "", slack_user_id: str = ""):
                return index.get_thread(thread_ts=thread_ts, permalink=permalink)

            def resolve_link(self, projection_id: str, url: str, *, slack_user_id: str = ""):
                record = index.resolve_link(url)
                if record is None:
                    raise PermissionError("not exposed")
                return record

        with tempfile.TemporaryDirectory() as tmp:
            log = JsonlAnswerLog(Path(tmp) / "answers.jsonl")
            log.append(
                AnswerLogEntry(
                    answer_id="a1",
                    question="フォーム期限",
                    answer="金曜",
                    citations=[Citation("https://doc", "r1", "doc")],
                    used_queries=["期限"],
                    asker="U0",
                    ts="2026",
                    model="m",
                    usage={"input_tokens": 1, "output_tokens": 1},
                    confidence="high",
                    unknowns=[],
                )
            )
            tools = WorkspaceMcpTools(Lethe(), projection_id="public", answer_log=log)
            agent = WorkspaceSearchAgent(tools, answer_log=log)

            envelope = agent.answer("フォームの提出期限は？", slack_user_id="U1")

            self.assertIn("https://doc", envelope.slack_text())
            self.assertNotIn("confidence", envelope.slack_text())
            self.assertTrue(envelope.prior_answer_ids)
            self.assertGreaterEqual(len(log.search("フォーム")), 2)
            self.assertFalse(tools.prior_qa_search("フォーム")["primary_source"])
            self.assertTrue(any("提出期限" in pattern for pattern in build_regex_patterns("フォームの提出期限は？")))
            self.assertTrue(is_human_trigger({"type": "app_mention"}))
            self.assertFalse(is_human_trigger({"type": "app_mention", "bot_id": "B1"}))

    def test_workspace_agent_can_use_codex_style_answer_composer(self) -> None:
        index = GrepIndex([WorkspaceRecord("r1", "doc", "提出期限は金曜です", "https://doc", "2026", source_title="Doc")])

        class Lethe:
            def grep(self, projection_id: str, request: GrepRequest, *, slack_user_id: str = ""):
                return index.grep(request)

            def get_record(self, projection_id: str, record_id: str, *, slack_user_id: str = ""):
                record = index.get_record(record_id)
                if record is None:
                    raise PermissionError("not exposed")
                return record

            def get_thread(self, projection_id: str, *, thread_ts: str = "", permalink: str = "", slack_user_id: str = ""):
                return []

            def resolve_link(self, projection_id: str, url: str, *, slack_user_id: str = ""):
                raise PermissionError("not exposed")

        class Composer:
            def __init__(self) -> None:
                self.called = False

            def __call__(self, question: str, snippets: list[str], citations: list[Citation]) -> ComposedAnswer:
                self.called = True
                self.assert_inputs = (question, snippets, citations)
                return ComposedAnswer("Codex synthesized answer", usage={"input_tokens": 10, "output_tokens": 5}, confidence="high")

        composer = Composer()
        agent = WorkspaceSearchAgent(WorkspaceMcpTools(Lethe(), projection_id="public"), model="codex-workspace", answer_composer=composer)

        envelope = agent.answer("提出期限", slack_user_id="U1")

        self.assertTrue(composer.called)
        self.assertEqual(envelope.answer, "Codex synthesized answer")
        self.assertEqual(envelope.usage["input_tokens"], 10)
        self.assertEqual(envelope.confidence, "high")


def slack_record(text: str, channel_name: str, author_id: str, *, is_bot: bool = False, is_public: bool = True) -> WorkspaceRecord:
    return WorkspaceRecord(
        record_id=text,
        source_type="slack",
        text=text,
        anchor_url=f"https://slack/{text}",
        timestamp="2026",
        source_title=channel_name,
        container_id="C1",
        author_id=author_id,
        metadata={"channel_name": channel_name, "is_bot": is_bot, "is_public_channel": is_public},
    )


def drive_record(
    file_id: str,
    source_type: str,
    sharing_level: str,
    folder_ids: list[str],
    owner_id: str,
    *,
    text: str,
    extra: dict[str, Any] | None = None,
) -> WorkspaceRecord:
    metadata = {"file_id": file_id, "sharing_level": sharing_level, "folder_ids": folder_ids, "owner_id": owner_id}
    metadata.update(extra or {})
    return WorkspaceRecord(
        record_id=file_id,
        source_type=source_type,  # type: ignore[arg-type]
        text=text,
        anchor_url=f"https://drive/{file_id}",
        timestamp="2026",
        source_title=file_id,
        container_id=file_id,
        author_id=owner_id,
        metadata=metadata,
    )


def file_info(file_id: str, mime_type: str) -> dict[str, Any]:
    return {
        "id": file_id,
        "name": file_id,
        "mimeType": mime_type,
        "parents": ["F1"],
        "sharing_level": "domain",
        "owner_id": "U1",
        "revisionId": "rev1",
        "modifiedTime": "2026",
        "webViewLink": f"https://drive/{file_id}",
    }


class running_server:
    def __init__(self, handler: type[BaseHTTPRequestHandler]):
        self.handler = handler
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> str:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        assert self.server is not None
        self.server.shutdown()
        self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


def error_handler(status: int) -> type[BaseHTTPRequestHandler]:
    class ErrorHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.dumps({"error": "forced"}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ErrorHandler


if __name__ == "__main__":
    unittest.main()
