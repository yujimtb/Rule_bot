from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .agent_cli import classify_agent_error, user_facing_agent_error
from .document_store import load_chunks
from .retrieval import Retriever, SearchHit
from .token_usage import usage_from_dict

LOGGER = logging.getLogger("rulebot.answer_engine")


@dataclass(frozen=True)
class Answer:
    answer: str
    citations: list[str]
    unknowns: list[str]
    usage: dict[str, int] = field(default_factory=dict)
    usage_chargeable: bool = True

    def to_slack_text(self) -> str:
        citations = "\n".join(f"- {citation}" for citation in self.citations) or "- なし"
        unknowns = "\n".join(f"- {unknown}" for unknown in self.unknowns) or "- なし"
        return f"*回答*\n{self.answer}\n\n*根拠*\n{citations}\n\n*不明な点*\n{unknowns}"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["slack_text"] = self.to_slack_text()
        return data


def answer_question(
    question: str,
    docs_dir: str | Path,
    *,
    top_k: int = 3,
    min_score: float = 0.08,
    backend: str = "local",
) -> Answer:
    question = question.strip()
    if not question:
        return Answer(
            answer="質問内容を読み取れませんでした。メンションの後に質問を書いてください。",
            citations=[],
            unknowns=["質問が空です。"],
        )

    if backend == "agent":
        return _answer_with_agent(question=question, docs_dir=docs_dir)

    chunks = load_chunks(docs_dir)
    if not chunks:
        return Answer(
            answer="現行ドキュメントでは確認できません。",
            citations=[],
            unknowns=["回答用ドキュメントが読み込まれていません。"],
        )

    hits = Retriever(chunks).search(question, top_k=top_k)
    useful_hits = [hit for hit in hits if hit.score >= min_score]
    if not useful_hits:
        return Answer(
            answer="現行ドキュメントでは確認できません。",
            citations=[],
            unknowns=["質問に一致するルールが見つかりませんでした。"],
        )

    return _compose_local_answer(useful_hits)


def _compose_local_answer(hits: list[SearchHit]) -> Answer:
    main = hits[0].chunk
    snippet = _compact(main.text)
    citations = [f"{hit.chunk.source}: {hit.chunk.location}" for hit in hits]
    return Answer(
        answer=f"関連するルールは以下です。\n{snippet}",
        citations=citations,
        unknowns=[],
    )


def _compact(text: str, limit: int = 600) -> str:
    normalized_lines = [line.strip() for line in text.splitlines() if line.strip()]
    compact = "\n".join(normalized_lines)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _answer_with_agent(question: str, docs_dir: str | Path) -> Answer:
    if _required_env("AGENT_CLI_PROVIDER").lower() == "codex_app_server":
        return _answer_with_codex_app_server_in_process(question, docs_dir)

    command = _required_env("AGENT_COMMAND")

    payload = {
        "question": question,
        "docs_dir": str(docs_dir),
        "required_format": {"answer": "string", "citations": ["string"], "unknowns": ["string"]},
    }
    timeout = float(_required_env("AGENT_TIMEOUT_SECONDS"))
    try:
        completed = subprocess.run(
            shlex.split(command),
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        LOGGER.warning("agent command timed out command=%s timeout=%s", command, timeout)
        return Answer(answer="回答生成に失敗しました。", citations=[], unknowns=[user_facing_agent_error("timeout")])
    except OSError as exc:
        LOGGER.warning("agent command failed to start command=%s error=%s", command, exc)
        return Answer(answer="回答生成に失敗しました。", citations=[], unknowns=[user_facing_agent_error("agent_error")])

    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"agent exited with code {completed.returncode}"
        error_type = classify_agent_error(detail)
        LOGGER.warning("agent command returned nonzero code=%s type=%s detail=%s", completed.returncode, error_type, detail)
        return Answer(answer="回答生成に失敗しました。", citations=[], unknowns=[user_facing_agent_error(error_type)])

    output = completed.stdout.strip()
    try:
        data = json.loads(output)
        return _answer_from_agent_data(data)
    except json.JSONDecodeError:
        return Answer(answer=output or "現行ドキュメントでは確認できません。", citations=[], unknowns=[])


def _answer_with_codex_app_server_in_process(question: str, docs_dir: str | Path) -> Answer:
    from .codex_agent import _run_codex_app_server

    data = _run_codex_app_server(question, Path(docs_dir))
    return _answer_from_agent_data(data)


def _answer_from_agent_data(data: dict[str, object]) -> Answer:
    return Answer(
        answer=str(data.get("answer", "")).strip() or "現行ドキュメントでは確認できません。",
        citations=[str(item) for item in data.get("citations", [])],
        unknowns=[str(item) for item in data.get("unknowns", [])],
        usage=usage_from_dict(data.get("usage")).to_dict(),
        usage_chargeable=bool(data.get("usage_chargeable", True)),
    )


def _required_env(name: str) -> str:
    value = os.environ[name].strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value
