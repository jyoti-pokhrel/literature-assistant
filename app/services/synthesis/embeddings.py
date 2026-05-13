from __future__ import annotations

import hashlib
import logging
import os
import re
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

_embedding_cache: dict[str, np.ndarray] = {}
_MAX_CACHE_SIZE = 50  # evict oldest when limit reached


def _paper_fingerprint(texts: list[str]) -> str:
    
    return hashlib.md5("|".join(texts).encode("utf-8", errors="replace")).hexdigest()


#Model registry
_model_cache: dict[str, object] = {}


def get_model(model_name: str):
    from sentence_transformers import SentenceTransformer
    if model_name not in _model_cache:
        logger.info("Loading SentenceTransformer model: %s", model_name)
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


def warm_up_model() -> None:
    #Pre-load the primary embedding model
    try:
        get_model(PRIMARY_MODEL)
        logger.info("Embedding model '%s' warmed up.", PRIMARY_MODEL)
    except Exception as exc:
        logger.warning("Embedding model warm-up failed: %s", exc)


#Text construction

def _normalize(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip().lower()
    seen: set[str] = set()
    return " ".join(w for w in text.split() if not (w in seen or seen.add(w)))  # type: ignore[func-returns-value]


def _build_texts(papers: list[dict]) -> list[str]:

    texts: list[str] = []
    for paper in papers:
        # Abstract: first 400 chars
        abstract = _normalize((paper.get("abstract") or "")[:400])
        title    = _normalize(paper.get("title", ""))
        lims     = " ".join(_normalize(t) for t in (paper.get("normalized_limitations") or [])[:5] if t)
        fw       = " ".join(_normalize(t) for t in (paper.get("normalized_future_work") or [])[:5] if t)
        methods_raw = (
            paper.get("normalized_method")           # key written by normalization.py
            or paper.get("normalized_methods")       # legacy alias (keep for compat)
            or ([paper.get("method")] if paper.get("method") else [])
        )
        methods = " ".join(_normalize(t) for t in methods_raw[:3] if t)

        # Build composite: abstract first so it dominates the embedding direction
        parts = [p for p in [abstract, title, methods, lims, fw] if p]
        combined = ". ".join(parts).strip(" .")
        texts.append(combined or "unknown research gap")
    return texts


#Public API

def generate_embeddings(papers: list[dict]) -> np.ndarray:
    if not papers:
        return np.empty((0, 1), dtype=np.float32)

    texts = _build_texts(papers)

    # Cache hit → skip expensive encoding
    key = _paper_fingerprint(texts)
    if key in _embedding_cache:
        logger.info("Embedding cache hit (%s papers).", len(papers))
        return _embedding_cache[key]

    # Cache miss → encode
    for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
        try:
            model = get_model(model_name)
            embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
            logger.info("Embeddings generated via SentenceTransformer (%s).", model_name)
            result = embeddings.astype(np.float32)

            # Store in cache; evict oldest entry if over limit
            if len(_embedding_cache) >= _MAX_CACHE_SIZE:
                oldest_key = next(iter(_embedding_cache))
                del _embedding_cache[oldest_key]
            _embedding_cache[key] = result
            return result

        except Exception as exc:
            logger.warning("SentenceTransformer model '%s' failed: %s", model_name, exc)

    raise RuntimeError(
        f"Both embedding models failed ({PRIMARY_MODEL}, {FALLBACK_MODEL}). "
        "Ensure sentence-transformers is installed and at least one model is downloadable."
    )
