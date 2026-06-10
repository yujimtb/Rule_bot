from __future__ import annotations

from dataclasses import dataclass, field

from .agent_cli import extract_json_object, run_agent_cli
from .token_usage import TokenUsage


@dataclass(frozen=True)
class QueryPlan:
    search_queries: list[str]
    related_terms: list[str]
    intent: str
    usage: TokenUsage = field(default_factory=TokenUsage)

    def all_queries(self, question: str) -> list[str]:
        queries = [question, *self.search_queries, *self.related_terms]
        seen: set[str] = set()
        unique: list[str] = []
        for query in queries:
            normalized = query.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique


def plan_query(question: str) -> QueryPlan:
    prompt = _build_prompt(question)
    result = run_agent_cli(prompt, purpose="query")
    if result.returncode != 0:
        detail = result.stderr or result.text or f"{result.provider} exited with code {result.returncode}"
        raise RuntimeError(f"query planner failed: {detail}")
    data = extract_json_object(result.text)
    usage = result.usage
    if data is None:
        raise ValueError("query planner did not return a JSON object")

    return QueryPlan(
        search_queries=_string_list(data.get("search_queries"))[:8],
        related_terms=_string_list(data.get("related_terms"))[:16],
        intent=str(data.get("intent", "")).strip(),
        usage=usage,
    )


def _build_prompt(question: str) -> str:
    return f"""あなたは日本語の規則文書検索クエリを作るアシスタントです。
ユーザー質問から、文書内に出てきそうな検索語・言い換え・関連語を生成してください。
回答本文は作らず、検索に使う語だけを返してください。

出力は必ずJSONのみです。
形式:
{{"search_queries":["検索フレーズ"],"related_terms":["関連語"],"intent":"質問意図の短い説明"}}

質問:
{question}
"""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
