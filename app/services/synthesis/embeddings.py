from __future__ import annotations

import os
import re
import logging
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

PRIMARY_MODEL: str = os.getenv("EMBEDDING_MODEL")
if not PRIMARY_MODEL:
    raise RuntimeError("EMBEDDING_MODEL is not set in .env")

FALLBACK_MODEL: str = os.getenv("EMBEDDING_FALLBACK_MODEL")
if not FALLBACK_MODEL:
    raise RuntimeError("EMBEDDING_FALLBACK_MODEL is not set in .env")

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip().lower()
    seen: set[str] = set()
    return " ".join(w for w in text.split() if not (w in seen or seen.add(w)))  # type: ignore[func-returns-value]


def _build_texts(papers: list[dict]) -> list[str]:

    texts: list[str] = []
    for paper in papers:
        lims = paper.get("normalized_limitations") or []
        fw = paper.get("normalized_future_work") or []

        # Join limitation and future-work
        lim_text = " ".join(_normalize(t) for t in lims if t)
        fw_text = " ".join(_normalize(t) for t in fw if t)
        combined = f"{lim_text} {fw_text}".strip()

        # Fallback
        if not combined:
            combined = _normalize(paper.get("title", "")) or "unknown research gap"

        texts.append(combined)
    return texts


_model_cache = {}

def get_model(model_name: str):
    from sentence_transformers import SentenceTransformer
    if model_name not in _model_cache:
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]

def generate_embeddings(papers: list[dict]) -> np.ndarray:

    texts = _build_texts(papers)
    if not texts:
        return np.empty((0, 1), dtype=np.float32)

    for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
        try:
            model = get_model(model_name)
            embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
            logger.info("Embeddings generated via SentenceTransformer (%s).", model_name)
            return embeddings.astype(np.float32)
        except Exception as exc:
            logger.warning("SentenceTransformer model '%s' failed: %s", model_name, exc)

    raise RuntimeError(
        f"Both embedding models failed ({PRIMARY_MODEL}, {FALLBACK_MODEL}). "
        "Ensure sentence-transformers is installed and at least one model is downloadable."
    )
