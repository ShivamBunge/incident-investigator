"""Markdown-aware chunking for runbooks and postmortems.

Strategy (spec Section 5.4):
- preserve Markdown headings (each chunk carries its heading path)
- split oversized sections by paragraph
- target roughly 400-800 tokens
- no blind fixed-character chunking
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# Rough token estimate for English prose: ~4 characters per token.
CHARS_PER_TOKEN = 4
TARGET_MIN_TOKENS = 400
TARGET_MAX_TOKENS = 800


@dataclass
class Chunk:
    heading: str | None
    content: str


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; fenced code blocks stay intact."""
    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            current.append(line)
            continue
        if not in_fence and not line.strip():
            if current:
                paragraphs.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append("\n".join(current).strip())
    return [p for p in paragraphs if p]


def _iter_sections(markdown: str):
    """Yield (heading_path, body) for each markdown section.

    Content before the first heading is yielded with an empty heading path.
    """
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []

    for line in markdown.splitlines():
        match = HEADING_RE.match(line)
        if match:
            body = "\n".join(current_lines).strip()
            if body:
                yield [title for _, title in heading_stack], body
            current_lines = []
            level = len(match.group(1))
            title = match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
        else:
            current_lines.append(line)

    body = "\n".join(current_lines).strip()
    if body:
        yield [title for _, title in heading_stack], body


def chunk_markdown(markdown: str) -> list[Chunk]:
    """Chunk markdown into heading-preserving, paragraph-packed chunks."""
    chunks: list[Chunk] = []

    for heading_path, body in _iter_sections(markdown):
        heading = " > ".join(heading_path) if heading_path else None
        if estimate_tokens(body) <= TARGET_MAX_TOKENS:
            chunks.append(Chunk(heading=heading, content=body))
            continue

        # Oversized section: pack paragraphs into bounded chunks.
        pack: list[str] = []
        pack_tokens = 0
        for paragraph in _split_paragraphs(body):
            para_tokens = estimate_tokens(paragraph)
            if pack and pack_tokens + para_tokens > TARGET_MAX_TOKENS:
                chunks.append(Chunk(heading=heading, content="\n\n".join(pack)))
                pack, pack_tokens = [], 0
            pack.append(paragraph)
            pack_tokens += para_tokens
        if pack:
            chunks.append(Chunk(heading=heading, content="\n\n".join(pack)))

    return _merge_small_chunks(chunks)


def _merge_small_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Merge undersized chunks into the previous chunk when the heading matches."""
    merged: list[Chunk] = []
    for chunk in chunks:
        if (
            merged
            and merged[-1].heading == chunk.heading
            and estimate_tokens(merged[-1].content) < TARGET_MIN_TOKENS
            and estimate_tokens(merged[-1].content + "\n\n" + chunk.content) <= TARGET_MAX_TOKENS
        ):
            merged[-1] = Chunk(
                heading=merged[-1].heading,
                content=merged[-1].content + "\n\n" + chunk.content,
            )
            continue
        merged.append(chunk)
    return merged