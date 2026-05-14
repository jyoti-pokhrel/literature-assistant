"""One-shot script: embed any paper docs in `papers` that lack an embedding.

Usage:
    python -m scripts.backfill_paper_embeddings [--batch 64]

Run after the Atlas Vector Search index has been provisioned. Subsequent
candidate fetches embed lazily, so this script is only needed if there are
pre-existing rows from before the recommendation system shipped.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from app.db.session import papers_collection
from app.services.recommendations.embedder import (
    EMBED_BATCH,
    _fingerprint,
    _text_for_paper,
    embed_texts,
)
from app.services.synthesis.embeddings import PRIMARY_MODEL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def _backfill(batch_size: int) -> int:
    if papers_collection is None:
        raise SystemExit("papers_collection is None — check MONGODB_URL")

    cursor = papers_collection.find({"embedding": {"$exists": False}})
    pending: list[dict] = []
    processed = 0

    async def flush(batch: list[dict]) -> None:
        nonlocal processed
        if not batch:
            return
        texts = [_text_for_paper(p) for p in batch]
        vectors = await embed_texts(texts)
        now = datetime.now(timezone.utc)
        for paper, text, vector in zip(batch, texts, vectors):
            await papers_collection.update_one(
                {"_id": paper["_id"]},
                {
                    "$set": {
                        "embedding": vector,
                        "embedding_model": PRIMARY_MODEL,
                        "embedding_text_fingerprint": _fingerprint(text),
                        "embedded_at": now,
                        "last_seen_at": now,
                    }
                },
            )
        processed += len(batch)
        logger.info("Embedded %d papers so far", processed)

    async for doc in cursor:
        pending.append(doc)
        if len(pending) >= batch_size:
            await flush(pending)
            pending = []
    await flush(pending)

    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch",
        type=int,
        default=EMBED_BATCH,
        help=f"papers per embed batch (default: {EMBED_BATCH})",
    )
    args = parser.parse_args()

    total = asyncio.run(_backfill(args.batch))
    logger.info("Backfill complete. Embedded %d papers.", total)


if __name__ == "__main__":
    main()
