from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .document_store import SUPPORTED_SUFFIXES, load_chunks
from .search_index import INDEX_VERSION, SearchIndex


INDEX_FILE_NAME = "search_index.json"
_LOCK = threading.Lock()


def get_search_index(docs_dir: str | Path, index_dir: str | Path) -> SearchIndex:
    docs_root = Path(docs_dir)
    index_root = Path(index_dir)

    with _LOCK:
        files = _fingerprint_docs(docs_root)
        cached = _load_if_current(index_root / INDEX_FILE_NAME, files)
        if cached is not None:
            return cached

        chunks = load_chunks(docs_root)
        index = SearchIndex.from_chunks(chunks)
        _save_index(index_root / INDEX_FILE_NAME, index.to_dict(files=files))
        return index


def _fingerprint_docs(docs_root: Path) -> list[dict[str, object]]:
    if not docs_root.exists():
        return []

    files: list[dict[str, object]] = []
    for path in sorted(docs_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        stat = path.stat()
        try:
            source = path.relative_to(docs_root).as_posix()
        except ValueError:
            source = path.name
        files.append({"source": source, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return files


def _load_if_current(index_path: Path, files: list[dict[str, object]]) -> SearchIndex | None:
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if int(data.get("version", -1)) != INDEX_VERSION:
        return None
    if data.get("files") != files:
        return None
    return SearchIndex.from_dict(data)


def _save_index(index_path: Path, data: dict[str, Any]) -> None:
    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=index_path.parent,
            delete=False,
            prefix=f".{index_path.name}.",
            suffix=".tmp",
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, index_path)
    except OSError:
        # The service can still answer with the in-memory index if the mounted
        # index directory is not writable.
        return
