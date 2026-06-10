from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import patch

from rulebot.query_planner import QueryPlan, plan_query


class QueryPlannerTest(unittest.TestCase):
    def test_query_plan_deduplicates_queries(self) -> None:
        plan = QueryPlan(search_queries=["鍵", "鍵"], related_terms=["紛失"], intent="")

        self.assertEqual(plan.all_queries("キー"), ["キー", "鍵", "紛失"])

    def test_plan_query_reads_codex_json(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"search_queries":["鍵 紛失"],"related_terms":["再発行"],"intent":"鍵紛失"}',
            stderr="",
        )

        with patch.dict(
            os.environ,
            {
                "AGENT_CLI_PROVIDER": "codex",
                "AGENT_WORKDIR": "/app",
                "AGENT_QUERY_TIMEOUT_SECONDS": "45",
                "CODEX_QUERY_PLANNER_REASONING_EFFORT": "low",
            },
            clear=True,
        ), patch("rulebot.agent_cli.subprocess.run", return_value=completed):
            plan = plan_query("キーをなくした場合は？")

        self.assertEqual(plan.search_queries, ["鍵 紛失"])
        self.assertEqual(plan.related_terms, ["再発行"])
        self.assertEqual(plan.intent, "鍵紛失")

    def test_plan_query_reads_codex_jsonl_usage(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"agent_message","text":"'
                '{\\"search_queries\\":[\\"鍵 紛失\\"],\\"related_terms\\":[\\"再発行\\"],\\"intent\\":\\"鍵紛失\\"}"}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,'
                '"output_tokens":20,"reasoning_output_tokens":5}}\n'
            ),
            stderr="",
        )

        with patch.dict(
            os.environ,
            {
                "AGENT_CLI_PROVIDER": "codex",
                "AGENT_WORKDIR": "/app",
                "AGENT_QUERY_TIMEOUT_SECONDS": "45",
                "CODEX_QUERY_PLANNER_REASONING_EFFORT": "low",
            },
            clear=True,
        ), patch("rulebot.agent_cli.subprocess.run", return_value=completed):
            plan = plan_query("キーをなくした場合は？")

        self.assertEqual(plan.search_queries, ["鍵 紛失"])
        self.assertEqual(plan.usage.total_tokens, 125)
        self.assertEqual(plan.usage.cached_input_tokens, 40)

    def test_plan_query_raises_on_failure(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="error")

        with patch.dict(
            os.environ,
            {
                "AGENT_CLI_PROVIDER": "codex",
                "AGENT_WORKDIR": "/app",
                "AGENT_QUERY_TIMEOUT_SECONDS": "45",
                "CODEX_QUERY_PLANNER_REASONING_EFFORT": "low",
            },
            clear=True,
        ), patch("rulebot.agent_cli.subprocess.run", return_value=completed), self.assertRaises(RuntimeError):
            plan_query("キーをなくした場合は？")


if __name__ == "__main__":
    unittest.main()
