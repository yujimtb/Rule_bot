from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass

from .token_usage import TokenUsage, parse_claude_json_output, parse_codex_json_output

AUTH_ERROR_PATTERNS = (
    "401 unauthorized",
    "access token",
    "refresh token",
    "refresh_token_reused",
    "sign in again",
    "log out and sign in again",
    "codex login",
)


@dataclass(frozen=True)
class AgentRunResult:
    text: str
    usage: TokenUsage
    returncode: int
    stderr: str = ""
    timed_out: bool = False
    provider: str = "codex"
    usage_chargeable: bool = True


def run_agent_cli(prompt: str, *, purpose: str) -> AgentRunResult:
    provider = _required_env("AGENT_CLI_PROVIDER").lower()
    if provider == "codex":
        return _run_codex(prompt, purpose=purpose)
    if provider == "claude":
        return _run_claude(prompt, purpose=purpose)
    return AgentRunResult(
        text="",
        usage=TokenUsage(),
        returncode=2,
        stderr=f"unsupported AGENT_CLI_PROVIDER={provider}",
        provider=provider,
    )


def classify_agent_error(detail: str) -> str:
    normalized = detail.lower()
    if any(pattern in normalized for pattern in AUTH_ERROR_PATTERNS):
        return "auth"
    if "rate limit" in normalized or "usage limit" in normalized or "quota" in normalized:
        return "usage_limit"
    if "timed out" in normalized or "timeout" in normalized:
        return "timeout"
    return "agent_error"


def user_facing_agent_error(error_type: str) -> str:
    if error_type == "auth":
        return "回答エンジンの認証が切れています。管理者はanswer-serviceコンテナでCodexに再ログインしてください。"
    if error_type == "usage_limit":
        return "回答エンジンの利用上限に達している可能性があります。時間をおいて再度試すか、管理者に確認してください。"
    if error_type == "timeout":
        return "回答生成がタイムアウトしました。質問を短くするか、時間をおいて再度試してください。"
    return "回答エンジンでエラーが発生しました。管理者はanswer-serviceのログを確認してください。"


def _run_codex(prompt: str, *, purpose: str) -> AgentRunResult:
    reasoning_effort = _codex_reasoning_effort(purpose)
    command = [
        "codex",
        "exec",
        "--json",
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--cd",
        _workdir(),
        prompt,
    ]
    timeout = _timeout_seconds(purpose)
    completed = _run_command(command, timeout=timeout, provider="codex")
    if completed.timed_out:
        return completed
    text, usage = parse_codex_json_output(completed.text)
    return AgentRunResult(
        text=text,
        usage=usage,
        returncode=completed.returncode,
        stderr=completed.stderr,
        provider="codex",
    )


def _run_claude(prompt: str, *, purpose: str) -> AgentRunResult:
    command = [
        "claude",
        "--bare",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--no-session-persistence",
    ]
    model = os.environ["CLAUDE_MODEL"].strip() if "CLAUDE_MODEL" in os.environ else ""
    if model:
        command.extend(["--model", model])

    permission_mode = _required_env("CLAUDE_PERMISSION_MODE")
    if permission_mode:
        command.extend(["--permission-mode", permission_mode])

    extra_args = os.environ["CLAUDE_EXTRA_ARGS"].strip() if "CLAUDE_EXTRA_ARGS" in os.environ else ""
    if extra_args:
        command.extend(shlex.split(extra_args))

    timeout = _timeout_seconds(purpose)
    completed = _run_command(command, timeout=timeout, provider="claude")
    if completed.timed_out:
        return completed
    text, usage = parse_claude_json_output(completed.text)
    return AgentRunResult(
        text=text,
        usage=usage,
        returncode=completed.returncode,
        stderr=completed.stderr,
        provider="claude",
    )


def _run_command(command: list[str], *, timeout: float, provider: str) -> AgentRunResult:
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return AgentRunResult(text="", usage=TokenUsage(), returncode=124, timed_out=True, provider=provider)
    except OSError as exc:
        return AgentRunResult(text="", usage=TokenUsage(), returncode=127, stderr=str(exc), provider=provider)

    return AgentRunResult(
        text=completed.stdout.strip(),
        usage=TokenUsage(),
        returncode=completed.returncode,
        stderr=completed.stderr.strip(),
        provider=provider,
    )


def _codex_reasoning_effort(purpose: str) -> str:
    if purpose == "query":
        return _required_env("CODEX_QUERY_PLANNER_REASONING_EFFORT")
    return _required_env("CODEX_REASONING_EFFORT")


def _timeout_seconds(purpose: str) -> float:
    if purpose == "query":
        name = "AGENT_QUERY_TIMEOUT_SECONDS"
    else:
        name = "AGENT_ANSWER_TIMEOUT_SECONDS"
    try:
        return float(_required_env(name))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _workdir() -> str:
    return _required_env("AGENT_WORKDIR")


def _required_env(name: str) -> str:
    value = os.environ[name].strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def extract_json_object(text: str) -> dict[str, object] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None
