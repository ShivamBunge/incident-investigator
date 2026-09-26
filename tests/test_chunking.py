"""Markdown-aware chunking tests (spec Section 5.4)."""

from app.rag.chunk import TARGET_MAX_TOKENS, chunk_markdown, estimate_tokens


def test_headings_preserved_as_paths():
    md = (
        "# Runbook\n\n"
        "Intro text.\n\n"
        "## Symptoms\n\n"
        "High error rate.\n\n"
        "## Mitigation\n\n"
        "Roll back."
    )
    chunks = chunk_markdown(md)
    headings = [c.heading for c in chunks]
    assert "Runbook > Symptoms" in headings
    assert "Runbook > Mitigation" in headings


def test_oversized_section_split_by_paragraph():
    paragraph = " ".join(["word"] * 500)  # ~500 estimated tokens
    md = f"# Guide\n\n## Details\n\n{paragraph}\n\n{paragraph}\n\n{paragraph}"
    chunks = chunk_markdown(md)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert estimate_tokens(chunk.content) <= TARGET_MAX_TOKENS


def test_code_fence_not_split_by_blank_lines():
    code = "```sql\nSELECT 1;\n\nSELECT 2;\n```"
    md = f"# Guide\n\n## Query\n\n{code}"
    chunks = chunk_markdown(md)
    assert any("SELECT 1" in c.content and "SELECT 2" in c.content for c in chunks)


def test_no_blind_fixed_character_chunking():
    """Sections under the max token budget stay intact as single chunks."""
    md = "# Guide\n\n## Short\n\nOnly a short paragraph here."
    chunks = chunk_markdown(md)
    assert len(chunks) == 1
    assert "short paragraph" in chunks[0].content
    assert chunks[0].heading == "Guide > Short"