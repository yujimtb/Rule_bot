from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rulebot.quota_store import QuotaSnapshot
from rulebot.slack_bot import (
    TRUNCATION_NOTICE,
    build_quota_footer,
    build_total_quota_exceeded_message,
    extract_question,
    fit_slack_text,
    load_slack_messages,
    update_slack_message,
)
from rulebot.token_usage import TokenUsage


class SlackBotTest(unittest.TestCase):
    def test_extract_question_removes_mentions(self) -> None:
        question = extract_question({"text": "<@U123ABC> 食器を割ったらどうする？"})

        self.assertEqual(question, "食器を割ったらどうする？")

    def test_load_slack_messages_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "messages.json"
            path.write_text(
                '{"progress_message":"確認しています","answer_error_message":"エラーです"}',
                encoding="utf-8",
            )

            messages = load_slack_messages(str(path))

        self.assertEqual(messages["progress_message"], "確認しています")
        self.assertEqual(messages["answer_error_message"], "エラーです")

    def test_load_slack_messages_requires_config_file(self) -> None:
        with self.assertRaises(OSError):
            load_slack_messages("missing.json")

    def test_build_quota_footer_shows_usage_and_remaining_tokens(self) -> None:
        footer = build_quota_footer(
            TokenUsage(input_tokens=1000, cached_input_tokens=800, output_tokens=200, reasoning_output_tokens=50),
            QuotaSnapshot(enabled=True, month="2026-05", used_tokens=5000, limit_tokens=10000),
        )

        self.assertIn("今回quota対象: 450 tokens", footer)
        self.assertIn("総使用量（参考）: 1,250 tokens", footer)
        self.assertIn("キャッシュ済み入力（参考）: 800 tokens", footer)
        self.assertIn("今月: 5,000 / 10,000 tokens", footer)
        self.assertIn("残り: 5,000 tokens", footer)

    def test_build_quota_footer_marks_non_chargeable_usage(self) -> None:
        footer = build_quota_footer(
            TokenUsage(input_tokens=1000, cached_input_tokens=800, output_tokens=100),
            QuotaSnapshot(enabled=True, month="2026-05", used_tokens=5000, limit_tokens=10000),
            chargeable=False,
        )

        self.assertIn("今回分は月間quotaに加算していません", footer)

    def test_build_total_quota_exceeded_message_does_not_show_usage_footer(self) -> None:
        text = build_total_quota_exceeded_message(
            QuotaSnapshot(enabled=True, month="2026-05", used_tokens=10000, limit_tokens=10000)
        )

        self.assertIn("Bot全体の月間トークン使用量上限に達しました", text)
        self.assertNotIn("*トークン使用量*", text)

    def test_fit_slack_text_truncates_long_text(self) -> None:
        text = fit_slack_text("a" * 100, limit=80)

        self.assertLessEqual(len(text), 80)
        self.assertTrue(text.endswith(TRUNCATION_NOTICE))

    def test_fit_slack_text_truncates_by_utf8_bytes(self) -> None:
        text = fit_slack_text("あ" * 100, limit=1000, max_bytes=120)

        self.assertLessEqual(len(text.encode("utf-8")), 120)
        self.assertTrue(text.endswith(TRUNCATION_NOTICE))

    def test_fit_slack_text_does_not_split_multibyte_boundary(self) -> None:
        text = fit_slack_text("あい", limit=10, max_bytes=4, max_json_bytes=1000)

        self.assertEqual(text, "あ")
        self.assertLessEqual(len(text.encode("utf-8")), 4)

    def test_fit_slack_text_truncates_by_json_escaped_bytes(self) -> None:
        text = fit_slack_text("あ" * 100, limit=1000, max_bytes=1000, max_json_bytes=500)

        self.assertLessEqual(len(__import__("json").dumps(text)), 500)
        self.assertTrue(text.endswith(TRUNCATION_NOTICE))

    def test_update_slack_message_retries_shorter_text(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def chat_update(self, *, channel: str, ts: str, text: str) -> None:
                self.calls.append(text)
                if len(self.calls) == 1:
                    raise RuntimeError("msg_too_long")

        client = Client()

        class Logger:
            def warning(self, message: str, *args: object) -> None:
                pass

            def error(self, message: str, *args: object, **kwargs: object) -> None:
                pass

            def exception(self, message: str) -> None:
                pass

        update_slack_message(
            client,
            channel="C123",
            ts="123.456",
            text="a" * 100,
            error_text="error",
            logger=Logger(),  # type: ignore[arg-type]
        )

        self.assertEqual(len(client.calls), 2)
        self.assertLess(len(client.calls[1]), len(client.calls[0]))

    def test_update_slack_message_sends_error_text_after_repeated_msg_too_long(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def chat_update(self, *, channel: str, ts: str, text: str) -> None:
                self.calls.append(text)
                if text != "error":
                    raise RuntimeError("msg_too_long")

        class Logger:
            def warning(self, message: str, *args: object) -> None:
                pass

            def error(self, message: str, *args: object, **kwargs: object) -> None:
                pass

            def exception(self, message: str) -> None:
                pass

        client = Client()

        update_slack_message(
            client,
            channel="C123",
            ts="123.456",
            text="あ" * 10000,
            error_text="error",
            logger=Logger(),  # type: ignore[arg-type]
        )

        self.assertEqual(client.calls[-1], "error")
        self.assertGreaterEqual(len(client.calls), 4)


if __name__ == "__main__":
    unittest.main()
