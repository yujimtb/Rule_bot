from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from .index_store import get_search_index
from .agent_cli import classify_agent_error, extract_json_object, run_agent_cli, user_facing_agent_error
from .codex_app_server import CodexAppServerError, CodexUsageLimitError, answer_with_codex_app_server
from .query_planner import QueryPlan, plan_query
from .search_index import IndexedSearchHit
from .token_usage import TokenUsage, usage_from_dict

LOGGER = logging.getLogger("rulebot.codex_agent")


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    question = str(payload.get("question", "")).strip()
    docs_dir = Path(str(payload.get("docs_dir") or _required_env("DOCS_DIR")))
    index_dir = Path(str(payload.get("index_dir") or _required_env("INDEX_DIR")))

    if not question:
        _emit({"answer": "質問内容を読み取れませんでした。", "citations": [], "unknowns": ["質問が空です。"]})
        return

    if _required_env("AGENT_CLI_PROVIDER").lower() == "codex_app_server":
        _emit(_run_codex_app_server(question, docs_dir))
        return

    _emit(_answer_with_search_agent(question, docs_dir, index_dir))


def _answer_with_search_agent(question: str, docs_dir: Path, index_dir: Path) -> dict[str, Any]:
    search_index = get_search_index(docs_dir, index_dir)
    if not search_index.chunks:
        return {
            "answer": "現行ドキュメントでは確認できません。",
            "citations": [],
            "unknowns": ["回答用ドキュメントが読み込まれていません。"],
        }

    query_plan = plan_query(question)
    candidates = _search_candidates(question, query_plan, search_index)
    if not candidates:
        return {
            "answer": "現行ドキュメントでは確認できません。",
            "citations": [],
            "unknowns": ["質問に一致する根拠候補が見つかりませんでした。"],
            "usage": query_plan.usage.to_dict(),
        }

    prompt = _build_prompt(question, query_plan, candidates)
    data = _run_codex(prompt)
    usage = query_plan.usage + usage_from_dict(data.get("usage"))
    if data.get("error_type"):
        data["citations"] = []
    elif not data.get("citations"):
        data["citations"] = [_citation(hit) for hit in candidates[:3]]
    data.setdefault("unknowns", [])
    data["usage"] = usage.to_dict()
    return data


def compose_workspace_answer(question: str, snippets: list[str], citations: list[dict[str, str]]) -> dict[str, Any]:
    prompt = _build_workspace_compose_prompt(question, snippets, citations)
    data = _run_codex(prompt)
    if data.get("error_type"):
        return data
    answer = str(data.get("answer", "")).strip()
    if not answer:
        data["answer"] = "一次ソースで確認できる範囲では回答を特定できませんでした。"
    data.setdefault("unknowns", [])
    data.setdefault("confidence", "medium")
    return data


def _build_workspace_compose_prompt(question: str, snippets: list[str], citations: list[dict[str, str]]) -> str:
    evidence = "\n\n".join(
        f"[{index}] url={citation.get('url', '')} record_id={citation.get('record_id', '')} "
        f"source_type={citation.get('source_type', '')}\n{_trim(snippet, limit=1200)}"
        for index, (snippet, citation) in enumerate(zip(snippets, citations, strict=False), start=1)
        if snippet.strip()
    )
    return f"""あなたはワークスペース検索 Bot の回答合成器です。
検証済み一次ソース snippets だけを根拠に、日本語で簡潔に回答してください。
過去の Bot 回答や外部知識は根拠にしないでください。
根拠 snippets にない内容は unknowns に入れてください。

出力は必ず JSON のみです。形式:
{{"answer":"回答本文","unknowns":["不明点"],"confidence":"high|medium|low"}}

質問:
{question}

検証済み一次ソース snippets:
{evidence or "なし"}
"""


def _run_codex_app_server(question: str, docs_dir: Path) -> dict[str, Any]:
    try:
        result = answer_with_codex_app_server(question, docs_dir)
    except CodexUsageLimitError as exc:
        LOGGER.warning("codex app-server usage limit: %s", exc)
        return {
            "answer": "回答サービスの利用上限に達したため、現在は回答できません。",
            "citations": [],
            "unknowns": [user_facing_agent_error("usage_limit")],
            "usage": TokenUsage().to_dict(),
            "usage_chargeable": False,
            "error_type": "usage_limit",
        }
    except CodexAppServerError as exc:
        error_type = classify_agent_error(str(exc))
        LOGGER.warning("codex app-server failed type=%s error=%s", error_type, exc)
        return _agent_error_response(error_type)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("unexpected codex app-server failure")
        return _agent_error_response(classify_agent_error(str(exc)))

    if result.returncode != 0:
        detail = result.stderr or result.text or f"{result.provider} exited with code {result.returncode}"
        error_type = classify_agent_error(detail)
        LOGGER.warning("codex app-server answer failed type=%s provider=%s code=%s detail=%s", error_type, result.provider, result.returncode, detail)
        return _agent_error_response(error_type, usage=result.usage)

    data = extract_json_object(result.text)
    if data is None:
        return {
            "answer": result.text or "現行ドキュメントでは確認できません。",
            "citations": [],
            "unknowns": [],
            "usage": result.usage.to_dict(),
            "usage_chargeable": result.usage_chargeable,
        }
    data.setdefault("citations", [])
    data.setdefault("unknowns", [])
    data["usage"] = result.usage.to_dict()
    data["usage_chargeable"] = result.usage_chargeable
    return data


def _search_candidates(question: str, query_plan: QueryPlan, search_index: Any) -> list[IndexedSearchHit]:
    candidate_top_k = int(_required_env("RETRIEVAL_CANDIDATE_TOP_K"))
    context_top_k = int(_required_env("ANSWER_CONTEXT_TOP_K"))
    hits = search_index.search(query_plan.all_queries(question), top_k=candidate_top_k)
    return hits[:context_top_k]


def _build_prompt(question: str, query_plan: QueryPlan, candidates: list[IndexedSearchHit]) -> str:
    context = "\n\n".join(_candidate_block(index, hit) for index, hit in enumerate(candidates, start=1))
    search_terms = ", ".join(query_plan.all_queries(question))
    return f"""あなたはSHIMOKITA COLLEGEの館内規則・生活ルール回答Botです。
以下の根拠候補だけを根拠にしてください。
日本語で簡潔に回答してください。
根拠資料にない内容は推測せず、不明な点に書いてください。

回答手順:
1. 根拠候補を比較し、質問に最も直接関係する候補だけを使ってください。
2. 質問文の単語に完全一致する箇所がなくても、意味が近い語、言い換え、カタカナ/漢字/英字の表記揺れを自分で判断してください。
3. 複数候補に矛盾や不足がある場合は、不明な点に書いてください。
4. 外部知識や推測で補わないでください。

出力は必ずJSONのみです。Markdownや説明文をJSONの外に出さないでください。
形式:
{{"answer":"回答本文","citations":["根拠1"],"unknowns":["不明点"]}}

質問:
{question}

検索意図:
{query_plan.intent or "未特定"}

検索語:
{search_terms}

根拠候補:
{context}
"""


def _candidate_block(index: int, hit: IndexedSearchHit) -> str:
    return f"""[{index}] {_citation(hit)} score={hit.score:.4f}
{_trim(hit.chunk.text)}"""


def _citation(hit: IndexedSearchHit) -> str:
    return f"{hit.chunk.source}: {hit.chunk.location}"


def _trim(text: str, limit: int = 1800) -> str:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def _run_codex(prompt: str) -> dict[str, Any]:
    result = run_agent_cli(prompt, purpose="answer")
    if result.timed_out:
        return {
            "answer": "回答生成に時間がかかりすぎたため中断しました。",
            "citations": [],
            "unknowns": [user_facing_agent_error("timeout")],
            "usage": TokenUsage().to_dict(),
            "error_type": "timeout",
        }
    if result.returncode != 0:
        detail = result.stderr or result.text or f"{result.provider} exited with code {result.returncode}"
        error_type = classify_agent_error(detail)
        LOGGER.warning("agent cli answer failed type=%s provider=%s code=%s detail=%s", error_type, result.provider, result.returncode, detail)
        return _agent_error_response(error_type, usage=result.usage)

    data = extract_json_object(result.text)
    if data is None:
        return {
            "answer": result.text.splitlines()[0] if result.text else "回答生成に失敗しました。",
            "citations": [],
            "unknowns": [],
            "usage": result.usage.to_dict(),
        }
    data["usage"] = result.usage.to_dict()
    return data


def _agent_error_response(error_type: str, *, usage: TokenUsage | None = None) -> dict[str, Any]:
    return {
        "answer": "回答生成に失敗しました。",
        "citations": [],
        "unknowns": [user_facing_agent_error(error_type)],
        "usage": (usage or TokenUsage()).to_dict(),
        "usage_chargeable": False,
        "error_type": error_type,
    }


def _emit(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False))


def _required_env(name: str) -> str:
    value = os.environ[name].strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


if __name__ == "__main__":
    main()
