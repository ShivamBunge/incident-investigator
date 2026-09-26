"""Local embedding wrapper (sentence-transformers), loaded once per process.

v1 uses sentence-transformers/all-MiniLM-L6-v2 (384-dim) — no API cost, offline.
The model choice is configuration, not code: swap via EMBEDDING_MODEL.
"""

from __future__ import annotations

import threading

from sentence_transformers import SentenceTransformer

from app.config import settings

_lock = threading.Lock()
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts; returns one vector per input text."""
    if not texts:
        return []
    model = get_model()
    vectors = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]