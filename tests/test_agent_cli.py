from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import patch

from rulebot.agent_cli import classify_agent_error, run_agent_cli, user_facing_agent_error


class AgentCliTest(unittest.TestCase):
    def test_codex_provider_is_read_from_env(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"answer\\":\\"ok\\"}"}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}\n'
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
        ), patch("rulebot.agent_cli.subprocess.run", return_value=completed) as run:
            result = run_agent_cli("prompt", purpose="answer")

        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["codex", "exec", "--json"])
        self.assertEqual(result.text, '{"answer":"ok"}')
        self.assertEqual(result.usage.total_tokens, 12)

    def test_claude_provider_uses_print_json_mode(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"result":"{\\"answer\\":\\"ok\\"}","usage":{"input_tokens":10,"output_tokens":3}}',
            stderr="",
        )

        with patch.dict(
            os.environ,
            {
                "AGENT_CLI_PROVIDER": "claude",
                "AGENT_ANSWER_TIMEOUT_SECONDS": "180",
                "CLAUDE_PERMISSION_MODE": "plan",
            },
            clear=True,
        ), patch(
            "rulebot.agent_cli.subprocess.run", return_value=completed
        ) as run:
            result = run_agent_cli("prompt", purpose="answer")

        command = run.call_args.args[0]
        self.assertIn("claude", command[0])
        self.assertIn("-p", command)
        self.assertIn("--output-format", command)
        self.assertIn("json", command)
        self.assertEqual(result.text, '{"answer":"ok"}')
        self.assertEqual(result.usage.total_tokens, 13)

    def test_classifies_codex_auth_errors(self) -> None:
        detail = "Failed to refresh token: 401 Unauthorized refresh_token_reused. Please log out and sign in again."

        error_type = classify_agent_error(detail)

        self.assertEqual(error_type, "auth")
        self.assertIn("再ログイン", user_facing_agent_error(error_type))
        self.assertNotIn("refresh_token", user_facing_agent_error(error_type))


if __name__ == "__main__":
    unittest.main()
