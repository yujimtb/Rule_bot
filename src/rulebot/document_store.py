from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_SUFFIXES = {".md", ".markdown", ".csv"}
MARKDOWN_HEADING_RE = re.compile(r"^(?:\d+\.\s*)?#+\s+(.+)$")


@dataclass(frozen=True)
class DocumentChunk:
    source: str
    location: str
    text: str


def load_chunks(docs_dir: str | Path) -> list[DocumentChunk]:
    root = Path(docs_dir)
    if not root.exists():
        return []

    chunks: list[DocumentChunk] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if path.suffix.lower() == ".csv":
            chunks.extend(_load_csv(path, root))
        else:
            chunks.extend(_load_markdown(path, root))
    return [chunk for chunk in chunks if chunk.text.strip()]


def _relative_source(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _load_markdown(path: Path, root: Path) -> list[DocumentChunk]:
    source = _relative_source(path, root)
    lines = path.read_text(encoding="utf-8").splitlines()
    chunks: list[DocumentChunk] = []
    title = "document"
    start_line = 1
    current: list[str] = []

    def flush() -> None:
        text = "\n".join(line for line in current).strip()
        if not text:
            return
        chunks.extend(_split_markdown_section(source, title, start_line, text))

    for line_no, line in enumerate(lines, start=1):
        heading = MARKDOWN_HEADING_RE.match(line)
        if heading:
            flush()
            title = heading.group(1).strip() or "heading"
            start_line = line_no
            current = [line]
        else:
            current.append(line)
    flush()
    return chunks


def _split_markdown_section(source: str, title: str, start_line: int, text: str) -> list[DocumentChunk]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    if len(text) <= 1200 or len(paragraphs) <= 1:
        return [DocumentChunk(source=source, location=f"{title} (line {start_line})", text=text)]

    chunks: list[DocumentChunk] = []
    buffer: list[str] = []
    for paragraph in paragraphs:
        candidate = "\n\n".join([*buffer, paragraph])
        if buffer and len(candidate) > 1200:
            chunks.append(
                DocumentChunk(
                    source=source,
                    location=f"{title} (line {start_line})",
                    text="\n\n".join(buffer),
                )
            )
            buffer = [paragraph]
        else:
            buffer.append(paragraph)
    if buffer:
        chunks.append(DocumentChunk(source=source, location=f"{title} (line {start_line})", text="\n\n".join(buffer)))
    return chunks


def _load_csv(path: Path, root: Path) -> list[DocumentChunk]:
    source = _relative_source(path, root)
    text = path.read_text(encoding="utf-8-sig")
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return []

    header = rows[0]
    has_header = len(header) > 1 and any(not cell.strip().isdigit() for cell in header)
    chunks: list[DocumentChunk] = []

    if has_header:
        for index, row in enumerate(rows[1:], start=2):
            pairs = []
            for key, value in zip(header, row):
                key = key.strip()
                value = value.strip()
                if key and value:
                    pairs.append(f"{key}: {value}")
            if pairs:
                chunks.append(DocumentChunk(source=source, location=f"row {index}", text="\n".join(pairs)))
        return chunks

    for index, row in enumerate(rows, start=1):
        values = [cell.strip() for cell in row if cell.strip()]
        if values:
            chunks.append(DocumentChunk(source=source, location=f"row {index}", text="\n".join(values)))
    return chunks
