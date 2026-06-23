from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .workspace_answer_log import AnswerLogEntry, Citation, JsonlAnswerLog
from .workspace_config import AgentLimits
from .workspace_mcp import WorkspaceMcpTools
from .workspace_records import stable_record_id


VARIANT_GROUPS = (
    ("落とし物", "忘れ物", "遺失物"),
    ("フォーム", "form", "Form"),
    ("締切", "〆切", "期限", "提出期限"),
    ("イベント", "event", "行事"),
)


@dataclass(frozen=True)
class AnswerEnvelope:
    answer: str
    citations: list[Citation]
    used_queries: list[str]
    asker: str
    ts: str
    model: str
    usage: dict[str, int]
    confidence: str
    unknowns: list[str]
    snippet: str = ""
    prior_answer_ids: list[str] = field(default_factory=list)

    def slack_text(self) -> str:
        sources = "\n".join(citation.url for citation in self.citations) or "なし"
        return f"{self.answer}\n\nSources:\n{sources}"


class WorkspaceSearchAgent:
    def __init__(
        self,
        tools: WorkspaceMcpTools,
        *,
        limits: AgentLimits | None = None,
        answer_log: JsonlAnswerLog | None = None,
        model: str = "grep-react",
    ):
        self.tools = tools
        self.limits = limits or AgentLimits()
        self.answer_log = answer_log
        self.model = model

    def answer(self, question: str, *, slack_user_id: str) -> AnswerEnvelope:
        question = question.strip()
        if not question:
            return self._unknown(question, slack_user_id, ["Question is empty."])

        deadline = time.monotonic() + self.limits.max_wall_clock_seconds
        tool_calls = 0
        used_queries: list[str] = []
        prior_answer_ids: list[str] = []
        citations: list[Citation] = []
        snippets: list[str] = []

        prior = self.tools.prior_qa_search(question, limit=3)
        tool_calls += 1
        for item in prior.get("results", []):
            prior_answer_ids.append(str(item.get("answer_id", "")))
            for citation in item.get("citations", []):
                if tool_calls >= self.limits.max_tool_calls or time.monotonic() > deadline:
                    break
                try:
                    resolved = self.tools.resolve_link(str(citation.get("url", "")), slack_user_id=slack_user_id)
                except Exception:
                    continue
                tool_calls += 1
                citations.append(_citation_from_record(resolved))
                snippets.append(str(resolved.get("text", ""))[:240])

        for pattern in build_regex_patterns(question):
            if tool_calls >= self.limits.max_tool_calls or time.monotonic() > deadline:
                break
            cursor = ""
            pages = 0
            used_queries.append(pattern)
            while pages < self.limits.max_grep_pages_per_query:
                result = self.tools.grep_search(pattern, cursor=cursor, slack_user_id=slack_user_id)
                tool_calls += 1
                pages += 1
                for match in result.get("matches", []):
                    if len(citations) >= self.limits.max_records_loaded:
                        break
                    citations.append(
                        Citation(
                            url=str(match.get("anchor_url", "")),
                            record_id=str(match.get("record_id", "")),
                            source_type=str(match.get("source_type", "")),
                        )
                    )
                    snippets.append(str(match.get("snippet", "")))
                cursor = str(result.get("next_cursor", ""))
                if result.get("complete", True) or not cursor or tool_calls >= self.limits.max_tool_calls:
                    break
            if citations:
                break

        unique_citations = _dedupe_citations(citations)
        if not unique_citations:
            envelope = self._unknown(question, slack_user_id, ["Primary source could not be verified."], used_queries=used_queries)
        else:
            envelope = AnswerEnvelope(
                answer=_compose_answer(question, snippets),
                citations=unique_citations,
                used_queries=used_queries,
                asker=slack_user_id,
                ts=datetime.now(timezone.utc).isoformat(),
                model=self.model,
                usage={"input_tokens": 0, "output_tokens": 0},
                confidence="medium",
                unknowns=[],
                snippet="\n".join(snippets[:3]),
                prior_answer_ids=[item for item in prior_answer_ids if item],
            )
        if self.answer_log is not None:
            self.answer_log.append(_log_entry(question, envelope))
        return envelope

    def _unknown(
        self,
        question: str,
        slack_user_id: str,
        unknowns: list[str],
        *,
        used_queries: list[str] | None = None,
    ) -> AnswerEnvelope:
        return AnswerEnvelope(
            answer="一次ソースで確認できる根拠が見つかりませんでした。",
            citations=[],
            used_queries=used_queries or [],
            asker=slack_user_id,
            ts=datetime.now(timezone.utc).isoformat(),
            model=self.model,
            usage={"input_tokens": 0, "output_tokens": 0},
            confidence="none",
            unknowns=unknowns,
        )


def build_regex_patterns(question: str) -> list[str]:
    words = [word for word in re.split(r"\s+", question) if word]
    patterns: list[str] = []
    for group in VARIANT_GROUPS:
        if any(item.casefold() in question.casefold() for item in group):
            patterns.append("|".join(re.escape(item) for item in group))
    for word in words:
        cleaned = word.strip("。、,.!?！？")
        if cleaned:
            patterns.append(re.escape(cleaned))
    return _dedupe_strings(patterns)


def is_human_trigger(event: dict[str, object]) -> bool:
    return (event.get("type") in {"app_mention", "slash_command"}) and not bool(event.get("bot_id"))


def _compose_answer(question: str, snippets: list[str]) -> str:
    compact = " ".join(snippet.strip() for snippet in snippets if snippet.strip())
    if not compact:
        return "一次ソースを確認しました。"
    return f"確認できた一次ソースでは、{compact[:500]}"


def _citation_from_record(record: dict[str, object]) -> Citation:
    return Citation(
        url=str(record.get("anchor_url", "")),
        record_id=str(record.get("record_id", "")),
        source_type=str(record.get("source_type", "")),
    )


def _dedupe_citations(citations: list[Citation]) -> list[Citation]:
    seen: set[tuple[str, str]] = set()
    result: list[Citation] = []
    for citation in citations:
        key = (citation.record_id, citation.url)
        if citation.url and key not in seen:
            seen.add(key)
            result.append(citation)
    return result


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _log_entry(question: str, envelope: AnswerEnvelope) -> AnswerLogEntry:
    answer_id = stable_record_id("answer", {"question": question, "ts": envelope.ts, "asker": envelope.asker})
    return AnswerLogEntry(
        answer_id=answer_id,
        question=question,
        answer=envelope.answer,
        citations=envelope.citations,
        used_queries=envelope.used_queries,
        asker=envelope.asker,
        ts=envelope.ts,
        model=envelope.model,
        usage=envelope.usage,
        confidence=envelope.confidence,
        unknowns=envelope.unknowns,
        prior_answer_ids=envelope.prior_answer_ids,
        snippet=envelope.snippet,
    )
