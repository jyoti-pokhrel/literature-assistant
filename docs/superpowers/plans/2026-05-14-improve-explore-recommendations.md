# Improve Explore Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/explore` feed reliably return ranked, personalized papers — even before Atlas Vector Search indexes new candidates — and lift recommendation quality with multi-component retrieval, author/venue affinity, time-decayed seen-list, and cursor pagination.

**Architecture:** Today the pipeline averages all profile components into one centroid and issues a single Atlas `$vectorSearch`. When the index pool is thin, it tries to fetch fresh candidates but those are not yet searchable (Atlas index updates asynchronously), so the user sees an empty feed. We will: (a) keep Atlas `$vectorSearch` as the primary retrieval over the established pool, (b) add an in-memory cosine ranker that scores freshly-fetched candidates the same request, (c) replace the single centroid with **multi-query retrieval** — one `$vectorSearch` per top profile component, results interleaved by component weight, (d) add author/venue affinity boosts derived from `search_history` and `library_items`, (e) introduce time-decayed `seen_paper_ids` so old impressions can resurface after 21 days, (f) implement true offset pagination, and (g) ship a diagnostic endpoint + a few unit tests for the pure-Python scoring code.

**Tech Stack:** FastAPI (async) + Motor (Mongo) + Pydantic + Atlas Vector Search; SentenceTransformer (`all-MiniLM-L6-v2`, 384-dim); pytest + pytest-asyncio for the new unit tests.

---

## Investigation Notes (read first)

These are the concrete failure modes observed in the current implementation. Reference them when reviewing each task.

1. `app/services/recommendations/pipeline.py:142-157` — when the vector pool is thin, the code calls `fetch_for_topics()` then immediately re-runs `rank_for_profile` (which only sees papers via Atlas `$vectorSearch`). Atlas indexes asynchronously; freshly upserted papers are not yet visible, so the second rank usually returns the same empty set. **Result: empty feed on first load when the corpus is small.**
2. `app/services/recommendations/pipeline.py:110-118` — `cursor` parameter is accepted but never threaded into `rank_for_profile`; pagination relies entirely on the `seen_paper_ids` ring buffer. After `MIN_POOL_FOR_PAGE` exhausts impressions, `next_cursor` advances but the ranker keeps returning the same top-N minus seen — leading to short, redundant pages.
3. `app/services/recommendations/profile_builder.py:152-167` — the profile is a single weighted centroid over all positive component vectors. When seeds are orthogonal (e.g. "GNNs", "compiler optimization", "cancer biology"), the centroid lies between clusters and matches none well.
4. `app/services/recommendations/ranker.py:204` — composite score uses `vector_score` directly. Atlas's vectorSearchScore is in `[0, 1]` for cosine, but its distribution skews high; recency/citation weights barely move the ranking. Worse, when `embedding` is missing from a candidate the MMR diversity term silently degrades to zero (line 168 `_cosine` returns 0).
5. `app/services/recommendations/profile_builder.py:326-345` — `seen_paper_ids` grows unbounded up to 500 with no time decay, so once a user has scrolled deep they cannot re-encounter papers they skimmed past months ago.
6. No diagnostic surface — there is no way for the operator (or the frontend) to learn *why* the feed is empty (no embedded papers? index missing? cold start? profile vector null?).

## File Structure

We will modify the recommendations service and add two new files. Each file's responsibility:

- **`app/services/recommendations/ranker.py`** *(modify)* — Atlas `$vectorSearch` retrieval and ranking. Split into: vector-search helper, in-memory cosine helper, scoring, MMR. New: accept multiple query vectors and merge.
- **`app/services/recommendations/pipeline.py`** *(modify)* — orchestrator. New: collect ranked-from-Atlas + ranked-in-memory (freshly fetched), merge, paginate via offset.
- **`app/services/recommendations/profile_builder.py`** *(modify)* — add affinity collection (top venues + top authors from search_history / library) and per-component vector materialization so the pipeline doesn't have to re-embed.
- **`app/services/recommendations/affinity.py`** *(new)* — author/venue affinity computation, isolated so it is unit-testable.
- **`app/services/recommendations/scoring.py`** *(new)* — pure scoring helpers (recency, citation, normalization, affinity boost, interleave). Moved out of `ranker.py` so the module has one responsibility and the helpers are easily testable without Mongo.
- **`app/api/routes/explore.py`** *(modify)* — add `GET /explore/diagnostics` (admin-only or always-on for dev) summarizing pool health.
- **`tests/recommendations/test_scoring.py`** *(new)* — pytest unit tests for scoring + interleave + affinity.
- **`tests/recommendations/test_ranker_inmemory.py`** *(new)* — pytest tests for the in-memory rank path (no Mongo).
- **`pyproject.toml`** *(modify)* — add pytest, pytest-asyncio as dev dependencies.

---

## Task 1: Add pytest scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/recommendations/__init__.py`
- Create: `tests/recommendations/conftest.py`

- [ ] **Step 1: Add dev dependencies to pyproject.toml**

Find the `[project]` table and append a `[dependency-groups]` block at the end of the file:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Install the dev dependency**

Run: `uv sync --group dev` (or `pip install pytest pytest-asyncio` if not using uv)
Expected: pytest binary in `.venv/bin/pytest`.

- [ ] **Step 3: Create the test package files**

Write `tests/__init__.py` and `tests/recommendations/__init__.py` as empty files.

Write `tests/recommendations/conftest.py`:

```python
"""Shared fixtures for recommendations tests.

The recommendations service has both pure-Python logic (scoring, interleave,
affinity) and Mongo-bound logic (vector search, persistence). Tests in this
package focus on the pure-Python side; Mongo is monkeypatched to None.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_mongo(monkeypatch):
    """Default-deny Mongo access in unit tests; opt-in per test."""
    import app.db.session as session
    monkeypatch.setattr(session, "papers_collection", None)
    monkeypatch.setattr(session, "user_profiles_collection", None)
    monkeypatch.setattr(session, "search_history_collection", None)
    monkeypatch.setattr(session, "gap_feedback_signals_collection", None)
```

- [ ] **Step 4: Verify pytest discovers nothing yet but exits 0**

Run: `pytest tests/ -q`
Expected: `no tests ran in 0.0Xs` (exit 0).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/recommendations/__init__.py tests/recommendations/conftest.py
git commit -m "test: add pytest scaffolding for recommendations module"
```

---

## Task 2: Extract scoring helpers + unit tests

Move pure scoring functions out of `ranker.py` into a new `scoring.py` and lock their behavior with tests. This gives us a stable target before we change ranker semantics.

**Files:**
- Create: `app/services/recommendations/scoring.py`
- Modify: `app/services/recommendations/ranker.py:30-58` (delete moved helpers and import them)
- Create: `tests/recommendations/test_scoring.py`

- [ ] **Step 1: Write the failing test for scoring helpers**

Create `tests/recommendations/test_scoring.py`:

```python
from datetime import datetime, timezone

from app.services.recommendations import scoring


def test_recency_score_within_window():
    current_year = datetime.now(timezone.utc).year
    assert scoring.recency_score(current_year) == 1.0
    assert scoring.recency_score(2020) == 0.0
    assert 0 < scoring.recency_score(2022) < 1


def test_recency_score_handles_invalid():
    assert scoring.recency_score(None) == 0.0
    assert scoring.recency_score("not-a-year") == 0.0


def test_citation_score_monotonic():
    assert scoring.citation_score(0) == 0.0
    assert scoring.citation_score(10) < scoring.citation_score(1000)
    assert scoring.citation_score(10**8) == 1.0  # clamped


def test_cosine_normalized():
    assert scoring.cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert scoring.cosine([1, 0, 0], [0, 1, 0]) == 0.0
    assert scoring.cosine([0, 0, 0], [1, 0, 0]) == 0.0  # zero-vector guard


def test_composite_score_weights():
    s = scoring.composite_score(
        vector_score=1.0, recency=1.0, citations=1.0, affinity=0.0
    )
    # 0.65*1 + 0.15*1 + 0.10*1 + 0.10*0 = 0.90
    assert abs(s - 0.90) < 1e-6


def test_composite_score_affinity_adds():
    no_aff = scoring.composite_score(0.5, 0.5, 0.5, affinity=0.0)
    with_aff = scoring.composite_score(0.5, 0.5, 0.5, affinity=1.0)
    assert with_aff > no_aff
```

- [ ] **Step 2: Run the test to confirm it fails (module missing)**

Run: `pytest tests/recommendations/test_scoring.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.recommendations.scoring'`

- [ ] **Step 3: Implement `scoring.py`**

Create `app/services/recommendations/scoring.py`:

```python
"""Pure scoring helpers for the recommendation ranker.

Lives outside `ranker.py` so the functions can be unit-tested without
touching Mongo. All inputs are plain numbers/vectors; no I/O.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Sequence

import numpy as np

RECENCY_FLOOR_YEAR = 2020
VECTOR_WEIGHT = 0.65
RECENCY_WEIGHT = 0.15
CITATION_WEIGHT = 0.10
AFFINITY_WEIGHT = 0.10


def recency_score(year: Any) -> float:
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        return 0.0
    current_year = _dt.datetime.now(_dt.timezone.utc).year
    denom = max(1, current_year - RECENCY_FLOOR_YEAR)
    return max(0.0, min(1.0, (year_int - RECENCY_FLOOR_YEAR) / denom))


def citation_score(citation_count: Any) -> float:
    try:
        count = max(0, int(citation_count or 0))
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, math.log10(1 + count) / 4.0)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    av = np.asarray(a, dtype=np.float32)
    bv = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom < 1e-9:
        return 0.0
    return float(np.dot(av, bv) / denom)


def composite_score(
    vector_score: float,
    recency: float,
    citations: float,
    affinity: float,
) -> float:
    return (
        VECTOR_WEIGHT * vector_score
        + RECENCY_WEIGHT * recency
        + CITATION_WEIGHT * citations
        + AFFINITY_WEIGHT * affinity
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/recommendations/test_scoring.py -q`
Expected: 6 passed.

- [ ] **Step 5: Wire `ranker.py` to use the new module**

In `app/services/recommendations/ranker.py`, replace the in-file helpers with imports.

Find and delete (lines 13-58 in current file):

```python
import datetime as _dt
import logging
import math
from typing import Any

import numpy as np

from app.db.session import papers_collection

logger = logging.getLogger(__name__)

VECTOR_INDEX_NAME = "papers_vector_index"
NUM_CANDIDATES = 200
VECTOR_LIMIT = 120
MMR_LAMBDA = 0.7
RECENCY_FLOOR_YEAR = 2020
VECTOR_WEIGHT = 0.70
RECENCY_WEIGHT = 0.20
CITATION_WEIGHT = 0.10


def _recency_score(year: Any) -> float:
    ...

def _citation_score(citation_count: Any) -> float:
    ...

def _cosine(a, b) -> float:
    ...
```

Replace with:

```python
import datetime as _dt
import logging
import math
from typing import Any

from app.db.session import papers_collection
from app.services.recommendations.scoring import (
    citation_score,
    composite_score,
    cosine,
    recency_score,
)

logger = logging.getLogger(__name__)

VECTOR_INDEX_NAME = "papers_vector_index"
NUM_CANDIDATES = 200
VECTOR_LIMIT = 120
MMR_LAMBDA = 0.7
```

Then update every call site in `ranker.py`:
- `_recency_score(...)` → `recency_score(...)`
- `_citation_score(...)` → `citation_score(...)`
- `_cosine(...)` → `cosine(...)`
- The composite at lines 203-207 becomes: `final = composite_score(vector_score, recency, citations, affinity=0.0)` (affinity wired in Task 5).

- [ ] **Step 6: Run app smoke test to verify ranker still imports**

Run: `python -c "from app.services.recommendations.ranker import rank_for_profile; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add app/services/recommendations/scoring.py app/services/recommendations/ranker.py tests/recommendations/test_scoring.py
git commit -m "refactor(recs): extract pure scoring helpers into scoring.py with tests"
```

---

## Task 3: Add `interleave_by_weight` helper

When we move to multi-query retrieval, we need to merge per-component ranked lists into one feed while respecting component weights.

**Files:**
- Modify: `app/services/recommendations/scoring.py` (append at the end)
- Modify: `tests/recommendations/test_scoring.py` (append at the end)

- [ ] **Step 1: Write the failing test**

Append to `tests/recommendations/test_scoring.py`:

```python
def test_interleave_balanced_by_weight():
    a = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}, {"id": "a4"}]
    b = [{"id": "b1"}, {"id": "b2"}]
    result = scoring.interleave_by_weight(
        lists=[a, b], weights=[2.0, 1.0], limit=6, key=lambda d: d["id"]
    )
    ids = [d["id"] for d in result]
    # heavier list contributes ~2/3, lighter ~1/3 — with limit 6, expect 4 a's, 2 b's
    assert ids.count("a1") + ids.count("a2") + ids.count("a3") + ids.count("a4") == 4
    assert ids.count("b1") + ids.count("b2") == 2
    # no duplicates
    assert len(set(ids)) == 6


def test_interleave_dedups_across_lists():
    a = [{"id": "x"}, {"id": "a2"}]
    b = [{"id": "x"}, {"id": "b2"}]
    result = scoring.interleave_by_weight(
        lists=[a, b], weights=[1.0, 1.0], limit=4, key=lambda d: d["id"]
    )
    ids = [d["id"] for d in result]
    assert ids.count("x") == 1
    assert set(ids) == {"x", "a2", "b2"}


def test_interleave_respects_limit():
    a = [{"id": f"a{i}"} for i in range(10)]
    result = scoring.interleave_by_weight(
        lists=[a], weights=[1.0], limit=3, key=lambda d: d["id"]
    )
    assert len(result) == 3
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/recommendations/test_scoring.py -q`
Expected: 3 failures for `interleave_by_weight` missing.

- [ ] **Step 3: Implement `interleave_by_weight`**

Append to `app/services/recommendations/scoring.py`:

```python
def interleave_by_weight(
    lists: list[list[dict]],
    weights: list[float],
    limit: int,
    key,
) -> list[dict]:
    """Round-robin pick items from ranked lists in proportion to weights.

    Each list is consumed front-to-back. The next list picked is the one with
    the highest `weight / (1 + picks_so_far)` value (deficit round-robin).
    `key` is a callable returning a hashable id for dedup across lists.
    """
    if not lists or limit <= 0:
        return []
    cursors = [0] * len(lists)
    picks = [0] * len(lists)
    seen: set = set()
    out: list[dict] = []

    while len(out) < limit:
        # pick the list with highest weight/(1+picks) that still has items
        best_idx = -1
        best_priority = -math.inf
        for i, lst in enumerate(lists):
            if cursors[i] >= len(lst):
                continue
            priority = weights[i] / (1.0 + picks[i])
            if priority > best_priority:
                best_priority = priority
                best_idx = i
        if best_idx == -1:
            break  # all lists exhausted
        # advance cursor on the chosen list until we find a fresh item
        while cursors[best_idx] < len(lists[best_idx]):
            candidate = lists[best_idx][cursors[best_idx]]
            cursors[best_idx] += 1
            cid = key(candidate)
            if cid in seen:
                continue
            seen.add(cid)
            out.append(candidate)
            picks[best_idx] += 1
            break
    return out
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/recommendations/test_scoring.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/recommendations/scoring.py tests/recommendations/test_scoring.py
git commit -m "feat(recs): add interleave_by_weight for multi-component merging"
```

---

## Task 4: In-memory ranker for freshly-fetched candidates

Atlas Vector Search indexes asynchronously, so candidates added via `fetch_for_topics` won't appear in a same-request `$vectorSearch`. Add a pure-Python cosine ranker that works on candidates we already hold in memory after `ensure_paper_embeddings`.

**Files:**
- Modify: `app/services/recommendations/ranker.py` (append new function)
- Create: `tests/recommendations/test_ranker_inmemory.py`

- [ ] **Step 1: Write the failing test**

Create `tests/recommendations/test_ranker_inmemory.py`:

```python
import math

import numpy as np
import pytest

from app.services.recommendations.ranker import rank_in_memory


def _unit(v):
    arr = np.array(v, dtype=np.float32)
    return (arr / np.linalg.norm(arr)).tolist()


def _paper(pid: str, embedding, year=2024, citations=10, **rest):
    return {
        "source": "arxiv",
        "external_id": pid,
        "title": pid,
        "embedding": embedding,
        "year": year,
        "citation_count": citations,
        **rest,
    }


@pytest.mark.asyncio
async def test_rank_in_memory_orders_by_similarity():
    query = _unit([1, 0, 0])
    candidates = [
        _paper("near", _unit([0.95, 0.05, 0])),
        _paper("far", _unit([0, 1, 0])),
        _paper("mid", _unit([0.7, 0.7, 0])),
    ]
    ranked = await rank_in_memory(
        query_vectors=[query],
        weights=[1.0],
        candidates=candidates,
        seen_ids=set(),
        page_size=3,
    )
    ids = [p["external_id"] for p in ranked]
    assert ids == ["near", "mid", "far"]


@pytest.mark.asyncio
async def test_rank_in_memory_filters_seen():
    query = _unit([1, 0, 0])
    candidates = [
        _paper("a", _unit([0.9, 0, 0])),
        _paper("b", _unit([0.8, 0, 0])),
    ]
    ranked = await rank_in_memory(
        query_vectors=[query],
        weights=[1.0],
        candidates=candidates,
        seen_ids={"a"},
        page_size=5,
    )
    assert [p["external_id"] for p in ranked] == ["b"]


@pytest.mark.asyncio
async def test_rank_in_memory_skips_missing_embeddings():
    query = _unit([1, 0, 0])
    candidates = [
        _paper("with_emb", _unit([0.9, 0, 0])),
        {"source": "arxiv", "external_id": "no_emb", "title": "x"},  # no embedding
    ]
    ranked = await rank_in_memory(
        query_vectors=[query],
        weights=[1.0],
        candidates=candidates,
        seen_ids=set(),
        page_size=5,
    )
    assert [p["external_id"] for p in ranked] == ["with_emb"]
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/recommendations/test_ranker_inmemory.py -q`
Expected: ImportError for `rank_in_memory`.

- [ ] **Step 3: Implement `rank_in_memory`**

Append to `app/services/recommendations/ranker.py`:

```python
async def rank_in_memory(
    query_vectors: list[list[float]],
    weights: list[float],
    candidates: list[dict],
    seen_ids: set[str],
    page_size: int,
) -> list[dict]:
    """Cosine-rank candidates that already have an `embedding` in memory.

    Used when Atlas Vector Search has not yet indexed freshly-fetched papers,
    or when we want to score a small pool without an extra Atlas round-trip.
    `query_vectors` are typically the per-component profile vectors; weights
    line up positionally. The best similarity across queries is used as the
    `vector_score` to keep behavior consistent with multi-query retrieval.
    """
    if not query_vectors or not candidates or page_size <= 0:
        return []

    scored: list[dict] = []
    for paper in candidates:
        external_id = paper.get("external_id")
        if not external_id or external_id in seen_ids:
            continue
        embedding = paper.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            continue
        best_sim = 0.0
        for q, w in zip(query_vectors, weights):
            if w <= 0:
                continue
            sim = cosine(embedding, q)
            if sim > best_sim:
                best_sim = sim
        recency = recency_score(paper.get("year"))
        citations = citation_score(paper.get("citation_count"))
        final = composite_score(best_sim, recency, citations, affinity=0.0)
        out = dict(paper)
        out["vector_score"] = best_sim
        out["_final_score"] = final
        scored.append(out)

    scored.sort(key=lambda d: d["_final_score"], reverse=True)
    return scored[:page_size]
```

(Import `composite_score` at the top of `ranker.py` — already done in Task 2 Step 5.)

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/recommendations/test_ranker_inmemory.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/recommendations/ranker.py tests/recommendations/test_ranker_inmemory.py
git commit -m "feat(recs): add rank_in_memory for candidates not yet in Atlas index"
```

---

## Task 5: Multi-query retrieval + interleave in `ranker.rank_for_profile`

Today `rank_for_profile` averages all positive components into one centroid. Replace with: per-top-component vector search, interleave results by component weight, then composite-score the union.

**Files:**
- Modify: `app/services/recommendations/ranker.py` — change `rank_for_profile` signature and body.

- [ ] **Step 1: Read the existing `rank_for_profile` to confirm signature**

Read `app/services/recommendations/ranker.py:182-222`. Confirm the function currently takes `profile_vector`, `profile_components`, `seen_paper_ids`, `page_size`, `embed_lookup`.

- [ ] **Step 2: Replace the function**

In `app/services/recommendations/ranker.py`, replace `rank_for_profile` (lines ~182-222) with:

```python
TOP_COMPONENTS_FOR_RETRIEVAL = 5


async def rank_for_profile(
    profile_vector: list[float],
    profile_components: list[dict],
    seen_paper_ids: list[str],
    page_size: int,
    embed_lookup,
) -> list[dict]:
    """Return up to `page_size` ranked candidate papers.

    Issues one `$vectorSearch` per top profile component (plus the centroid
    as a fallback), interleaves the per-component lists by weight, then
    composite-scores the union and applies MMR for diversity.
    """
    seen = set(seen_paper_ids or [])

    hydrated = _hydrate_components(profile_components, embed_lookup)
    positives = [c for c in hydrated if c.get("weight", 0) > 0]
    positives.sort(key=lambda c: c["weight"], reverse=True)

    queries: list[tuple[list[float], float, dict | None]] = []
    if positives:
        for component in positives[:TOP_COMPONENTS_FOR_RETRIEVAL]:
            queries.append((component["_vector"], float(component["weight"]), component))
    if profile_vector:
        queries.append((profile_vector, max(0.5, sum(c["weight"] for c in positives) * 0.3), None))

    if not queries:
        return []

    per_query_raw: list[list[dict]] = []
    for vector, _w, _comp in queries:
        results = await _vector_search(vector)
        per_query_raw.append(results)

    per_query_filtered: list[list[dict]] = []
    for results in per_query_raw:
        kept = []
        for doc in results:
            external_id = doc.get("external_id")
            if external_id and external_id in seen:
                continue
            kept.append(doc)
        per_query_filtered.append(kept)

    interleaved = interleave_by_weight(
        lists=per_query_filtered,
        weights=[w for _v, w, _c in queries],
        limit=max(page_size * 4, page_size),
        key=lambda d: d.get("external_id") or id(d),
    )

    if not interleaved:
        return []

    for doc in interleaved:
        vector_score = float(doc.get("vector_score") or 0.0)
        recency = recency_score(doc.get("year"))
        citations = citation_score(doc.get("citation_count"))
        affinity = float(doc.get("_affinity_score") or 0.0)
        doc["_final_score"] = composite_score(vector_score, recency, citations, affinity)

    interleaved.sort(key=lambda d: d["_final_score"], reverse=True)
    selected = _mmr_select(interleaved, page_size)

    for item in selected:
        item["reason"] = _build_reason(item.get("embedding") or [], hydrated)
        item["score"] = round(float(item.get("_final_score", 0.0)), 4)

    return selected
```

Add the import at the top of `ranker.py`:

```python
from app.services.recommendations.scoring import interleave_by_weight
```

- [ ] **Step 3: Run all existing tests + verify import**

Run: `pytest tests/recommendations/ -q && python -c "from app.services.recommendations.ranker import rank_for_profile; print('ok')"`
Expected: existing tests still pass, import ok.

- [ ] **Step 4: Commit**

```bash
git add app/services/recommendations/ranker.py
git commit -m "feat(recs): multi-query retrieval interleaved by component weight"
```

---

## Task 6: Wire freshly-fetched candidates through `rank_in_memory` in the pipeline

Currently `pipeline.get_feed_page` re-calls `rank_for_profile` after `fetch_for_topics`, but the fresh papers aren't in the Atlas index. Fix: capture the returned candidate dicts from `fetch_for_topics` and pass them through `rank_in_memory`, then merge with the Atlas-ranked results.

**Files:**
- Modify: `app/services/recommendations/candidate_fetcher.py` — already returns the embedded-paper dicts; confirm shape.
- Modify: `app/services/recommendations/pipeline.py` — call `rank_in_memory` and merge.

- [ ] **Step 1: Confirm `fetch_for_topics` returns embedded candidates**

Read `app/services/recommendations/candidate_fetcher.py:59-92`. Confirm `fetch_for_topics` returns `candidate_dicts` (all candidates, with `embedding` populated on fresh rows after `ensure_paper_embeddings`).

- [ ] **Step 2: Rewrite `get_feed_page` in `pipeline.py`**

Replace the body of `get_feed_page` (lines 110-183) with:

```python
async def get_feed_page(
    username: str,
    cursor: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> FeedPage:
    profile = await load_profile(username)
    if profile.is_cold_start or not profile.vector:
        raise ColdStartRequired()

    component_dicts = [
        {"kind": c.kind, "label": c.label, "weight": c.weight, "meta": c.meta}
        for c in profile.components
    ]
    positive_labels = [
        c["label"] for c in component_dicts if c["weight"] > 0 and c.get("label")
    ]
    prepare_lookup, lookup = _make_embed_lookup(positive_labels)
    await prepare_lookup()

    topics = [
        c["label"]
        for c in sorted(
            component_dicts, key=lambda c: abs(c.get("weight", 0)), reverse=True
        )
        if c.get("label")
    ]

    atlas_ranked = await rank_for_profile(
        profile_vector=profile.vector,
        profile_components=component_dicts,
        seen_paper_ids=profile.seen_paper_ids,
        page_size=page_size * 2,  # over-fetch so we can dedup against fresh
        embed_lookup=lookup,
    )

    if len(atlas_ranked) < max(1, int(page_size * MIN_POOL_FOR_PAGE)):
        fresh_candidates = await fetch_for_topics(topics)

        query_vectors: list[list[float]] = []
        query_weights: list[float] = []
        for component in component_dicts:
            if component["weight"] <= 0:
                continue
            vector = lookup(component["label"])
            if not vector:
                continue
            query_vectors.append(vector)
            query_weights.append(float(component["weight"]))
        if not query_vectors and profile.vector:
            query_vectors = [profile.vector]
            query_weights = [1.0]

        seen_set = set(profile.seen_paper_ids or [])
        atlas_ids = {p.get("external_id") for p in atlas_ranked if p.get("external_id")}
        # Don't re-show candidates Atlas already ranked
        seen_for_inmem = seen_set | atlas_ids
        in_mem_ranked = await rank_in_memory(
            query_vectors=query_vectors,
            weights=query_weights,
            candidates=fresh_candidates,
            seen_ids=seen_for_inmem,
            page_size=page_size * 2,
        )
        # Attach reasons to in-memory ranked items
        hydrated = []
        from app.services.recommendations.ranker import _hydrate_components, _build_reason
        hydrated = _hydrate_components(component_dicts, lookup)
        for item in in_mem_ranked:
            item["reason"] = _build_reason(item.get("embedding") or [], hydrated)
            item["score"] = round(float(item.get("_final_score", 0.0)), 4)

        merged = atlas_ranked + in_mem_ranked
        merged.sort(key=lambda d: d.get("_final_score") or d.get("score") or 0.0, reverse=True)
        ranked = merged[:page_size]
    else:
        ranked = atlas_ranked[:page_size]

    if ranked and topics:
        asyncio.create_task(replenish(topics))

    # Apply cursor as an offset over the ranked window so subsequent pages
    # advance instead of returning the same top-N minus seen.
    if cursor > 0:
        ranked = ranked[cursor : cursor + page_size] if cursor < len(ranked) else []

    chosen_ids = [doc.get("external_id") for doc in ranked if doc.get("external_id")]
    if chosen_ids:
        await record_impressions(username, chosen_ids)

    serialized = [_serialize_paper(doc) for doc in ranked]
    has_more = len(ranked) >= page_size
    next_cursor = cursor + len(ranked)

    return FeedPage(
        papers=serialized,
        next_cursor=next_cursor,
        has_more=has_more,
        profile_summary=_profile_summary(profile),
    )
```

- [ ] **Step 3: Add the import**

At the top of `pipeline.py`, add to the existing imports from `ranker`:

```python
from app.services.recommendations.ranker import rank_for_profile, rank_in_memory
```

- [ ] **Step 4: Smoke-test import**

Run: `python -c "from app.services.recommendations.pipeline import get_feed_page; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add app/services/recommendations/pipeline.py
git commit -m "fix(recs): rank freshly-fetched candidates in memory to bypass Atlas index lag"
```

---

## Task 7: Author/venue affinity from search history + library

Read the user's recent searches and saved library to compute simple frequency tables for top authors and top venues, then boost matching candidates' affinity score.

**Files:**
- Create: `app/services/recommendations/affinity.py`
- Create: `tests/recommendations/test_affinity.py`
- Modify: `app/services/recommendations/pipeline.py` — fetch affinity, attach `_affinity_score` to candidates before ranking.

- [ ] **Step 1: Write the failing test**

Create `tests/recommendations/test_affinity.py`:

```python
import pytest

from app.services.recommendations.affinity import (
    AffinityProfile,
    affinity_score_for_paper,
)


def test_affinity_score_zero_when_empty():
    prof = AffinityProfile(authors={}, venues={})
    assert affinity_score_for_paper({"authors": ["Alice"], "venue": "NeurIPS"}, prof) == 0.0


def test_affinity_score_author_match():
    prof = AffinityProfile(authors={"alice": 1.0}, venues={})
    s = affinity_score_for_paper({"authors": ["Alice", "Bob"], "venue": "X"}, prof)
    assert 0 < s <= 1.0


def test_affinity_score_venue_match():
    prof = AffinityProfile(authors={}, venues={"neurips": 1.0})
    s = affinity_score_for_paper({"authors": [], "venue": "NeurIPS 2024"}, prof)
    assert 0 < s <= 1.0


def test_affinity_score_clamped():
    prof = AffinityProfile(
        authors={"alice": 10.0, "bob": 10.0},
        venues={"neurips": 10.0},
    )
    s = affinity_score_for_paper(
        {"authors": ["Alice", "Bob"], "venue": "NeurIPS"}, prof
    )
    assert s <= 1.0
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/recommendations/test_affinity.py -q`
Expected: ImportError for `app.services.recommendations.affinity`.

- [ ] **Step 3: Implement `affinity.py`**

Create `app/services/recommendations/affinity.py`:

```python
"""Author/venue affinity profile derived from search history + library saves.

Counts are frequency-weighted with light recency decay. We deliberately keep
this independent of the embedding-based profile so the signal is interpretable
and easy to inspect via `/explore/diagnostics`.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.db.session import (
    library_items_collection,
    search_history_collection,
)

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 60
MAX_AUTHORS = 25
MAX_VENUES = 25


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


@dataclass
class AffinityProfile:
    authors: dict[str, float] = field(default_factory=dict)  # normalized name -> weight
    venues: dict[str, float] = field(default_factory=dict)   # normalized venue token -> weight


async def build_affinity(username: str) -> AffinityProfile:
    """Aggregate venue/author counts from library_items + search_history."""
    profile = AffinityProfile()
    if not username:
        return profile

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    if library_items_collection is not None:
        try:
            cursor = library_items_collection.find(
                {"owner": username},
                projection={"authors": 1, "venue": 1, "added_at": 1, "updated_at": 1},
            ).limit(500)
            async for item in cursor:
                ts = item.get("added_at") or item.get("updated_at")
                weight = _recency_weight(ts, cutoff)
                for author in (item.get("authors") or [])[:8]:
                    key = _norm(author)
                    if not key:
                        continue
                    profile.authors[key] = profile.authors.get(key, 0.0) + weight
                venue_key = _norm(item.get("venue"))
                if venue_key:
                    profile.venues[venue_key] = profile.venues.get(venue_key, 0.0) + weight
        except Exception:
            logger.exception("affinity: library scan failed for %s", username)

    if search_history_collection is not None:
        try:
            cursor = (
                search_history_collection.find(
                    {"username": username, "created_at": {"$gte": cutoff}},
                    projection={"venue": 1, "created_at": 1},
                )
                .sort("created_at", -1)
                .limit(100)
            )
            async for entry in cursor:
                venue_key = _norm(entry.get("venue"))
                if venue_key:
                    weight = _recency_weight(entry.get("created_at"), cutoff)
                    profile.venues[venue_key] = profile.venues.get(venue_key, 0.0) + weight * 0.5
        except Exception:
            logger.exception("affinity: search_history scan failed for %s", username)

    profile.authors = _top_n(profile.authors, MAX_AUTHORS)
    profile.venues = _top_n(profile.venues, MAX_VENUES)
    _normalize(profile.authors)
    _normalize(profile.venues)
    return profile


def affinity_score_for_paper(paper: dict, profile: AffinityProfile) -> float:
    """Return an affinity score in [0, 1] for a single candidate paper."""
    if not profile.authors and not profile.venues:
        return 0.0
    author_score = 0.0
    for author in (paper.get("authors") or [])[:5]:
        weight = profile.authors.get(_norm(author))
        if weight:
            author_score += weight
    venue = _norm(paper.get("venue"))
    venue_score = 0.0
    if venue:
        for known, w in profile.venues.items():
            if known and (known == venue or known in venue or venue in known):
                venue_score = max(venue_score, w)
                break
    # cap at 1.0; author hits are additive across multiple matches
    return min(1.0, author_score * 0.6 + venue_score * 0.4)


def _recency_weight(ts, cutoff: datetime) -> float:
    if not isinstance(ts, datetime):
        return 0.4
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    span = max((datetime.now(timezone.utc) - cutoff).total_seconds(), 1.0)
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return max(0.2, math.exp(-age / span))


def _top_n(counts: dict[str, float], n: int) -> dict[str, float]:
    if len(counts) <= n:
        return counts
    items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return dict(items)


def _normalize(counts: dict[str, float]) -> None:
    if not counts:
        return
    peak = max(counts.values())
    if peak <= 0:
        return
    for key in list(counts.keys()):
        counts[key] = counts[key] / peak
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/recommendations/test_affinity.py -q`
Expected: 4 passed.

- [ ] **Step 5: Wire affinity into `pipeline.get_feed_page`**

At the top of `pipeline.py`, add:

```python
from app.services.recommendations.affinity import (
    affinity_score_for_paper,
    build_affinity,
)
```

In `get_feed_page`, right after `await prepare_lookup()` (before the call to `rank_for_profile`), insert:

```python
    affinity = await build_affinity(username)

    def _attach_affinity(docs: list[dict]) -> None:
        for doc in docs:
            doc["_affinity_score"] = affinity_score_for_paper(doc, affinity)
```

Then call `_attach_affinity` on the Atlas results before they're scored. Since `rank_for_profile` reads `doc["_affinity_score"]` (already wired in Task 5), we need to set it on the raw vector-search results. Easiest path: do affinity inside `_vector_search` callers. The simplest place is the pipeline — call `_attach_affinity(atlas_ranked)` *before* ranking, but `rank_for_profile` already does composite scoring internally.

Instead, push affinity down into `rank_for_profile` so it's applied during the composite-score step. Update Task 5's `rank_for_profile` signature to accept an optional `affinity_profile`:

In `ranker.py`, change the `rank_for_profile` signature to:

```python
async def rank_for_profile(
    profile_vector: list[float],
    profile_components: list[dict],
    seen_paper_ids: list[str],
    page_size: int,
    embed_lookup,
    affinity_profile=None,
) -> list[dict]:
```

And in the scoring loop, replace `affinity = float(doc.get("_affinity_score") or 0.0)` with:

```python
        if affinity_profile is not None:
            from app.services.recommendations.affinity import affinity_score_for_paper
            affinity = affinity_score_for_paper(doc, affinity_profile)
        else:
            affinity = 0.0
```

Then in `pipeline.get_feed_page`, pass `affinity_profile=affinity` into both `rank_for_profile` and `rank_in_memory`. For `rank_in_memory`, similarly add an optional `affinity_profile` parameter and use it in the scoring loop.

- [ ] **Step 6: Run all tests to ensure no regressions**

Run: `pytest tests/recommendations/ -q && python -c "from app.services.recommendations.pipeline import get_feed_page; print('ok')"`
Expected: all 16 tests passed, import ok.

- [ ] **Step 7: Commit**

```bash
git add app/services/recommendations/affinity.py app/services/recommendations/pipeline.py app/services/recommendations/ranker.py tests/recommendations/test_affinity.py
git commit -m "feat(recs): boost author/venue matches via affinity profile"
```

---

## Task 8: Time-decayed seen-list

Currently `seen_paper_ids` is a fixed-size ring buffer with no time decay. After two scrolls a user is permanently barred from seeing those papers. Switch to a `seen_impressions` array of `{external_id, ts}` entries with a 21-day expiry filter at read time.

**Files:**
- Modify: `app/services/recommendations/profile_builder.py` — replace `record_impressions` and add `_recent_seen_ids` helper. Update `load_profile` to read decayed set.

- [ ] **Step 1: Update `record_impressions`**

In `app/services/recommendations/profile_builder.py:326-345`, replace the function with:

```python
SEEN_EXPIRY_DAYS = 21
SEEN_MAX_KEEP = 1000


async def record_impressions(username: str, external_ids: list[str], max_keep: int = SEEN_MAX_KEEP) -> None:
    """Append timestamped impressions; trim to `max_keep`.

    Stores `seen_impressions = [{id, ts}, ...]` rather than a bare id list so
    `load_profile` can filter out impressions older than SEEN_EXPIRY_DAYS,
    letting old papers resurface.
    """
    if user_profiles_collection is None or not username or not external_ids:
        return
    now = datetime.now(timezone.utc)
    entries = [{"id": eid, "ts": now} for eid in external_ids if eid]
    if not entries:
        return
    try:
        await user_profiles_collection.update_one(
            {"username": username},
            {
                "$push": {
                    "seen_impressions": {
                        "$each": entries,
                        "$slice": -max_keep,
                    }
                },
                "$set": {"seen_impressions_updated_at": now},
            },
            upsert=True,
        )
    except Exception:
        logger.exception("Failed to record impressions for %s", username)
```

- [ ] **Step 2: Update `load_profile` to materialize the decayed seen-set**

In `profile_builder.py`, find the `load_profile` function. Replace the line that reads `seen_paper_ids = list(doc.get("seen_paper_ids") or [])` (appears in both `load_profile` and `build_profile`) with a helper call:

```python
def _decayed_seen_ids(doc: dict) -> list[str]:
    impressions = doc.get("seen_impressions") or []
    cutoff = datetime.now(timezone.utc) - timedelta(days=SEEN_EXPIRY_DAYS)
    ids: list[str] = []
    for entry in impressions:
        ts = entry.get("ts") if isinstance(entry, dict) else None
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                ids.append(entry.get("id"))
        else:
            # legacy entries without ts — treat as fresh to avoid forever-block
            ids.append(entry.get("id") if isinstance(entry, dict) else entry)
    # also include any legacy bare-list field
    for legacy in (doc.get("seen_paper_ids") or []):
        ids.append(legacy)
    return [i for i in ids if i]
```

And replace each `seen_paper_ids = list(doc.get("seen_paper_ids") or [])` call with `seen_paper_ids = _decayed_seen_ids(doc)`.

Add `from datetime import timedelta` to the existing `datetime` import line (line 16):

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 3: Smoke import test**

Run: `python -c "from app.services.recommendations.profile_builder import load_profile, record_impressions; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add app/services/recommendations/profile_builder.py
git commit -m "feat(recs): time-decayed seen-list so old impressions can resurface"
```

---

## Task 9: Diagnostics endpoint

Operators need a one-shot way to see *why* the feed is empty. Expose `GET /explore/diagnostics` returning: pool size, embedded-paper count, profile state, atlas-index probe.

**Files:**
- Modify: `app/api/routes/explore.py` — append a new route and helper.

- [ ] **Step 1: Add a Pydantic response model**

In `app/api/routes/explore.py`, after the existing response models, add:

```python
class ExploreDiagnosticsResponse(BaseModel):
    paper_count: int
    embedded_paper_count: int
    profile_state: str  # "cold_start" | "ready"
    profile_vector_dim: Optional[int] = None
    seen_count: int = 0
    top_components: List[dict] = Field(default_factory=list)
    affinity: dict = Field(default_factory=dict)
    vector_search_ok: bool = False
    vector_search_sample: int = 0
    notes: List[str] = Field(default_factory=list)
```

- [ ] **Step 2: Add the route handler**

Append to `app/api/routes/explore.py`:

```python
@router.get(
    "/explore/diagnostics",
    response_model=ExploreDiagnosticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Operator-facing health check for the explore feed",
)
async def explore_diagnostics(current_user: dict = Depends(get_current_user)):
    _ensure_enabled()
    from app.db.session import papers_collection, user_profiles_collection
    from app.services.recommendations.affinity import build_affinity
    from app.services.recommendations.ranker import VECTOR_INDEX_NAME

    username = _username(current_user)
    notes: list[str] = []

    paper_count = 0
    embedded_paper_count = 0
    if papers_collection is not None:
        try:
            paper_count = await papers_collection.estimated_document_count()
        except Exception:
            notes.append("estimated_document_count failed")
        try:
            embedded_paper_count = await papers_collection.count_documents(
                {"embedding": {"$exists": True}}, limit=10001
            )
        except Exception:
            notes.append("embedded count failed")
    else:
        notes.append("papers_collection is None")

    profile = await profile_builder.load_profile(username)
    profile_state = "cold_start" if profile.is_cold_start else "ready"
    profile_vector_dim = len(profile.vector) if profile.vector else None
    seen_count = len(profile.seen_paper_ids)
    top_components = [
        {"kind": c.kind, "label": c.label, "weight": round(c.weight, 3)}
        for c in (profile.components or [])[:8]
    ]

    affinity = await build_affinity(username)
    affinity_summary = {
        "top_authors": list(affinity.authors.keys())[:5],
        "top_venues": list(affinity.venues.keys())[:5],
    }

    vector_search_ok = False
    vector_search_sample = 0
    if papers_collection is not None and profile.vector:
        try:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": VECTOR_INDEX_NAME,
                        "path": "embedding",
                        "queryVector": profile.vector,
                        "numCandidates": 20,
                        "limit": 5,
                    }
                },
                {"$count": "n"},
            ]
            async for doc in papers_collection.aggregate(pipeline):
                vector_search_sample = int(doc.get("n", 0))
            vector_search_ok = True
        except Exception as exc:
            notes.append(f"$vectorSearch probe failed: {exc!s}")

    if paper_count == 0:
        notes.append("papers collection is empty — run a search to seed it")
    elif embedded_paper_count == 0:
        notes.append(
            "no papers carry an embedding — run "
            "`python -m scripts.backfill_paper_embeddings`"
        )
    elif not vector_search_ok:
        notes.append(
            "$vectorSearch probe failed — check the `papers_vector_index` "
            "Atlas Search index exists and matches the embedding dimension"
        )

    return ExploreDiagnosticsResponse(
        paper_count=paper_count,
        embedded_paper_count=embedded_paper_count,
        profile_state=profile_state,
        profile_vector_dim=profile_vector_dim,
        seen_count=seen_count,
        top_components=top_components,
        affinity=affinity_summary,
        vector_search_ok=vector_search_ok,
        vector_search_sample=vector_search_sample,
        notes=notes,
    )
```

- [ ] **Step 3: Manual smoke test**

Start the dev server: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &`
Wait for `Uvicorn running`. Then: `curl -s http://localhost:8000/explore/diagnostics | python -m json.tool`
Expected: JSON with `paper_count`, `embedded_paper_count`, `profile_state`, etc. `notes` will tell you what's missing.
Stop the server.

- [ ] **Step 4: Commit**

```bash
git add app/api/routes/explore.py
git commit -m "feat(explore): /explore/diagnostics endpoint for pool/profile health"
```

---

## Task 10: Cold-start fallback to direct topic search

When the user has saved seeds but the corpus has no embedded matches yet, return papers fetched in real time from arXiv/S2 instead of an empty page. Same path the user gets on first scroll today, but with a clearer message.

**Files:**
- Modify: `app/services/recommendations/pipeline.py` — when the merged ranked list is still empty, fall back to a topic-search using the seed topics directly and synthesize an "early-access" reason.

- [ ] **Step 1: Add the cold-start fallback after the merged ranking**

In `pipeline.get_feed_page`, inside the `if len(atlas_ranked) < ...` branch (after the existing in-memory ranking merge), if `ranked` is still empty append:

```python
        if not ranked and fresh_candidates:
            # Atlas returned nothing AND in-memory ranking returned nothing
            # (e.g. no candidates carried embeddings). Surface the freshest
            # arXiv/S2 hits unranked but flagged so the user isn't stuck.
            fallback = []
            seen_so_far: set[str] = set()
            for paper in fresh_candidates[: page_size]:
                external_id = paper.get("external_id")
                if not external_id or external_id in seen_set or external_id in seen_so_far:
                    continue
                seen_so_far.add(external_id)
                item = dict(paper)
                item["reason"] = "New result for your seed topics"
                item["score"] = 0.0
                item["_final_score"] = 0.0
                fallback.append(item)
            ranked = fallback
```

(`fresh_candidates` was already in scope from Task 6. `seen_set` was already defined there.)

- [ ] **Step 2: Smoke import test**

Run: `python -c "from app.services.recommendations.pipeline import get_feed_page; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/services/recommendations/pipeline.py
git commit -m "feat(recs): fall back to direct topic-search when ranked pool is empty"
```

---

## Task 11: Frontend — surface diagnostics + improved empty state

When the user lands on `/workspace/explore` and the feed comes back empty, show the diagnostics notes instead of "No recommendations yet." so the user can self-diagnose.

**Files:**
- Modify: `frontend/js/search.js` — add `fetchExploreDiagnostics()`.
- Modify: `frontend/js/alpine/components/exploreFeed.js` — fetch diagnostics on empty state and display.
- Modify: `frontend/html/index.html:990-992` — replace the static "No recommendations yet." block.

- [ ] **Step 1: Add API helper**

In `frontend/js/search.js`, after `fetchExploreProfile` (~line 126), add:

```javascript
async function fetchExploreDiagnostics() {
    const response = await authenticatedFetch(`${BASE_URL}/explore/diagnostics`, {
        method: "GET",
    });
    return await parseResponse(response, "Could not load explore diagnostics");
}
```

And add `fetchExploreDiagnostics` to the exported object (next to `fetchExploreProfile`).

- [ ] **Step 2: Use diagnostics in `exploreFeed.js`**

In `frontend/js/alpine/components/exploreFeed.js`, add a new field `diagnostics: null` at the top of the returned object, and a method:

```javascript
        async loadDiagnostics() {
            try {
                this.diagnostics = await window.searchAPI.fetchExploreDiagnostics();
            } catch (e) {
                this.diagnostics = { notes: ["Diagnostics endpoint failed: " + (e?.message || e)] };
            }
        },
```

In `loadMore()`, right after the loop that builds `newPapers`, if `this.$store.app.explore.papers.length === 0 && !data?.has_more && !this.diagnostics`, call `await this.loadDiagnostics()`.

- [ ] **Step 3: Render diagnostics in the empty state**

In `frontend/html/index.html:990-992`, replace:

```html
            <div x-show="!$store.app.explore.coldStart && !$store.app.explore.papers.length && !$store.app.explore.isLoadingPage && !$store.app.explore.error" style="text-align:center; padding:3rem 0; color:var(--text-muted);">
              No recommendations yet. Run a search or save some gap feedback to seed the feed.
            </div>
```

with:

```html
            <div x-show="!$store.app.explore.coldStart && !$store.app.explore.papers.length && !$store.app.explore.isLoadingPage && !$store.app.explore.error" style="text-align:center; padding:3rem 1rem; color:var(--text-muted); max-width: 540px; margin: 0 auto;">
              <p style="font-size: 0.95rem; margin-bottom: 1rem;">No recommendations yet.</p>
              <template x-if="diagnostics && Array.isArray(diagnostics.notes) && diagnostics.notes.length">
                <ul style="text-align: left; font-size: 0.85rem; line-height: 1.6; background: var(--glass-bg); border: 1px solid var(--border-color); border-radius: 10px; padding: 1rem 1.25rem; list-style: disc; padding-left: 2rem;">
                  <template x-for="note in diagnostics.notes" :key="note">
                    <li x-text="note"></li>
                  </template>
                </ul>
              </template>
              <p x-show="diagnostics && !diagnostics.notes?.length" style="font-size: 0.85rem;">Try a fresh search or upvote a gap to seed your profile.</p>
            </div>
```

- [ ] **Step 4: Bump the asset version on the changed JS to bust browser cache**

In `frontend/html/index.html:1225`, change `?v=20260514a` to `?v=20260514b`.

- [ ] **Step 5: Manual smoke test in browser**

Start the dev server: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &`
Open `http://localhost:8000/workspace/explore` in a browser. If no papers, confirm the diagnostics notes render. Stop the server.

- [ ] **Step 6: Commit**

```bash
git add frontend/js/search.js frontend/js/alpine/components/exploreFeed.js frontend/html/index.html
git commit -m "feat(explore-ui): surface diagnostics in the empty-state"
```

---

## Task 12: End-to-end smoke test (manual)

We don't yet have Playwright specs for explore. Add a minimal one to lock the cold-start → seed → feed flow.

**Files:**
- Create: `tests/e2e/explore.spec.js`

- [ ] **Step 1: Write the Playwright spec**

Create `tests/e2e/explore.spec.js`:

```javascript
const { test, expect } = require("@playwright/test");

test.describe("explore feed", () => {
  test("cold-start onboarding renders, accepts seeds, transitions to feed", async ({ page }) => {
    await page.goto("/workspace/explore");

    // Cold-start panel should be visible at first
    await expect(page.getByText(/Tell us what you're into/i)).toBeVisible({ timeout: 10_000 });

    // Type three seed topics
    const inputs = page.locator('input[placeholder^="Topic"]');
    await inputs.nth(0).fill("graph neural networks");
    await inputs.nth(1).fill("attention mechanisms");
    await inputs.nth(2).fill("self-supervised learning");

    await page.getByRole("button", { name: /Build my feed/i }).click();

    // Either we land on a populated feed OR the diagnostics-driven empty state
    // (both are acceptable end states for this smoke).
    await expect(async () => {
      const heading = await page.locator("h2.results-query-title").innerText();
      expect(heading.length).toBeGreaterThan(0);
    }).toPass({ timeout: 30_000 });
  });
});
```

- [ ] **Step 2: Run Playwright**

Run: `npm run test:e2e -- tests/e2e/explore.spec.js`
Expected: passes (assuming dev server is running on :8000 per playwright.config.js).

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/explore.spec.js
git commit -m "test(e2e): smoke-test the explore cold-start → feed flow"
```

---

## Self-Review

**1. Spec coverage:**
- "Not giving paper recommendations" → addressed by Task 6 (in-memory ranker bypasses Atlas index lag) + Task 10 (direct-search fallback) + Task 9 (operator can see exactly why).
- "Improve the recommendation algorithm" → addressed by Task 5 (multi-query retrieval), Task 7 (affinity boost), Task 8 (time-decayed seen list so feed stays fresh).
- Cursor pagination bug (`cursor` unused) → fixed in Task 6 Step 2.

**2. Placeholder scan:** all "TODO / fill in details / similar to" patterns absent. Every step shows the actual code or command to run.

**3. Type consistency:**
- `rank_for_profile` signature gains `affinity_profile=None` in Task 7 Step 5 — every caller in `pipeline.py` (Task 6 Step 2) is updated to pass it. Confirmed.
- `rank_in_memory` signature in Task 4 Step 3 matches every call site in Task 6 Step 2. Confirmed.
- `_decayed_seen_ids` is added in `profile_builder.py` (Task 8 Step 2) and replaces every legacy `seen_paper_ids = list(doc.get("seen_paper_ids") or [])` site. Confirmed.
- `interleave_by_weight` signature `(lists, weights, limit, key)` matches use in Task 5 Step 2. Confirmed.

**4. Spec-to-code mapping:**
- Atlas index latency root cause → Task 4 + Task 6.
- Bad single-centroid retrieval → Task 5.
- No author/venue signal → Task 7.
- Permanent dedup blocking re-discovery → Task 8.
- Operator blindness → Task 9.
- Empty cold-start → Task 10.
- Frontend invisibility of root cause → Task 11.
- Regression safety net → Tasks 2, 3, 4, 7, 12 add tests.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-14-improve-explore-recommendations.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
