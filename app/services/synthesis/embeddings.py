from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import List

import numpy as np
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL", "all-mpnet-base-v2")

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip().lower()
    seen = set()
    return " ".join(w for w in text.split() if not (w in seen or seen.add(w)))

def _build_texts(papers: list[dict]) -> list[str]:
    texts: list[str] = []
    for paper in papers:
        parts = [
            _normalize(paper.get("title", "")),
            _normalize(paper.get("abstract", "") or ""),
            _normalize(paper.get("limitations", "") or ""),
            _normalize(paper.get("future_work", "") or ""),
        ]
        texts.append(" ".join(p for p in parts if p).strip() or "unknown")
    return texts


def _tfidf_fallback(texts: list[str]) -> np.ndarray:
    #Use sklearn TF-IDF + TruncatedSVD (LSA) as embedding fallback
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer

    n_components = min(64, len(texts) - 1) if len(texts) > 1 else 1
    tfidf = TfidfVectorizer(max_features=5000, stop_words="english")
    matrix = tfidf.fit_transform(texts)
    if n_components >= 1 and matrix.shape[1] > n_components:
        svd = TruncatedSVD(n_components=n_components, random_state=42)
        return svd.fit_transform(matrix)
    return matrix.toarray()


def generate_embeddings(papers: list[dict]) -> np.ndarray:

    texts = _build_texts(papers)
    if not texts:
        return np.empty((0, 1), dtype=np.float32)

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        logger.info("Embeddings generated via SentenceTransformer (%s).", EMBEDDING_MODEL_NAME)
        return embeddings.astype(np.float32)
    except Exception as exc:
        logger.warning("SentenceTransformer failed (%s); using TF-IDF fallback.", exc)
        return _tfidf_fallback(texts).astype(np.float32)
