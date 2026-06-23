from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from rulebot import codex_agent
from rulebot.agent_cli import AgentRunResult
from rulebot.document_store import DocumentChunk
from rulebot.query_planner import QueryPlan
from rulebot.search_index import SearchIndex
from rulebot.token_usage import TokenUsage


class CodexAgentTest(unittest.TestCase):
    def test_prompt_uses_candidates_not_full_corpus(self) -> None:
        index = SearchIndex.from_chunks(
            [
                DocumentChunk(
                    source="rules.md",
                    location="鍵について (line 10)",
                    text="鍵を紛失した場合は再発行費用が発生します。",
                )
            ]
        )
        candidates = index.search(["鍵 紛失 再発行"], top_k=3)

        prompt = codex_agent._build_prompt(
            "キーをなくした場合は？",
            QueryPlan(search_queries=["鍵 紛失"], related_terms=["再発行"], intent="鍵紛失時の費用確認"),
            candidates,
        )

        self.assertIn("根拠候補だけ", prompt)
        self.assertIn("鍵について", prompt)
        self.assertIn("鍵 紛失", prompt)
        self.assertNotIn("回答用ドキュメント全文", prompt)

    def test_search_candidates_uses_planned_terms(self) -> None:
        index = SearchIndex.from_chunks(
            [
                DocumentChunk(source="rules.md", location="鍵について", text="鍵を紛失した場合は再発行費用が発生します。"),
                DocumentChunk(source="food.md", location="食器", text="食器を割った場合はスタッフへ報告します。"),
            ]
        )

        with patch.dict(os.environ, {"RETRIEVAL_CANDIDATE_TOP_K": "30", "ANSWER_CONTEXT_TOP_K": "8"}, clear=True):
            hits = codex_agent._search_candidates(
                "キーをなくした場合は？",
                QueryPlan(search_queries=["鍵 紛失 再発行"], related_terms=[], intent=""),
                index,
            )

        self.assertTrue(hits)
        self.assertEqual(hits[0].chunk.location, "鍵について")

    def test_codex_uses_configured_reasoning(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"answer":"ok","citations":["rules.md"],"unknowns":[]}',
            stderr="",
        )

        with patch.dict(
            os.environ,
            {
                "AGENT_CLI_PROVIDER": "codex",
                "AGENT_WORKDIR": "/app",
                "AGENT_ANSWER_TIMEOUT_SECONDS": "180",
                "CODEX_REASONING_EFFORT": "medium",
            },
            clear=True,
        ), patch("rulebot.agent_cli.subprocess.run", return_value=completed) as run:
            data = codex_agent._run_codex("prompt")

        command = run.call_args.args[0]
        self.assertEqual(data["answer"], "ok")
        self.assertIn("--json", command)
        self.assertIn("--cd", command)
        self.assertEqual(command[command.index("--cd") + 1], "/app")
        self.assertIn('model_reasoning_effort="medium"', command)

    def test_codex_reads_jsonl_usage(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"agent_message","text":"'
                '{\\"answer\\":\\"ok\\",\\"citations\\":[\\"rules.md\\"],\\"unknowns\\":[]}"}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":120,"cached_input_tokens":30,'
                '"output_tokens":25,"reasoning_output_tokens":10}}\n'
            ),
            stderr="",
        )

        with patch.dict(
            os.environ,
            {
                "AGENT_CLI_PROVIDER": "codex",
                "AGENT_WORKDIR": "/app",
                "AGENT_ANSWER_TIMEOUT_SECONDS": "180",
                "CODEX_REASONING_EFFORT": "medium",
            },
            clear=True,
        ), patch("rulebot.agent_cli.subprocess.run", return_value=completed):
            data = codex_agent._run_codex("prompt")

        self.assertEqual(data["answer"], "ok")
        self.assertEqual(data["usage"]["total_tokens"], 155)
        self.assertEqual(data["usage"]["cached_input_tokens"], 30)

    def test_app_server_agent_error_is_sanitized_without_cli_retry(self) -> None:
        with patch("rulebot.codex_agent.answer_with_codex_app_server", side_effect=codex_agent.CodexAppServerError("boom")), patch(
            "rulebot.codex_agent._answer_with_search_agent",
        ) as retry:
            data = codex_agent._run_codex_app_server("質問", Path("docs"))

        retry.assert_not_called()
        self.assertEqual(data["error_type"], "agent_error")
        self.assertFalse(data["usage_chargeable"])

    def test_app_server_auth_error_is_sanitized_without_cli_retry(self) -> None:
        error = codex_agent.CodexAppServerError("401 Unauthorized refresh_token_reused Please log out and sign in again")
        with patch("rulebot.codex_agent.answer_with_codex_app_server", side_effect=error), patch(
            "rulebot.codex_agent._answer_with_search_agent",
        ) as retry:
            data = codex_agent._run_codex_app_server("質問", Path("docs"))

        retry.assert_not_called()
        self.assertEqual(data["error_type"], "auth")
        self.assertEqual(data["citations"], [])
        self.assertIn("再ログイン", data["unknowns"][0])
        self.assertNotIn("refresh_token", data["unknowns"][0])

    def test_run_codex_nonzero_error_is_sanitized(self) -> None:
        result = AgentRunResult(
            text="",
            usage=TokenUsage(input_tokens=10),
            returncode=1,
            stderr="Failed to refresh token: refresh_token_reused",
        )
        with patch("rulebot.codex_agent.run_agent_cli", return_value=result):
            data = codex_agent._run_codex("prompt")

        self.assertEqual(data["error_type"], "auth")
        self.assertEqual(data["citations"], [])
        self.assertIn("再ログイン", data["unknowns"][0])
        self.assertNotIn("refresh_token", data["unknowns"][0])

    def test_app_server_result_can_mark_usage_not_chargeable(self) -> None:
        result = AgentRunResult(
            text='{"answer":"ok","citations":[],"unknowns":[]}',
            usage=TokenUsage(input_tokens=100),
            returncode=0,
            provider="codex_app_server",
            usage_chargeable=False,
        )
        with patch("rulebot.codex_agent.answer_with_codex_app_server", return_value=result):
            data = codex_agent._run_codex_app_server("質問", Path("docs"))

        self.assertEqual(data["answer"], "ok")
        self.assertFalse(data["usage_chargeable"])

    def test_compose_workspace_answer_calls_codex_with_verified_sources(self) -> None:
        with patch(
            "rulebot.codex_agent._run_codex",
            return_value={"answer": "金曜です。", "unknowns": [], "confidence": "high", "usage": {"input_tokens": 3, "output_tokens": 2}},
        ) as run:
            data = codex_agent.compose_workspace_answer(
                "提出期限は？",
                ["提出期限は金曜です。"],
                [{"url": "https://doc", "record_id": "r1", "source_type": "doc"}],
            )

        prompt = run.call_args.args[0]
        self.assertEqual(data["answer"], "金曜です。")
        self.assertIn("検証済み一次ソース", prompt)
        self.assertIn("https://doc", prompt)
        self.assertIn("提出期限は金曜", prompt)


if __name__ == "__main__":
    unittest.main()
