from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .document_store import DocumentChunk


ASCII_WORD_RE = re.compile(r"[a-zA-Z0-9_]{2,}")
PUNCT_RE = re.compile(r"[\s　、。,.!?！？:：;；()\[\]{}<>「」『』【】#*_`~|/\\-]+")


@dataclass(frozen=True)
class SearchHit:
    chunk: DocumentChunk
    score: float


class Retriever:
    def __init__(self, chunks: list[DocumentChunk]):
        self._entries = [(chunk, _tokens(chunk.text)) for chunk in chunks]

    def search(self, query: str, top_k: int = 3) -> list[SearchHit]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []

        hits: list[SearchHit] = []
        for chunk, doc_tokens in self._entries:
            score = _score(query, query_tokens, chunk.text, doc_tokens)
            if score > 0:
                hits.append(SearchHit(chunk=chunk, score=score))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(ASCII_WORD_RE.findall(lowered))

    compact = PUNCT_RE.sub("", lowered)
    tokens.update(_char_ngrams(compact))
    return tokens


def _char_ngrams(compact: str) -> set[str]:
    tokens: set[str] = set()
    for index in range(max(0, len(compact) - 1)):
        token = compact[index : index + 2]
        if not token.strip():
            continue
        tokens.add(token)

    for index in range(max(0, len(compact) - 2)):
        token = compact[index : index + 3]
        if not token.strip():
            continue
        tokens.add(token)
    return tokens


def _score(query: str, query_tokens: set[str], text: str, doc_tokens: set[str]) -> float:
    if not doc_tokens:
        return 0.0

    overlap = query_tokens & doc_tokens
    if not overlap:
        return 0.0

    score = len(overlap) / math.sqrt(len(query_tokens) * len(doc_tokens))
    normalized_query = PUNCT_RE.sub("", query.lower())
    normalized_text = PUNCT_RE.sub("", text.lower())
    if normalized_query and normalized_query in normalized_text:
        score += 0.4
    return score
