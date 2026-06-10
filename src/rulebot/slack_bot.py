from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .quota_store import MonthlyQuotaStore, QuotaSnapshot
from .token_usage import TokenUsage, usage_from_dict

LOGGER = logging.getLogger("rulebot.slack_bot")
MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
DEFAULT_PROGRESS_MESSAGE = "回答を生成しています。少しお待ちください。"
DEFAULT_ANSWER_ERROR_MESSAGE = (
    "*回答*\n回答生成中にエラーが発生しました。\n\n*根拠*\n- なし\n\n*不明な点*\n- 回答サービスまたはSlack更新処理でエラーが発生しました。"
)
DEFAULT_SLACK_TEXT_LIMIT = 4000
DEFAULT_SLACK_TEXT_MAX_BYTES = 12000
DEFAULT_SLACK_TEXT_MAX_JSON_BYTES = 24000
TRUNCATION_NOTICE = "\n\n（回答が長すぎるため、Slackの文字数上限に合わせて一部を省略しました。）"


def load_slack_messages(config_path: str | None = None) -> dict[str, str]:
    path = config_path or _required_env("SLACK_MESSAGES_CONFIG")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    messages: dict[str, str] = {}
    for key in ("progress_message", "answer_error_message"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path} must define non-empty {key}")
        messages[key] = value
    return messages


def ask_answer_service(
    question: str,
    *,
    slack_user_id: str = "",
    slack_channel_id: str = "",
    slack_thread_ts: str = "",
) -> dict[str, Any]:
    url = _required_env("ANSWER_SERVICE_URL")
    payload = json.dumps(
        {
            "question": question,
            "slack_user_id": slack_user_id,
            "slack_channel_id": slack_channel_id,
            "slack_thread_ts": slack_thread_ts,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_answer_service_timeout()) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        LOGGER.exception("answer service request failed")
        return {
            "slack_text": f"*回答*\n回答サービスに接続できませんでした。\n\n*根拠*\n- なし\n\n*不明な点*\n- {exc}",
            "usage": TokenUsage().to_dict(),
        }
    return data


def _answer_service_timeout() -> float:
    try:
        return float(_required_env("ANSWER_SERVICE_TIMEOUT_SECONDS"))
    except ValueError as exc:
        raise ValueError("ANSWER_SERVICE_TIMEOUT_SECONDS must be a number") from exc


def _slack_text_limit() -> int:
    limit = _optional_int_env("SLACK_TEXT_LIMIT", DEFAULT_SLACK_TEXT_LIMIT)
    return max(1, limit)


def _slack_text_max_bytes() -> int:
    limit = _optional_int_env("SLACK_TEXT_MAX_BYTES", DEFAULT_SLACK_TEXT_MAX_BYTES)
    return max(1, limit)


def _slack_text_max_json_bytes() -> int:
    limit = _optional_int_env("SLACK_TEXT_MAX_JSON_BYTES", DEFAULT_SLACK_TEXT_MAX_JSON_BYTES)
    return max(1, limit)


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _json_escaped_len(text: str) -> int:
    return len(json.dumps(text))


def _truncate_utf8(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def fit_slack_text(
    text: str,
    *,
    limit: int | None = None,
    max_bytes: int | None = None,
    max_json_bytes: int | None = None,
) -> str:
    limit = _slack_text_limit() if limit is None else max(1, limit)
    max_bytes = _slack_text_max_bytes() if max_bytes is None else max(1, max_bytes)
    max_json_bytes = _slack_text_max_json_bytes() if max_json_bytes is None else max(1, max_json_bytes)
    if len(text) <= limit and _utf8_len(text) <= max_bytes and _json_escaped_len(text) <= max_json_bytes:
        return text

    notice_len = len(TRUNCATION_NOTICE)
    notice_bytes = _utf8_len(TRUNCATION_NOTICE)
    notice_json_bytes = _json_escaped_len(TRUNCATION_NOTICE)
    if limit <= notice_len or max_bytes <= notice_bytes or max_json_bytes <= notice_json_bytes:
        return _truncate_to_slack_limits(text, limit=limit, max_bytes=max_bytes, max_json_bytes=max_json_bytes)

    body_limit = limit - notice_len
    body_max_bytes = max_bytes - notice_bytes
    body_max_json_bytes = max_json_bytes - notice_json_bytes
    body = _truncate_to_slack_limits(
        text,
        limit=body_limit,
        max_bytes=body_max_bytes,
        max_json_bytes=body_max_json_bytes,
    ).rstrip()
    return f"{body}{TRUNCATION_NOTICE}"


def _truncate_to_slack_limits(text: str, *, limit: int, max_bytes: int, max_json_bytes: int) -> str:
    candidate = _truncate_utf8(text[:limit], max_bytes)
    while candidate and _json_escaped_len(candidate) > max_json_bytes:
        candidate = candidate[: max(0, len(candidate) - max(1, len(candidate) // 4))]
        candidate = _truncate_utf8(candidate, max_bytes)
    return candidate


def _is_msg_too_long_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            return response.get("error") == "msg_too_long"
        except AttributeError:
            pass
    return "msg_too_long" in str(exc)


def _slack_update_attempts(text: str) -> list[str]:
    attempts: list[str] = []
    for limit, max_bytes, max_json_bytes in (
        (_slack_text_limit(), _slack_text_max_bytes(), _slack_text_max_json_bytes()),
        (2000, 6000, 12000),
        (1000, 3000, 6000),
    ):
        candidate = fit_slack_text(text, limit=limit, max_bytes=max_bytes, max_json_bytes=max_json_bytes)
        if not attempts or candidate != attempts[-1]:
            attempts.append(candidate)
    return attempts


def update_slack_message(
    client: Any,
    *,
    channel: str,
    ts: str,
    text: str,
    error_text: str,
    logger: logging.Logger,
) -> None:
    last_error: Exception | None = None
    for attempt_text in _slack_update_attempts(text):
        try:
            client.chat_update(channel=channel, ts=ts, text=attempt_text)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if not _is_msg_too_long_error(exc):
                break
            logger.warning(
                "Slack message too long; retrying shorter update chars=%s utf8_bytes=%s json_bytes=%s",
                len(attempt_text),
                _utf8_len(attempt_text),
                _json_escaped_len(attempt_text),
            )

    if last_error is not None:
        logger.error(
            "failed to update Slack message; sending configured error text",
            exc_info=(type(last_error), last_error, last_error.__traceback__),
        )

    try:
        client.chat_update(channel=channel, ts=ts, text=fit_slack_text(error_text, limit=1000, max_bytes=3000, max_json_bytes=6000))
    except Exception:  # noqa: BLE001
        logger.exception("failed to update Slack message with configured error text")


def extract_question(event: dict[str, Any]) -> str:
    text = str(event.get("text", ""))
    return MENTION_RE.sub("", text).strip()


def build_quota_footer(usage: TokenUsage, snapshot: QuotaSnapshot, *, chargeable: bool = True) -> str:
    if not snapshot.enabled:
        return ""
    charge_note = "" if chargeable else "\n- 今回分は月間quotaに加算していません"
    return (
        "\n\n*トークン使用量*\n"
        f"- 今回quota対象: {usage.effective_tokens:,} tokens\n"
        f"- 総使用量（参考）: {usage.total_tokens:,} tokens\n"
        f"- キャッシュ済み入力（参考）: {usage.cached_input_tokens:,} tokens\n"
        f"- 今月: {snapshot.used_tokens:,} / {snapshot.limit_tokens:,} tokens\n"
        f"- 残り: {snapshot.remaining_tokens:,} tokens"
        f"{charge_note}"
    )


def build_quota_exceeded_message(snapshot: QuotaSnapshot) -> str:
    return (
        "*回答*\n"
        "今月のトークン上限に達しました。翌月まで利用できません。\n\n"
        "*根拠*\n"
        "- なし\n\n"
        "*不明な点*\n"
        "- 管理者に月次割当の変更を依頼してください。"
        f"{build_quota_footer(TokenUsage(), snapshot)}"
    )


def build_total_quota_exceeded_message(snapshot: QuotaSnapshot) -> str:
    return (
        "*回答*\n"
        "Bot全体の月間トークン使用量上限に達しました。翌月まで利用できません。\n\n"
        "*根拠*\n"
        "- なし\n\n"
        "*不明な点*\n"
        "- 管理者に月間上限の変更を依頼してください。"
    )


def build_app():
    from slack_bolt import App

    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    messages = load_slack_messages()
    quota_store = MonthlyQuotaStore.from_env()

    @app.event("app_mention")
    def handle_app_mention(event: dict[str, Any], client: Any, logger: logging.Logger) -> None:
        question = extract_question(event)
        channel = event["channel"]
        user_id = str(event.get("user", "unknown"))
        thread_ts = event.get("thread_ts") or event["ts"]
        logger.info(
            "received app_mention channel=%s user=%s ts=%s empty=%s",
            channel,
            user_id,
            event.get("ts"),
            not question,
        )
        progress = client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=messages["progress_message"],
        )
        progress_ts = progress["ts"]
        try:
            total_snapshot = quota_store.get_total_snapshot()
            snapshot = quota_store.get_snapshot(user_id)
            if total_snapshot.limited:
                text = build_total_quota_exceeded_message(total_snapshot)
            elif snapshot.limited:
                text = build_quota_exceeded_message(snapshot)
            else:
                data = ask_answer_service(
                    question,
                    slack_user_id=user_id,
                    slack_channel_id=str(channel),
                    slack_thread_ts=str(thread_ts),
                )
                usage = usage_from_dict(data.get("usage"))
                usage_chargeable = bool(data.get("usage_chargeable", True))
                if usage_chargeable:
                    snapshot = quota_store.add_usage(user_id, usage)
                text = str(data.get("slack_text") or data.get("answer") or "回答を生成できませんでした。")
                text = f"{text}{build_quota_footer(usage, snapshot, chargeable=usage_chargeable)}"
        except Exception:  # noqa: BLE001
            logger.exception("failed to generate answer")
            text = messages["answer_error_message"]
        update_slack_message(
            client,
            channel=channel,
            ts=progress_ts,
            text=text,
            error_text=messages["answer_error_message"],
            logger=logger,
        )

    return app


def main() -> None:
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    logging.basicConfig(level=os.environ["LOG_LEVEL"] if "LOG_LEVEL" in os.environ else "INFO")
    if not _required_env("SLACK_BOT_TOKEN") or not _required_env("SLACK_APP_TOKEN"):
        raise SystemExit("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set to start slack-bot")
    app = build_app()
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


def _required_env(name: str) -> str:
    value = os.environ[name].strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _optional_int_env(name: str, default: int) -> int:
    if name not in os.environ:
        return default
    try:
        return int(os.environ[name].strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


if __name__ == "__main__":
    main()
