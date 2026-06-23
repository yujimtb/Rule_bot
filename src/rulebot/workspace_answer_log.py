from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Citation:
    url: str
    record_id: str
    source_type: str


@dataclass(frozen=True)
class AnswerLogEntry:
    answer_id: str
    question: str
    answer: str
    citations: list[Citation]
    used_queries: list[str]
    asker: str
    ts: str
    model: str
    usage: dict[str, int]
    confidence: str
    unknowns: list[str]
    prior_answer_ids: list[str] = field(default_factory=list)
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnswerLogEntry":
        return cls(
            answer_id=str(data["answer_id"]),
            question=str(data["question"]),
            answer=str(data["answer"]),
            citations=[Citation(**item) for item in data.get("citations", [])],
            used_queries=[str(item) for item in data.get("used_queries", [])],
            asker=str(data.get("asker", "")),
            ts=str(data.get("ts", "")),
            model=str(data.get("model", "")),
            usage={str(key): int(value) for key, value in data.get("usage", {}).items()},
            confidence=str(data.get("confidence", "")),
            unknowns=[str(item) for item in data.get("unknowns", [])],
            prior_answer_ids=[str(item) for item in data.get("prior_answer_ids", [])],
            snippet=str(data.get("snippet", "")),
        )


class JsonlAnswerLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, entry: AnswerLogEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def search(self, query: str, *, limit: int = 5) -> list[AnswerLogEntry]:
        terms = _query_terms(query)
        if not self.path.exists():
            return []
        entries: list[tuple[int, AnswerLogEntry]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = AnswerLogEntry.from_dict(json.loads(line))
            haystack = f"{entry.question}\n{entry.answer}\n{' '.join(entry.used_queries)}".casefold()
            score = sum(1 for term in terms if term in haystack) if terms else int(query.casefold() in haystack)
            if score > 0:
                entries.append((score, entry))
        entries.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in entries[:limit]]


def _query_terms(query: str) -> list[str]:
    terms = [term.casefold() for term in re.split(r"[\s、。,.!?！？のはをがにへとで]+", query) if term.strip()]
    if terms:
        return terms
    compact = query.casefold().strip()
    return [compact] if compact else []
