"""Compute and persist SentenceTransformer embeddings for paper documents.

Thin wrapper around `app.services.synthesis.embeddings.generate_embeddings`
that batches encodes, upserts vectors into the `papers` collection, and
records the model name + fingerprint used. Runs in a thread so the embedding
model doesn't block the asyncio loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Iterable

from pymongo import UpdateOne

from app.db.session import papers_collection
from app.services.synthesis.embeddings import (
    PRIMARY_MODEL,
    generate_embeddings,
    get_model,
)

logger = logging.getLogger(__name__)

EMBED_BATCH = 32


def _text_for_paper(paper: dict) -> str:
    title = (paper.get("title") or "").strip()
    abstract = (paper.get("abstract") or "").strip()[:400]
    if title and abstract:
        return f"{title}. {abstract}"
    return title or abstract or "untitled paper"


def _fingerprint(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def get_embedding_dim() -> int:
    """Returns the active model's embedding dimension (cached after first call)."""
    model = get_model(PRIMARY_MODEL)
    return int(model.get_sentence_embedding_dimension())


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Async-friendly wrapper around generate_embeddings.

    Treats each string as its own pseudo-paper so we can reuse the existing
    embedding plumbing. Runs in a worker thread to keep the event loop free.
    """
    if not texts:
        return []
    pseudo_papers = [{"title": "", "abstract": text} for text in texts]
    loop = asyncio.get_running_loop()
    vectors = await loop.run_in_executor(None, generate_embeddings, pseudo_papers)
    return [vec.tolist() for vec in vectors]


async def ensure_paper_embeddings(papers: Iterable[dict]) -> list[dict]:
    """Embed any paper docs that are missing embeddings and upsert into Mongo.

    Each paper is matched on (source, external_id). Returns the input list with
    `embedding`, `embedding_model`, and `embedded_at` fields populated.
    """
    if papers_collection is None:
        return list(papers)

    paper_list = list(papers)
    if not paper_list:
        return paper_list

    to_embed: list[int] = []
    fingerprints: list[str] = []
    texts: list[str] = []
    for idx, paper in enumerate(paper_list):
        existing = paper.get("embedding")
        if isinstance(existing, list) and existing:
            continue
        text = _text_for_paper(paper)
        to_embed.append(idx)
        fingerprints.append(_fingerprint(text))
        texts.append(text)

    if not to_embed:
        return paper_list

    vectors: list[list[float]] = []
    for batch_start in range(0, len(texts), EMBED_BATCH):
        batch = texts[batch_start : batch_start + EMBED_BATCH]
        batch_vectors = await embed_texts(batch)
        vectors.extend(batch_vectors)

    now = datetime.now(timezone.utc)
    operations: list[UpdateOne] = []
    for offset, idx in enumerate(to_embed):
        paper = paper_list[idx]
        vector = vectors[offset]
        paper["embedding"] = vector
        paper["embedding_model"] = PRIMARY_MODEL
        paper["embedding_text_fingerprint"] = fingerprints[offset]
        paper["embedded_at"] = now

        source = paper.get("source")
        external_id = paper.get("external_id")
        if not source or not external_id:
            continue
        operations.append(
            UpdateOne(
                {"source": source, "external_id": external_id},
                {
                    "$set": {
                        "source": source,
                        "external_id": external_id,
                        "title": paper.get("title"),
                        "abstract": paper.get("abstract"),
                        "authors": paper.get("authors") or [],
                        "year": paper.get("year"),
                        "venue": paper.get("venue"),
                        "url": paper.get("url"),
                        "pdf_url": paper.get("pdf_url"),
                        "citation_count": paper.get("citation_count"),
                        "doi": paper.get("doi"),
                        "embedding": vector,
                        "embedding_model": PRIMARY_MODEL,
                        "embedding_text_fingerprint": fingerprints[offset],
                        "embedded_at": now,
                        "last_seen_at": now,
                    },
                    "$setOnInsert": {"first_seen_at": now},
                },
                upsert=True,
            )
        )

    if operations:
        try:
            await papers_collection.bulk_write(operations, ordered=False)
        except Exception:
            logger.exception("Bulk upsert of paper embeddings failed")

    return paper_list
