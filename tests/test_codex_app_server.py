from __future__ import annotations

import json
import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rulebot import codex_app_server


class FakeCodexAppServerClient:
    def __init__(self) -> None:
        self.seed_count = 0
        self.fork_count = 0
        self.archived: list[str] = []
        self.rolled_back: list[dict[str, object]] = []
        self.answer_usage_after_completed: dict[str, int] | None = None
        self._request_id = 0
        self.stdout = FakeStream()
        self.stderr = FakeStream()
        self.stdin = self

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        pass

    def write(self, value: str) -> None:
        request = json.loads(value)
        self._request_id = int(request["id"])
        method = request["method"]
        params = request.get("params") or {}
        if method == "initialize":
            self._emit_response({"ok": True})
        elif method == "thread/start":
            self.seed_count += 1
            self._emit_response({"thread": {"id": f"seed-{self.seed_count}"}})
        elif method == "turn/start":
            self._emit_response({"turn": {"id": "turn-1"}})
            thread_id = params["threadId"]
            text = params["input"][0]["text"]
            if "READY" in text:
                self._emit_turn(thread_id, "READY", {"totalTokens": 100, "inputTokens": 95, "outputTokens": 5})
            else:
                self._emit_turn(
                    thread_id,
                    '{"answer":"ok","citations":["rules"],"unknowns":[]}',
                    {
                        "totalTokens": 22315,
                        "inputTokens": 22203,
                        "cachedInputTokens": 21888,
                        "outputTokens": 112,
                        "reasoningOutputTokens": 31,
                    },
                )
        elif method == "thread/compact/start":
            self._emit_response({})
            self._emit_turn(params["threadId"], "", {"totalTokens": 10})
        elif method == "thread/fork":
            self.fork_count += 1
            self._emit_response({"thread": {"id": f"fork-{self.fork_count}"}})
        elif method == "thread/archive":
            self.archived.append(params["threadId"])
            self._emit_response({})
        elif method == "thread/rollback":
            self.rolled_back.append({"threadId": params["threadId"], "numTurns": params["numTurns"]})
            self._emit_response({"thread": {"id": params["threadId"], "turns": []}})
        else:
            self._emit_response({})

    def flush(self) -> None:
        pass

    def readline(self) -> str:
        return ""

    def __iter__(self):
        return iter(())

    def _emit_response(self, result: dict[str, object]) -> None:
        self.stdout.put(json.dumps({"id": self._request_id, "result": result}) + "\n")

    def _emit_turn(self, thread_id: str, text: str, usage: dict[str, int]) -> None:
        self.stdout.put(
            json.dumps(
                {
                    "method": "thread/tokenUsage/updated",
                    "params": {"threadId": thread_id, "turnId": "turn-1", "tokenUsage": {"last": usage, "total": usage}},
                }
            )
            + "\n"
        )
        if text:
            self.stdout.put(
                json.dumps(
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": "turn-1",
                            "completedAtMs": 1,
                            "item": {"type": "agentMessage", "id": "item-1", "text": text, "phase": "final_answer"},
                        },
                    }
                )
                + "\n"
            )
        self.stdout.put(
            json.dumps(
                {
                    "method": "turn/completed",
                    "params": {"threadId": thread_id, "turn": {"id": "turn-1", "items": [], "status": "completed"}},
                }
            )
            + "\n"
        )
        if self.answer_usage_after_completed is not None and text != "READY":
            self.stdout.put(
                json.dumps(
                    {
                        "method": "thread/tokenUsage/updated",
                        "params": {
                            "threadId": thread_id,
                            "turnId": "turn-1",
                            "tokenUsage": {
                                "last": self.answer_usage_after_completed,
                                "total": self.answer_usage_after_completed,
                            },
                        },
                    }
                )
                + "\n"
            )


class FakeStream:
    def __init__(self) -> None:
        self._queue: queue.Queue[str | None] = queue.Queue()

    def put(self, line: str) -> None:
        self._queue.put(line)

    def __iter__(self):
        return self

    def __next__(self) -> str:
        line = self._queue.get(timeout=5)
        if line is None:
            raise StopIteration
        return line


class CodexAppServerTest(unittest.TestCase):
    def test_answers_from_compacted_seed_and_rolls_back_answer_turn(self) -> None:
        fake = FakeCodexAppServerClient()
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            (docs / "rules.md").write_text("ゲストは宿泊できません。", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "AGENT_WORKDIR": tmp,
                    "CODEX_DEFAULT_MODEL": "gpt-test",
                    "CODEX_REASONING_EFFORT": "low",
                    "CODEX_APP_SERVER_REMOTE_COMPACTION_V2": "1",
                    "CODEX_APP_SERVER_USAGE_DRAIN_SECONDS": "0",
                    "CODEX_APP_SERVER_SEED_TIMEOUT_SECONDS": "300",
                    "CODEX_APP_SERVER_ANSWER_TIMEOUT_SECONDS": "300",
                },
                clear=True,
            ), patch("rulebot.codex_app_server.subprocess.Popen", return_value=fake):
                client = codex_app_server.CodexAppServerClient()
                result = client.answer("ゲストは宿泊できますか？", docs)

        self.assertEqual(result.text, '{"answer":"ok","citations":["rules"],"unknowns":[]}')
        self.assertEqual(result.usage.total_tokens, 22315)
        self.assertEqual(result.usage.effective_tokens, 427)
        self.assertFalse(result.usage_chargeable)
        self.assertEqual(fake.fork_count, 0)
        self.assertEqual(fake.archived, [])
        self.assertEqual(fake.rolled_back, [{"threadId": "seed-1", "numTurns": 1}])

    def test_first_answer_after_seed_is_free_then_later_answers_are_chargeable(self) -> None:
        fake = FakeCodexAppServerClient()
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            (docs / "rules.md").write_text("ゲストは宿泊できません。", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "AGENT_WORKDIR": tmp,
                    "CODEX_DEFAULT_MODEL": "gpt-test",
                    "CODEX_REASONING_EFFORT": "low",
                    "CODEX_APP_SERVER_REMOTE_COMPACTION_V2": "1",
                    "CODEX_APP_SERVER_USAGE_DRAIN_SECONDS": "0",
                    "CODEX_APP_SERVER_SEED_TIMEOUT_SECONDS": "300",
                    "CODEX_APP_SERVER_ANSWER_TIMEOUT_SECONDS": "300",
                },
                clear=True,
            ), patch("rulebot.codex_app_server.subprocess.Popen", return_value=fake):
                client = codex_app_server.CodexAppServerClient()
                first = client.answer("ゲストは宿泊できますか？", docs)
                second = client.answer("ゲストは宿泊できますか？", docs)

        self.assertFalse(first.usage_chargeable)
        self.assertTrue(second.usage_chargeable)
        self.assertEqual(fake.seed_count, 1)
        self.assertEqual(fake.fork_count, 0)
        self.assertEqual(fake.archived, [])
        self.assertEqual(
            fake.rolled_back,
            [{"threadId": "seed-1", "numTurns": 1}, {"threadId": "seed-1", "numTurns": 1}],
        )

    def test_rollback_mode_reuses_seed_thread_and_removes_answer_turn(self) -> None:
        fake = FakeCodexAppServerClient()
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            (docs / "rules.md").write_text("ゲストは宿泊できません。", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "AGENT_WORKDIR": tmp,
                    "CODEX_DEFAULT_MODEL": "gpt-test",
                    "CODEX_REASONING_EFFORT": "low",
                    "CODEX_APP_SERVER_REMOTE_COMPACTION_V2": "1",
                    "CODEX_APP_SERVER_USAGE_DRAIN_SECONDS": "0",
                    "CODEX_APP_SERVER_SEED_TIMEOUT_SECONDS": "300",
                    "CODEX_APP_SERVER_ANSWER_TIMEOUT_SECONDS": "300",
                },
                clear=True,
            ), patch("rulebot.codex_app_server.subprocess.Popen", return_value=fake):
                client = codex_app_server.CodexAppServerClient()
                first = client.answer("ゲストは宿泊できますか？", docs)
                second = client.answer("ゲストは宿泊できますか？", docs)

        self.assertEqual(first.text, '{"answer":"ok","citations":["rules"],"unknowns":[]}')
        self.assertFalse(first.usage_chargeable)
        self.assertTrue(second.usage_chargeable)
        self.assertEqual(fake.seed_count, 1)
        self.assertEqual(fake.fork_count, 0)
        self.assertEqual(fake.archived, [])
        self.assertEqual(
            fake.rolled_back,
            [{"threadId": "seed-1", "numTurns": 1}, {"threadId": "seed-1", "numTurns": 1}],
        )

    def test_uses_late_token_usage_update_after_turn_completed(self) -> None:
        fake = FakeCodexAppServerClient()
        fake.answer_usage_after_completed = {
            "totalTokens": 22315,
            "inputTokens": 22203,
            "cachedInputTokens": 17000,
            "outputTokens": 112,
            "reasoningOutputTokens": 31,
        }
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            (docs / "rules.md").write_text("ゲストは宿泊できません。", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "AGENT_WORKDIR": tmp,
                    "CODEX_DEFAULT_MODEL": "gpt-test",
                    "CODEX_REASONING_EFFORT": "low",
                    "CODEX_APP_SERVER_REMOTE_COMPACTION_V2": "1",
                    "CODEX_APP_SERVER_USAGE_DRAIN_SECONDS": "0.01",
                    "CODEX_APP_SERVER_SEED_TIMEOUT_SECONDS": "300",
                    "CODEX_APP_SERVER_ANSWER_TIMEOUT_SECONDS": "300",
                },
                clear=True,
            ), patch("rulebot.codex_app_server.subprocess.Popen", return_value=fake):
                client = codex_app_server.CodexAppServerClient()
                result = client.answer("ゲストは宿泊できますか？", docs)

        self.assertEqual(result.usage.cached_input_tokens, 17000)
        self.assertEqual(result.usage.effective_tokens, 5315)


if __name__ == "__main__":
    unittest.main()
