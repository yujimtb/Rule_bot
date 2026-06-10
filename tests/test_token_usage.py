from __future__ import annotations

import unittest

from rulebot.token_usage import TokenUsage, parse_claude_json_output, parse_codex_json_output, usage_from_dict


class TokenUsageTest(unittest.TestCase):
    def test_parse_codex_json_output_reads_agent_message_and_usage(self) -> None:
        text, usage = parse_codex_json_output(
            "\n".join(
                [
                    '{"type":"thread.started","thread_id":"abc"}',
                    '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"answer\\":\\"ok\\"}"}}',
                    '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":3,'
                    '"output_tokens":4,"reasoning_output_tokens":2}}',
                ]
            )
        )

        self.assertEqual(text, '{"answer":"ok"}')
        self.assertEqual(usage.total_tokens, 16)
        self.assertEqual(usage.cached_input_tokens, 3)
        self.assertEqual(usage.effective_tokens, 13)

    def test_usage_from_dict_reads_app_server_camel_case_usage(self) -> None:
        usage = usage_from_dict(
            {
                "totalTokens": 22315,
                "inputTokens": 22203,
                "cachedInputTokens": 21888,
                "outputTokens": 112,
                "reasoningOutputTokens": 31,
            }
        )

        self.assertEqual(usage.total_tokens, 22315)
        self.assertEqual(usage.cached_input_tokens, 21888)
        self.assertEqual(usage.effective_tokens, 427)

    def test_effective_tokens_never_negative(self) -> None:
        usage = TokenUsage(input_tokens=100, cached_input_tokens=200)

        self.assertEqual(usage.effective_tokens, 0)

    def test_parse_claude_json_output_reads_result_and_usage(self) -> None:
        text, usage = parse_claude_json_output(
            '{"result":"{\\"answer\\":\\"ok\\"}","usage":{"input_tokens":20,'
            '"cache_read_input_tokens":8,"output_tokens":5}}'
        )

        self.assertEqual(text, '{"answer":"ok"}')
        self.assertEqual(usage.total_tokens, 25)
        self.assertEqual(usage.cached_input_tokens, 8)


if __name__ == "__main__":
    unittest.main()
