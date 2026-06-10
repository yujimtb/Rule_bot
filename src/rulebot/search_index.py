from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .document_store import DocumentChunk


INDEX_VERSION = 2
ASCII_WORD_RE = re.compile(r"[a-zA-Z0-9_]{2,}")
PUNCT_RE = re.compile(r"[\s　、。,.!?！？:：;；()\[\]{}<>「」『』【】#*_`~|/\\-]+")


@dataclass(frozen=True)
class IndexedChunk:
    source: str
    location: str
    text: str
    tokens: dict[str, int]
    length: int

    @classmethod
    def from_document_chunk(cls, chunk: DocumentChunk) -> "IndexedChunk":
        indexed_text = f"{chunk.source}\n{chunk.location}\n{chunk.text}"
        counts = Counter(_tokens(indexed_text))
        return cls(
            source=chunk.source,
            location=chunk.location,
            text=chunk.text,
            tokens=dict(counts),
            length=sum(counts.values()),
        )


@dataclass(frozen=True)
class IndexedSearchHit:
    chunk: IndexedChunk
    score: float


class SearchIndex:
    def __init__(self, chunks: list[IndexedChunk], document_frequency: dict[str, int] | None = None):
        self.chunks = chunks
        self.document_frequency = document_frequency or _document_frequency(chunks)
        self.average_length = _average_length(chunks)

    @classmethod
    def from_chunks(cls, chunks: list[DocumentChunk]) -> "SearchIndex":
        indexed_chunks = [IndexedChunk.from_document_chunk(chunk) for chunk in chunks]
        return cls(indexed_chunks)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchIndex":
        chunks = [
            IndexedChunk(
                source=str(item["source"]),
                location=str(item["location"]),
                text=str(item["text"]),
                tokens={str(key): int(value) for key, value in item["tokens"].items()},
                length=int(item["length"]),
            )
            for item in data.get("chunks", [])
        ]
        df = {str(key): int(value) for key, value in data.get("document_frequency", {}).items()}
        return cls(chunks=chunks, document_frequency=df)

    def to_dict(self, *, files: list[dict[str, object]]) -> dict[str, Any]:
        return {
            "version": INDEX_VERSION,
            "files": files,
            "document_frequency": self.document_frequency,
            "chunks": [
                {
                    "source": chunk.source,
                    "location": chunk.location,
                    "text": chunk.text,
                    "tokens": chunk.tokens,
                    "length": chunk.length,
                }
                for chunk in self.chunks
            ],
        }

    def search(self, queries: list[str], *, top_k: int) -> list[IndexedSearchHit]:
        query_tokens = _query_tokens(queries)
        if not query_tokens or not self.chunks:
            return []

        hits: list[IndexedSearchHit] = []
        for chunk in self.chunks:
            score = self._score_chunk(query_tokens, chunk)
            if score > 0:
                hits.append(IndexedSearchHit(chunk=chunk, score=score))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def _score_chunk(self, query_tokens: Counter[str], chunk: IndexedChunk) -> float:
        score = 0.0
        total_docs = max(len(self.chunks), 1)
        avg_len = self.average_length or 1.0
        k1 = 1.2
        b = 0.75

        for token, query_count in query_tokens.items():
            freq = chunk.tokens.get(token, 0)
            if not freq:
                continue

            df = self.document_frequency.get(token, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            denom = freq + k1 * (1 - b + b * chunk.length / avg_len)
            score += idf * (freq * (k1 + 1) / denom) * min(query_count, 3)

        normalized_queries = [PUNCT_RE.sub("", query.lower()) for query in query_tokens if len(query) >= 4]
        normalized_location = PUNCT_RE.sub("", f"{chunk.source}{chunk.location}".lower())
        for query in normalized_queries:
            if query and query in normalized_location:
                score += 2.0
        return score


def _document_frequency(chunks: list[IndexedChunk]) -> dict[str, int]:
    df: Counter[str] = Counter()
    for chunk in chunks:
        df.update(chunk.tokens.keys())
    return dict(df)


def _average_length(chunks: list[IndexedChunk]) -> float:
    if not chunks:
        return 0.0
    return sum(chunk.length for chunk in chunks) / len(chunks)


def _query_tokens(queries: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for query in queries:
        counts.update(_tokens(query))
    return counts


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = list(ASCII_WORD_RE.findall(lowered))
    compact = PUNCT_RE.sub("", lowered)

    for index in range(max(0, len(compact) - 1)):
        token = compact[index : index + 2]
        if token.strip():
            tokens.append(token)

    for index in range(max(0, len(compact) - 2)):
        token = compact[index : index + 3]
        if token.strip():
            tokens.append(token)
    return tokens
