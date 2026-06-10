from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .token_usage import TokenUsage, usage_from_dict


@dataclass(frozen=True)
class QuotaSnapshot:
    enabled: bool
    month: str
    used_tokens: int
    limit_tokens: int

    @property
    def remaining_tokens(self) -> int:
        return max(self.limit_tokens - self.used_tokens, 0)

    @property
    def limited(self) -> bool:
        return self.enabled and self.used_tokens >= self.limit_tokens

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "month": self.month,
            "used_tokens": self.used_tokens,
            "limit_tokens": self.limit_tokens,
            "remaining_tokens": self.remaining_tokens,
            "limited": self.limited,
        }


class MonthlyQuotaStore:
    def __init__(self, db_path: str | Path, *, monthly_token_limit: int, quota_users: int, timezone: str = "Asia/Tokyo"):
        self.db_path = Path(db_path)
        self.monthly_token_limit = max(int(monthly_token_limit), 0)
        self.quota_users = max(int(quota_users), 0)
        self.timezone = timezone

    @classmethod
    def from_env(cls) -> MonthlyQuotaStore:
        return cls(
            _required_env("AGENT_USAGE_DB_PATH"),
            monthly_token_limit=_int_env("AGENT_MONTHLY_TOKEN_LIMIT"),
            quota_users=_int_env("AGENT_MONTHLY_QUOTA_USERS"),
            timezone=_required_env("TOKEN_QUOTA_TIMEZONE"),
        )

    @property
    def enabled(self) -> bool:
        return self.monthly_token_limit > 0 and self.quota_users > 0

    @property
    def per_user_limit(self) -> int:
        if not self.enabled:
            return 0
        return self.monthly_token_limit // self.quota_users

    def current_month(self) -> str:
        return datetime.now(ZoneInfo(self.timezone)).strftime("%Y-%m")

    def get_snapshot(self, user_id: str, month: str | None = None) -> QuotaSnapshot:
        month = month or self.current_month()
        if not self.enabled:
            return QuotaSnapshot(enabled=False, month=month, used_tokens=0, limit_tokens=0)

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT used_tokens FROM monthly_usage WHERE month = ? AND user_id = ?",
                (month, user_id),
            ).fetchone()
        finally:
            conn.close()
        used_tokens = int(row[0]) if row else 0
        return QuotaSnapshot(enabled=True, month=month, used_tokens=used_tokens, limit_tokens=self.per_user_limit)

    def get_total_snapshot(self, month: str | None = None) -> QuotaSnapshot:
        month = month or self.current_month()
        if not self.enabled:
            return QuotaSnapshot(enabled=False, month=month, used_tokens=0, limit_tokens=0)

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(used_tokens), 0) FROM monthly_usage WHERE month = ?",
                (month,),
            ).fetchone()
        finally:
            conn.close()
        used_tokens = int(row[0]) if row else 0
        return QuotaSnapshot(enabled=True, month=month, used_tokens=used_tokens, limit_tokens=self.monthly_token_limit)

    def add_usage(self, user_id: str, usage: TokenUsage | dict[str, object], month: str | None = None) -> QuotaSnapshot:
        month = month or self.current_month()
        if not self.enabled:
            return QuotaSnapshot(enabled=False, month=month, used_tokens=0, limit_tokens=0)

        token_usage = usage if isinstance(usage, TokenUsage) else usage_from_dict(usage)
        updated_at = datetime.now(ZoneInfo(self.timezone)).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO monthly_usage (
                    month, user_id, used_tokens, input_tokens, cached_input_tokens,
                    output_tokens, reasoning_output_tokens, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(month, user_id) DO UPDATE SET
                    used_tokens = used_tokens + excluded.used_tokens,
                    input_tokens = input_tokens + excluded.input_tokens,
                    cached_input_tokens = cached_input_tokens + excluded.cached_input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    reasoning_output_tokens = reasoning_output_tokens + excluded.reasoning_output_tokens,
                    updated_at = excluded.updated_at
                """,
                (
                    month,
                    user_id,
                    token_usage.effective_tokens,
                    token_usage.input_tokens,
                    token_usage.cached_input_tokens,
                    token_usage.output_tokens,
                    token_usage.reasoning_output_tokens,
                    updated_at,
                ),
            )
            row = conn.execute(
                "SELECT used_tokens FROM monthly_usage WHERE month = ? AND user_id = ?",
                (month, user_id),
            ).fetchone()
            conn.commit()
        finally:
            conn.close()

        used_tokens = int(row[0]) if row else 0
        return QuotaSnapshot(enabled=True, month=month, used_tokens=used_tokens, limit_tokens=self.per_user_limit)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_usage (
                month TEXT NOT NULL,
                user_id TEXT NOT NULL,
                used_tokens INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (month, user_id)
            )
            """
        )
        return conn


def _required_env(name: str) -> str:
    value = os.environ[name].strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _int_env(name: str) -> int:
    try:
        return int(_required_env(name))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
