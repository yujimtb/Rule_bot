from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_cli import AgentRunResult
from .token_usage import TokenUsage, usage_from_dict

LOGGER = logging.getLogger("rulebot.codex_app_server")


class CodexAppServerError(RuntimeError):
    pass


class CodexUsageLimitError(CodexAppServerError):
    pass


@dataclass
class _SeedState:
    fingerprint: str
    thread_id: str
    free_next_answer: bool = False


@dataclass
class _AnswerResult:
    text: str
    usage: TokenUsage
    usage_chargeable: bool


@dataclass
class _TurnResult:
    text: str
    usage: TokenUsage
    status: str
    error: dict[str, Any] | None = None


_CLIENT: CodexAppServerClient | None = None
_CLIENT_LOCK = threading.Lock()


def answer_with_codex_app_server(question: str, docs_dir: str | Path) -> AgentRunResult:
    client = _get_client()
    try:
        result = client.answer(question, Path(docs_dir))
    except CodexUsageLimitError:
        raise
    except Exception:
        _reset_client()
        raise
    return AgentRunResult(
        text=result.text,
        usage=result.usage,
        returncode=0,
        provider="codex_app_server",
        usage_chargeable=result.usage_chargeable,
    )


def _get_client() -> CodexAppServerClient:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = CodexAppServerClient()
        return _CLIENT


def _reset_client() -> None:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            _CLIENT.close()
        _CLIENT = None


class CodexAppServerClient:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._next_id = 1
        self._seed: _SeedState | None = None
        self._pending_notifications: list[dict[str, Any]] = []
        self._stdout: queue.Queue[str | None] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._proc = self._start_process()
        self._start_reader_threads()
        self._initialize()

    def answer(self, question: str, docs_dir: Path) -> _AnswerResult:
        with self._lock:
            seed = self._ensure_seed(docs_dir)
            return self._answer_on_seed_thread(question, seed)

    def _answer_on_seed_thread(self, question: str, seed: _SeedState) -> _AnswerResult:
        result = self._turn(seed.thread_id, _answer_prompt(question), _answer_timeout())
        try:
            self._raise_for_turn_error(result.error)
            if result.status != "completed":
                raise CodexAppServerError(f"answer turn did not complete: {result.status}")
            usage_chargeable = not seed.free_next_answer
            seed.free_next_answer = False
            LOGGER.info(
                "codex app-server answer usage thread_id=%s mode=rollback chargeable=%s usage=%s",
                seed.thread_id,
                usage_chargeable,
                result.usage.to_dict(),
            )
            return _AnswerResult(
                text=result.text.strip(),
                usage=result.usage,
                usage_chargeable=usage_chargeable,
            )
        finally:
            try:
                self._request("thread/rollback", {"threadId": seed.thread_id, "numTurns": 1}, timeout=20)
            except CodexAppServerError as exc:
                LOGGER.warning("failed to rollback answer turn thread_id=%s error=%s", seed.thread_id, exc)
                _reset_client()

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def _start_process(self) -> subprocess.Popen[str]:
        command = _app_server_command()
        LOGGER.info("starting codex app-server command=%s", command)
        try:
            return subprocess.Popen(
                command,
                cwd=_workdir(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise CodexAppServerError(str(exc)) from exc

    def _start_reader_threads(self) -> None:
        assert self._proc.stdout is not None
        assert self._proc.stderr is not None

        def read_stdout() -> None:
            for line in self._proc.stdout:
                self._stdout.put(line)
            self._stdout.put(None)

        def read_stderr() -> None:
            for line in self._proc.stderr:
                self._stderr_lines.append(line.rstrip())

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()

    def _initialize(self) -> None:
        result = self._request(
            "initialize",
            {
                "clientInfo": {"name": "rulebot-answer-service", "version": "0.1"},
                "capabilities": {"experimentalApi": True},
            },
            timeout=20,
        )
        LOGGER.info("codex app-server initialized result=%s", result)

    def _ensure_seed(self, docs_dir: Path) -> _SeedState:
        docs_text, fingerprint = _read_docs(docs_dir)
        if self._seed is not None and self._seed.fingerprint == fingerprint:
            return self._seed

        thread_id = self._start_thread(ephemeral=False)
        seed_result = self._turn(thread_id, _seed_prompt(docs_text), _seed_timeout())
        self._raise_for_turn_error(seed_result.error)
        if seed_result.status != "completed":
            raise CodexAppServerError(f"seed turn did not complete: {seed_result.status}")
        self._request("thread/compact/start", {"threadId": thread_id}, timeout=20)
        compact_result = self._wait_turn(thread_id, _seed_timeout())
        self._raise_for_turn_error(compact_result.error)
        if compact_result.status != "completed":
            raise CodexAppServerError(f"compact turn did not complete: {compact_result.status}")

        self._seed = _SeedState(fingerprint=fingerprint, thread_id=thread_id, free_next_answer=True)
        LOGGER.info(
            "prepared codex app-server seed thread_id=%s seed_usage=%s compact_usage=%s",
            thread_id,
            seed_result.usage.to_dict(),
            compact_result.usage.to_dict(),
        )
        return self._seed

    def _start_thread(self, *, ephemeral: bool) -> str:
        result = self._request(
            "thread/start",
            {
                "cwd": _workdir(),
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "approvalsReviewer": "user",
                "model": _model(),
                "developerInstructions": _developer_instructions(),
                "ephemeral": ephemeral,
            },
            timeout=30,
        )
        try:
            return str(result["thread"]["id"])
        except (KeyError, TypeError) as exc:
            raise CodexAppServerError(f"thread/start returned unexpected result: {result}") from exc

    def _turn(self, thread_id: str, text: str, timeout: float) -> _TurnResult:
        self._request(
            "turn/start",
            {
                "threadId": thread_id,
                "effort": _reasoning_effort(),
                "input": [{"type": "text", "text": text}],
            },
            timeout=20,
        )
        return self._wait_turn(thread_id, timeout)

    def _wait_turn(self, thread_id: str, timeout: float) -> _TurnResult:
        deadline = time.monotonic() + timeout
        text = ""
        usage = TokenUsage()
        while time.monotonic() < deadline:
            message = self._next_notification(deadline)
            method = message.get("method")
            params = message.get("params") or {}
            if "id" in message and method:
                self._answer_server_request(message)
                continue
            if params.get("threadId") != thread_id:
                continue
            if method == "thread/tokenUsage/updated":
                usage = usage_from_dict((params.get("tokenUsage") or {}).get("last"))
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage":
                    item_text = item.get("text")
                    if isinstance(item_text, str) and item_text.strip():
                        text = item_text.strip()
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if not text:
                    text = _extract_agent_text(turn.get("items"))
                usage = self._drain_final_usage(
                    thread_id=thread_id,
                    turn_id=str(turn.get("id") or params.get("turnId") or ""),
                    usage=usage,
                )
                return _TurnResult(
                    text=text,
                    usage=usage,
                    status=str(turn.get("status") or ""),
                    error=turn.get("error"),
                )
            elif method == "error":
                error = params.get("error")
                if not params.get("willRetry"):
                    return _TurnResult(text=text, usage=usage, status="failed", error=error)
        raise CodexAppServerError("timed out waiting for codex app-server turn")

    def _drain_final_usage(self, *, thread_id: str, turn_id: str, usage: TokenUsage) -> TokenUsage:
        drain_seconds = _usage_drain_seconds()
        if drain_seconds <= 0:
            return usage
        deadline = time.monotonic() + drain_seconds
        latest = usage
        while time.monotonic() < deadline:
            try:
                message = self._read_message(deadline)
            except CodexAppServerError:
                break
            method = message.get("method")
            params = message.get("params") or {}
            if "id" in message and method:
                self._answer_server_request(message)
                continue
            if method == "thread/tokenUsage/updated" and params.get("threadId") == thread_id:
                if not turn_id or params.get("turnId") == turn_id:
                    latest = usage_from_dict((params.get("tokenUsage") or {}).get("last"))
                    continue
            if "method" in message and "id" not in message:
                self._pending_notifications.append(message)
        return latest

    def _request(self, method: str, params: dict[str, Any], *, timeout: float) -> Any:
        request_id = self._send(method, params)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self._read_message(deadline)
            if "id" in message and "method" in message:
                self._answer_server_request(message)
                continue
            if message.get("id") != request_id:
                if "method" in message and "id" not in message:
                    self._pending_notifications.append(message)
                continue
            if "error" in message:
                raise CodexAppServerError(str(message["error"]))
            return message.get("result")
        raise CodexAppServerError(f"timed out waiting for app-server response method={method}")

    def _next_notification(self, deadline: float) -> dict[str, Any]:
        if self._pending_notifications:
            return self._pending_notifications.pop(0)
        return self._read_message(deadline)

    def _send(self, method: str, params: dict[str, Any]) -> int:
        if self._proc.poll() is not None:
            raise CodexAppServerError(f"codex app-server exited code={self._proc.returncode}: {self._stderr()}")
        request_id = self._next_id
        self._next_id += 1
        message = {"id": request_id, "method": method, "params": params}
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        return request_id

    def _read_message(self, deadline: float) -> dict[str, Any]:
        if self._proc.poll() is not None and self._stdout.empty():
            raise CodexAppServerError(f"codex app-server exited code={self._proc.returncode}: {self._stderr()}")
        timeout = max(deadline - time.monotonic(), 0.01)
        try:
            line = self._stdout.get(timeout=timeout)
        except queue.Empty as exc:
            raise CodexAppServerError("timed out waiting for app-server output") from exc
        if line is None:
            raise CodexAppServerError(f"codex app-server closed stdout: {self._stderr()}")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexAppServerError(f"invalid app-server JSON: {line!r}") from exc

    def _answer_server_request(self, request: dict[str, Any]) -> None:
        method = request.get("method")
        request_id = request.get("id")
        if method == "item/commandExecution/requestApproval":
            result: dict[str, Any] = {"decision": "accept"}
        elif method == "item/fileChange/requestApproval":
            result = {"decision": "cancel"}
        elif method == "item/permissions/requestApproval":
            result = {"permissions": {"fileSystem": None, "network": None}, "scope": "turn"}
        elif method == "item/tool/requestUserInput":
            result = {"input": ""}
        else:
            result = {}
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps({"id": request_id, "result": result}, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _raise_for_turn_error(self, error: dict[str, Any] | None) -> None:
        if not error:
            return
        if error.get("codexErrorInfo") == "usageLimitExceeded":
            raise CodexUsageLimitError(str(error.get("message") or "Codex usage limit exceeded"))
        raise CodexAppServerError(str(error.get("message") or error))

    def _stderr(self) -> str:
        return "\n".join(self._stderr_lines[-20:])


def _extract_agent_text(items: object) -> str:
    if not isinstance(items, list):
        return ""
    for item in items:
        if isinstance(item, dict) and item.get("type") == "agentMessage":
            text = item.get("text")
            if isinstance(text, str):
                return text.strip()
    return ""


def _read_docs(docs_dir: Path) -> tuple[str, str]:
    blocks: list[str] = []
    digest = hashlib.sha256()
    for path in sorted(docs_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        digest.update(b"\0")
        blocks.append(f"# {path.name}\n{text}")
    if not blocks:
        raise CodexAppServerError(f"no markdown docs found in {docs_dir}")
    return "\n\n---\n\n".join(blocks), digest.hexdigest()


def _seed_prompt(docs_text: str) -> str:
    return (
        "以下は信頼済みの館内規則です。後続の質問回答で唯一の根拠として使えるように保持してください。"
        "このターンでは内容説明をせず、READYだけ返してください。\n\n"
        f"{docs_text}"
    )


def _answer_prompt(question: str) -> str:
    return (
        "保持している館内規則だけを根拠として日本語で回答してください。"
        "根拠にない内容は不明としてください。"
        "回答はJSONのみで、形式は"
        '{"answer":"回答本文","citations":["根拠文書名または規則名"],"unknowns":["不明点"]}'
        "です。\n\n"
        f"質問: {question}"
    )


def _developer_instructions() -> str:
    return (
        "あなたはSHIMOKITA COLLEGEの館内規則・生活ルール回答Botです。"
        "根拠として与えられた規則だけを使い、日本語で簡潔に回答してください。"
        "不明な点は推測しないでください。"
    )


def _app_server_command() -> list[str]:
    raw = os.environ["CODEX_APP_SERVER_COMMAND"].strip() if "CODEX_APP_SERVER_COMMAND" in os.environ else ""
    command = shlex.split(raw) if raw else ["codex", "app-server", "--listen", "stdio://"]
    if _bool_env("CODEX_APP_SERVER_REMOTE_COMPACTION_V2") and "remote_compaction_v2" not in command:
        command.extend(["--enable", "remote_compaction_v2"])
    return command


def _model() -> str:
    return _required_env("CODEX_DEFAULT_MODEL")


def _reasoning_effort() -> str:
    return _required_env("CODEX_REASONING_EFFORT")


def _workdir() -> str:
    return _required_env("AGENT_WORKDIR")


def _seed_timeout() -> float:
    return _float_env("CODEX_APP_SERVER_SEED_TIMEOUT_SECONDS")


def _answer_timeout() -> float:
    return _float_env("CODEX_APP_SERVER_ANSWER_TIMEOUT_SECONDS")


def _usage_drain_seconds() -> float:
    return _float_env("CODEX_APP_SERVER_USAGE_DRAIN_SECONDS")


def _float_env(name: str) -> float:
    try:
        return float(_required_env(name))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _bool_env(name: str) -> bool:
    value = _required_env(name).lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _required_env(name: str) -> str:
    value = os.environ[name].strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value
