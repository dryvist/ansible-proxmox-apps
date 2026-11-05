"""Markdown corpus loader for the grounded Q&A fill workload.

Reads local files only. This module has no network access.
"""

import random
import re
import threading
from dataclasses import dataclass
from pathlib import Path

CHUNK_CHARS = 6000
_HEADING = re.compile(r"^#{1,6}\s")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str


def _sections(text):
    """Split at markdown headings; each section starts with its heading line."""
    section = []
    for line in text.splitlines(keepends=True):
        if _HEADING.match(line) and section:
            yield "".join(section)
            section = []
        section.append(line)
    if section:
        yield "".join(section)


def _units(text, limit):
    """Yield pieces of at most limit characters, keeping headings and paragraphs whole when possible."""
    for section in _sections(text):
        if len(section) <= limit:
            yield section
            continue
        buffer = ""
        for paragraph in section.split("\n\n"):
            paragraph += "\n\n"
            while len(paragraph) > limit:
                if buffer:
                    yield buffer
                    buffer = ""
                yield paragraph[:limit]
                paragraph = paragraph[limit:]
            if len(buffer) + len(paragraph) > limit:
                yield buffer
                buffer = ""
            buffer += paragraph
        if buffer:
            yield buffer


def chunk_text(text, limit=CHUNK_CHARS):
    """Pack heading-led units into chunks of at most limit characters."""
    chunks, buffer = [], ""
    for unit in _units(text, limit):
        if buffer and len(buffer) + len(unit) > limit:
            chunks.append(buffer)
            buffer = ""
        buffer += unit
    if buffer:
        chunks.append(buffer)
    return [chunk for chunk in chunks if chunk.strip()]


def load_chunks(corpus_dir, limit=CHUNK_CHARS):
    """Load every markdown file under corpus_dir in sorted order, skipping hidden paths such as .git."""
    root = Path(corpus_dir)
    chunks = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        # Symlinks are skipped so a cloned repository cannot expose files outside the corpus.
        if path.is_symlink() or not path.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for index, body in enumerate(chunk_text(text, limit)):
            chunks.append(Chunk(chunk_id=f"{relative.as_posix()}#{index}", text=body))
    return chunks


class ChunkPicker:
    """Hands out chunks round-robin, or at random from a seeded generator. Thread-safe."""

    def __init__(self, chunks, mode="round_robin", seed=None):
        if not chunks:
            raise ValueError("corpus has no markdown chunks")
        if mode not in {"round_robin", "random"}:
            raise ValueError(f"unknown chunk selection mode: {mode}")
        self._chunks = list(chunks)
        self._mode = mode
        self._random = random.Random(seed)
        self._next = 0
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            if self._mode == "random":
                return self._random.choice(self._chunks)
            chunk = self._chunks[self._next % len(self._chunks)]
            self._next += 1
            return chunk
