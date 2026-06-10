from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rulebot.quota_store import MonthlyQuotaStore
from rulebot.token_usage import TokenUsage


class QuotaStoreTest(unittest.TestCase):
    def test_calculates_per_user_limit_from_codex_monthly_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MonthlyQuotaStore(
                Path(tmp) / "usage.sqlite3",
                monthly_token_limit=1000000,
                quota_users=10,
            )

            snapshot = store.get_snapshot("U123", month="2026-05")

        self.assertTrue(snapshot.enabled)
        self.assertEqual(snapshot.limit_tokens, 100000)
        self.assertEqual(snapshot.remaining_tokens, 100000)

    def test_records_usage_by_user_and_month(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MonthlyQuotaStore(
                Path(tmp) / "usage.sqlite3",
                monthly_token_limit=1000,
                quota_users=2,
            )
            first = store.add_usage(
                "U123",
                TokenUsage(input_tokens=100, cached_input_tokens=80, output_tokens=25),
                month="2026-05",
            )
            second = store.add_usage("U123", TokenUsage(input_tokens=50, reasoning_output_tokens=10), month="2026-05")
            other_user = store.get_snapshot("U999", month="2026-05")
            next_month = store.get_snapshot("U123", month="2026-06")

        self.assertEqual(first.used_tokens, 45)
        self.assertEqual(second.used_tokens, 105)
        self.assertEqual(other_user.used_tokens, 0)
        self.assertEqual(next_month.used_tokens, 0)
        self.assertEqual(second.remaining_tokens, 395)

    def test_tracks_total_monthly_usage_across_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MonthlyQuotaStore(
                Path(tmp) / "usage.sqlite3",
                monthly_token_limit=300,
                quota_users=3,
            )
            store.add_usage("U123", TokenUsage(input_tokens=100, cached_input_tokens=20), month="2026-05")
            store.add_usage("U999", TokenUsage(input_tokens=150, output_tokens=50), month="2026-05")

            total = store.get_total_snapshot(month="2026-05")
            next_month = store.get_total_snapshot(month="2026-06")

        self.assertEqual(total.used_tokens, 280)
        self.assertEqual(total.limit_tokens, 300)
        self.assertFalse(total.limited)
        self.assertEqual(next_month.used_tokens, 0)

    def test_from_env_reads_current_agent_variables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "AGENT_USAGE_DB_PATH": str(Path(tmp) / "usage.sqlite3"),
                "AGENT_MONTHLY_TOKEN_LIMIT": "900",
                "AGENT_MONTHLY_QUOTA_USERS": "3",
                "TOKEN_QUOTA_TIMEZONE": "Asia/Tokyo",
            },
            clear=True,
        ):
            store = MonthlyQuotaStore.from_env()

        self.assertEqual(store.monthly_token_limit, 900)
        self.assertEqual(store.per_user_limit, 300)


if __name__ == "__main__":
    unittest.main()
