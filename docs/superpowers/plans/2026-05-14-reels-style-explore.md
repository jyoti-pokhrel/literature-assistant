# Reels-Style Explore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/explore` show recommended papers on the very first visit — no seed-topic onboarding gate — and let it adapt to the user as they like, dislike, hide, or open papers from the feed (TikTok/Reels-style).

**Architecture:** Replace the hard `ColdStartRequired` gate with a **popular fallback**: when the user has no profile vector, rank the indexed papers by `recency + log10(citations)` with author/venue diversity. When the corpus is empty, fetch a curated default-topic pool from arXiv/S2 on the fly. Add a `paper_interactions` collection + `POST /explore/interactions` endpoint that records `open`, `like`, `dislike`, `hide` events, and feed those interactions back into `profile_builder` so the centroid moves toward "liked" papers and away from "disliked" ones in real time. Frontend drops the cold-start panel entirely and adds three small action buttons to every card.

**Tech Stack:** FastAPI (async) + Motor (Mongo) + Pydantic + Atlas Vector Search; SentenceTransformer (`all-MiniLM-L6-v2`, 384-dim) for the existing embedding hooks; pytest for the new unit tests; Alpine.js + plain DOM for the action UI.

---

## Why this is necessary (read first)

The merged improve-explore-recommendations PR (#21) fixed multi-query retrieval, Atlas latency, time-decayed seen-lists, and added a diagnostics endpoint. But the feed is still gated by `ColdStartRequired` in `app/services/recommendations/pipeline.py:122-123`:

```python
if profile.is_cold_start or not profile.vector:
    raise ColdStartRequired()
```

A new user opens `/explore`, sees the seed-topic form, and unless they type three topics, the feed never renders. That's the "0 papers · end of results" the user is seeing. Reels never asks for setup; this should not either.

Adaptation today only happens through explicit search submissions (search_history signal) and gap-feedback votes (gap_feedback_signals signal). Neither is available on a paper card in the explore view. To respond to user signal *while they scroll*, we need first-class per-card interactions persisted on the server.

## Scope check

This plan is one subsystem: the explore feed. Backend retrieval, interaction-logging, and the explore UI all change together — splitting them would leave an unusable intermediate state.

Things explicitly out of scope (defer to follow-up plans if the user asks):
- IntersectionObserver-based impression tracking on scroll (we use the existing `seen_impressions` ring buffer instead; explicit clicks are the live-signal hook).
- Re-ranking inside a single rendered page (we let interactions affect *future* pages — the next scroll or refresh).
- A user-facing "seed topics" settings drawer (we keep `POST /explore/seed` as an API affordance; the UI form is removed for now).

## File Structure

**New backend files:**
- `app/services/recommendations/popular.py` — pure-Python ranker for the no-profile / weak-profile path. Sorts indexed papers by recency + citation popularity, applies a simple venue-diversity pass.
- `app/services/recommendations/interactions.py` — persist and read per-user paper interactions (`open`, `like`, `dislike`, `hide`).

**Modified backend files:**
- `app/db/session.py` — declare `paper_interactions_collection` and create its indexes.
- `app/services/recommendations/profile_builder.py` — add a fourth signal source (interactions), looking up embeddings from `papers_collection` instead of re-embedding text.
- `app/services/recommendations/pipeline.py` — never raise `ColdStartRequired`; call `rank_popular` when there is no profile vector; remove the seed-topic dependency from the fallback branch.
- `app/api/routes/explore.py` — drop the 409 reaction; add `POST /explore/interactions`. Keep `POST /explore/seed` and `GET /explore/profile` for API consumers; the UI no longer drives them.
- `app/services/recommendations/__init__.py` — re-export the few entry points the routes now need (per the open follow-up from the previous review).

**Modified frontend files:**
- `frontend/html/index.html` — remove the cold-start panel (`x-show="$store.app.explore.coldStart"` block); insert a 3-button action bar (`Like` / `Hide` / `Open`) into each card; bump the asset versions.
- `frontend/js/alpine/components/exploreFeed.js` — `init()` always calls `loadMore()`; remove `coldStart` branching; add `recordInteraction(paper, kind)` that fires the API and locally removes hidden papers from the list.
- `frontend/js/search.js` — add `recordExploreInteractions(events)` API wrapper.
- `frontend/js/alpine/stores/appStore.js` — drop the `explore.coldStart` boolean from the store; remove related resets.

**New tests:**
- `tests/recommendations/test_popular.py` — ranker scoring, diversity, empty-corpus behavior.
- `tests/recommendations/test_interactions.py` — signal weighting math + dedup.

**Modified tests:**
- `tests/e2e/explore.spec.js` — assert that on first visit the feed renders papers (or an empty state) directly, with NO onboarding form visible.

---

## Task 1: Declare paper_interactions collection + indexes

**Files:**
- Modify: `app/db/session.py`

- [ ] **Step 1: Add the collection handle**

Open `/home/jyoti/Documents/code/research-agent/app/db/session.py`. Find the block where the other collections are declared (around line 67-82). Append the new line right after `gap_feedback_signals_collection`:

```python
paper_interactions_collection = db["paper_interactions"] if db is not None else None
```

- [ ] **Step 2: Add the indexes inside `init_indexes`**

Find `async def init_indexes()`. Right after the existing recommendations indexes for `gap_feedback_signals_collection` (the block ending with the unique `gap_feedback_signal_uniq` index), add:

```python
    # Per-user interaction log for the explore feed (open/like/dislike/hide).
    # Compound covers the common "load my recent feedback" query.
    await _safe_create_index(
        paper_interactions_collection,
        [("username", 1), ("ts", -1)],
    )
    # One write per (user, paper, kind) — dedup likes/dislikes/etc.
    await _safe_create_index(
        paper_interactions_collection,
        [("username", 1), ("external_id", 1), ("kind", 1)],
        unique=True,
        name="paper_interaction_uniq",
    )
```

- [ ] **Step 3: Smoke test the import**

Run: `cd /home/jyoti/Documents/code/research-agent && .venv/bin/python -c "from app.db.session import paper_interactions_collection; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add app/db/session.py
git commit -m "feat(db): declare paper_interactions collection + indexes"
```

---

## Task 2: interactions service + unit tests

**Files:**
- Create: `app/services/recommendations/interactions.py`
- Create: `tests/recommendations/test_interactions.py`

- [ ] **Step 1: Write the failing tests first**

Create `tests/recommendations/test_interactions.py`:

```python
import pytest

from app.services.recommendations.interactions import (
    InteractionSignal,
    INTERACTION_WEIGHTS,
    _weight_for,
)


def test_known_kinds_have_weights():
    for kind in ("open", "like", "save", "dislike", "hide"):
        assert kind in INTERACTION_WEIGHTS


def test_positive_signals_are_positive():
    assert _weight_for("like") > 0
    assert _weight_for("save") > 0
    assert _weight_for("open") > 0


def test_negative_signals_are_negative():
    assert _weight_for("dislike") < 0
    assert _weight_for("hide") < 0


def test_unknown_kind_returns_zero():
    assert _weight_for("invalid_kind") == 0.0
    assert _weight_for("") == 0.0
    assert _weight_for(None) == 0.0


def test_signal_dataclass_normalizes_kind():
    sig = InteractionSignal(external_id="abc", kind="LIKE", weight=0.0)
    # constructor doesn't lowercase — _weight_for() handles unknown case;
    # the field is preserved for diagnostics.
    assert sig.kind == "LIKE"
```

- [ ] **Step 2: Run the tests to confirm failure**

Run: `.venv/bin/pytest tests/recommendations/test_interactions.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.recommendations.interactions'`.

- [ ] **Step 3: Implement `interactions.py`**

Create `app/services/recommendations/interactions.py`:

```python
"""Per-user paper-interaction log for the explore feed.

Records every explicit per-card action (`open`, `like`, `save`, `dislike`,
`hide`) into `paper_interactions_collection`. The dedup index makes each
(user, paper, kind) record at-most-once — re-firing the same action just
refreshes `ts`.

`fetch_interaction_signals` powers the new signal source in
`profile_builder`. Embedding lookup is done from `papers_collection`
because the candidate paper has already been embedded for vector search.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db.session import paper_interactions_collection, papers_collection

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 30
SIGNAL_LIMIT = 200

INTERACTION_WEIGHTS: dict[str, float] = {
    "open": 0.3,
    "like": 1.0,
    "save": 1.0,
    "dislike": -0.8,
    "hide": -0.5,
}


@dataclass
class InteractionSignal:
    external_id: str
    kind: str
    weight: float
    ts: datetime
    embedding: list[float]


def _weight_for(kind) -> float:
    if not isinstance(kind, str):
        return 0.0
    return INTERACTION_WEIGHTS.get(kind, 0.0)


async def record_interaction(
    username: str, external_id: str, kind: str
) -> None:
    """Upsert one (user, paper, kind) row. Refreshes `ts` on re-fire."""
    if paper_interactions_collection is None or not username or not external_id:
        return
    if kind not in INTERACTION_WEIGHTS:
        return
    now = datetime.now(timezone.utc)
    try:
        await paper_interactions_collection.update_one(
            {"username": username, "external_id": external_id, "kind": kind},
            {
                "$set": {
                    "username": username,
                    "external_id": external_id,
                    "kind": kind,
                    "ts": now,
                }
            },
            upsert=True,
        )
    except Exception:
        logger.exception(
            "Failed to record interaction %s for %s on %s",
            kind,
            username,
            external_id,
        )


async def fetch_interaction_signals(username: str) -> list[InteractionSignal]:
    """Materialize the interaction signal list for the profile builder.

    Joins each interaction with the paper's stored embedding so the profile
    centroid can include it without re-embedding text. Interactions whose
    paper carries no embedding are skipped — they will contribute on the
    next call after embedding catches up.
    """
    if paper_interactions_collection is None or papers_collection is None:
        return []
    if not username:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    try:
        cursor = (
            paper_interactions_collection.find(
                {"username": username, "ts": {"$gte": cutoff}},
                projection={"external_id": 1, "kind": 1, "ts": 1},
            )
            .sort("ts", -1)
            .limit(SIGNAL_LIMIT)
        )
        rows = [doc async for doc in cursor]
    except Exception:
        logger.exception("Failed to load interactions for %s", username)
        return []

    if not rows:
        return []

    external_ids = list({r.get("external_id") for r in rows if r.get("external_id")})
    embeddings_by_id: dict[str, list[float]] = {}
    try:
        cursor = papers_collection.find(
            {"external_id": {"$in": external_ids}, "embedding": {"$exists": True}},
            projection={"external_id": 1, "embedding": 1},
        )
        async for doc in cursor:
            eid = doc.get("external_id")
            emb = doc.get("embedding")
            if eid and isinstance(emb, list) and emb:
                embeddings_by_id[eid] = emb
    except Exception:
        logger.exception("Failed to load embeddings for interactions of %s", username)
        return []

    signals: list[InteractionSignal] = []
    for row in rows:
        eid = row.get("external_id")
        kind = row.get("kind")
        weight = _weight_for(kind)
        if weight == 0.0 or not eid:
            continue
        emb = embeddings_by_id.get(eid)
        if not emb:
            continue
        ts = row.get("ts")
        if not isinstance(ts, datetime):
            ts = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        signals.append(
            InteractionSignal(
                external_id=eid, kind=kind, weight=weight, ts=ts, embedding=emb
            )
        )
    return signals
```

- [ ] **Step 4: Confirm tests now pass**

Run: `.venv/bin/pytest tests/recommendations/test_interactions.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/services/recommendations/interactions.py tests/recommendations/test_interactions.py
git commit -m "feat(recs): per-user paper interactions service + signal builder"
```

---

## Task 3: popular-page ranker

**Files:**
- Create: `app/services/recommendations/popular.py`
- Create: `tests/recommendations/test_popular.py`

- [ ] **Step 1: Write the failing tests first**

Create `tests/recommendations/test_popular.py`:

```python
import pytest

from app.services.recommendations.popular import (
    _popular_score,
    _diversify_by_venue,
)


def test_popular_score_combines_recency_and_citations():
    fresh_hi_cite = _popular_score({"year": 2025, "citation_count": 100})
    fresh_lo_cite = _popular_score({"year": 2025, "citation_count": 0})
    old_hi_cite = _popular_score({"year": 2018, "citation_count": 100})

    # higher citations within the same year beats lower citations
    assert fresh_hi_cite > fresh_lo_cite
    # for the same citations, newer beats older
    assert fresh_hi_cite > old_hi_cite


def test_popular_score_handles_missing_fields():
    assert _popular_score({}) == 0.0
    assert _popular_score({"year": None, "citation_count": None}) == 0.0


def test_diversify_caps_per_venue():
    items = [
        {"external_id": f"a{i}", "venue": "NeurIPS", "_pop_score": 1.0 - i * 0.01}
        for i in range(5)
    ] + [
        {"external_id": f"b{i}", "venue": "ICML", "_pop_score": 0.5 - i * 0.01}
        for i in range(5)
    ]
    out = _diversify_by_venue(items, page_size=4, per_venue_cap=2)
    venues = [p["venue"] for p in out]
    assert venues.count("NeurIPS") <= 2
    assert venues.count("ICML") <= 2
    # top-scoring items still preferred within the cap
    assert out[0]["external_id"] == "a0"


def test_diversify_falls_back_when_one_venue_dominates():
    items = [
        {"external_id": f"a{i}", "venue": "NeurIPS", "_pop_score": 1.0 - i * 0.001}
        for i in range(10)
    ]
    out = _diversify_by_venue(items, page_size=5, per_venue_cap=2)
    # only one venue is available — cap is relaxed so the page fills
    assert len(out) == 5
```

- [ ] **Step 2: Run the tests — should fail**

Run: `.venv/bin/pytest tests/recommendations/test_popular.py -q`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `popular.py`**

Create `app/services/recommendations/popular.py`:

```python
"""Popular-page ranker for users with no (or weak) profile vector.

Powers the first-visit explore feed. The score is a simple blend of
recency and citation popularity — fast, deterministic, and explainable.
Diversity is enforced by capping the number of papers per venue per page;
once any venue saturates the cap, we relax it to keep the page filled.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db.session import papers_collection
from app.services.recommendations.scoring import citation_score, recency_score

logger = logging.getLogger(__name__)

POOL_LIMIT = 500
PER_VENUE_CAP = 3
RECENCY_BLEND = 0.55
CITATION_BLEND = 0.45


def _popular_score(paper: dict) -> float:
    recency = recency_score(paper.get("year"))
    citations = citation_score(paper.get("citation_count"))
    return RECENCY_BLEND * recency + CITATION_BLEND * citations


def _diversify_by_venue(
    items: list[dict],
    page_size: int,
    per_venue_cap: int = PER_VENUE_CAP,
) -> list[dict]:
    """Cap items per venue while preserving rank order. Relaxes the cap if
    the page would otherwise be short — better one venue twice than a half page."""
    if not items or page_size <= 0:
        return []
    out: list[dict] = []
    venue_counts: dict[str, int] = {}
    overflow: list[dict] = []
    for item in items:
        venue = (item.get("venue") or "").strip().lower() or "_unknown"
        if venue_counts.get(venue, 0) < per_venue_cap:
            out.append(item)
            venue_counts[venue] = venue_counts.get(venue, 0) + 1
            if len(out) >= page_size:
                return out
        else:
            overflow.append(item)
    # Cap relaxed: pull from overflow until the page is full.
    for item in overflow:
        if len(out) >= page_size:
            break
        out.append(item)
    return out


async def rank_popular(
    seen_paper_ids: set[str],
    page_size: int,
) -> list[dict]:
    """Return up to `page_size` recency + citations ranked papers from the DB.

    Filters out previously-seen ids and applies a per-venue diversity cap.
    Returns `[]` if the embedded paper pool is empty — the caller is
    responsible for the next-level fallback (direct topic fetch).
    """
    if papers_collection is None or page_size <= 0:
        return []
    try:
        cursor = papers_collection.find(
            {"embedding": {"$exists": True}},
            projection={
                "source": 1,
                "external_id": 1,
                "title": 1,
                "abstract": 1,
                "authors": 1,
                "year": 1,
                "venue": 1,
                "url": 1,
                "pdf_url": 1,
                "citation_count": 1,
                "doi": 1,
                "embedding": 1,
            },
        ).limit(POOL_LIMIT)
        pool = [doc async for doc in cursor]
    except Exception:
        logger.exception("rank_popular: pool fetch failed")
        return []

    filtered = []
    for paper in pool:
        eid = paper.get("external_id")
        if eid and eid in seen_paper_ids:
            continue
        paper["_pop_score"] = _popular_score(paper)
        paper["_final_score"] = paper["_pop_score"]
        filtered.append(paper)

    filtered.sort(key=lambda d: d["_pop_score"], reverse=True)
    selected = _diversify_by_venue(filtered, page_size=page_size)

    for item in selected:
        item["reason"] = "Trending recently"
        item["score"] = round(float(item.get("_pop_score", 0.0)), 4)
    return selected
```

- [ ] **Step 4: Run the tests to confirm pass**

Run: `.venv/bin/pytest tests/recommendations/test_popular.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/services/recommendations/popular.py tests/recommendations/test_popular.py
git commit -m "feat(recs): popular-page ranker for users with no profile vector"
```

---

## Task 4: Wire interactions into profile_builder

**Files:**
- Modify: `app/services/recommendations/profile_builder.py`

- [ ] **Step 1: Add the import for the new signal source**

Open `/home/jyoti/Documents/code/research-agent/app/services/recommendations/profile_builder.py`. After the existing `from app.services.recommendations.signals import (...)` block (around line 25-30), add:

```python
from app.services.recommendations.interactions import (
    INTERACTION_WEIGHTS,
    fetch_interaction_signals,
)
```

- [ ] **Step 2: Add the constants**

Right after `GAP_NEGATIVE_WEIGHT = -0.6` (around line 38), add:

```python
INTERACTION_HALF_LIFE_DAYS = 21.0
```

- [ ] **Step 3: Add a helper for interaction decay**

In the same file, alongside `_search_weight` and `_gap_weight` helpers, add:

```python
def _interaction_weight(signal) -> float:
    """Decay raw interaction weights over INTERACTION_HALF_LIFE_DAYS."""
    age = (datetime.now(timezone.utc) - signal.ts).total_seconds() / 86400.0
    return signal.weight * min(1.0, math.exp(-age / INTERACTION_HALF_LIFE_DAYS))
```

- [ ] **Step 4: Add the interaction loop inside `_compose_profile`**

Find the `_compose_profile` function. After the existing gap-signal loop (the block ending with `components.append(ProfileComponent(... kind="gap_positive"... ))`), add:

```python
    interaction_signals = await fetch_interaction_signals(username)
    for signal in interaction_signals:
        weight = _interaction_weight(signal)
        if weight == 0.0:
            continue
        components.append(
            ProfileComponent(
                kind=(
                    "interaction_positive"
                    if weight > 0
                    else "interaction_negative"
                ),
                label=signal.external_id,
                weight=weight,
                vector=list(signal.embedding),
                meta={"kind": signal.kind, "ts": signal.ts.isoformat()},
            )
        )
```

- [ ] **Step 5: Confirm tests still green**

Run: `.venv/bin/pytest tests/ -q`
Expected: all pre-existing tests still pass (19 from the previous PR + 9 new = 28).

- [ ] **Step 6: Commit**

```bash
git add app/services/recommendations/profile_builder.py
git commit -m "feat(recs): feed paper interactions into the profile centroid"
```

---

## Task 5: Replace the cold-start raise with a popular fallback

**Files:**
- Modify: `app/services/recommendations/pipeline.py`

- [ ] **Step 1: Update the imports**

Open `/home/jyoti/Documents/code/research-agent/app/services/recommendations/pipeline.py`. Find the existing `from app.services.recommendations.ranker import (...)` block. Below it, add:

```python
from app.services.recommendations.popular import rank_popular
```

The existing `ColdStartRequired` class can stay defined (some tests or external callers may reference it) but will no longer be raised. Keep the dataclass `FeedPage` unchanged.

- [ ] **Step 2: Replace the early `raise` with the popular fallback**

Find lines 121-123 (the `if profile.is_cold_start or not profile.vector:` block) and replace them with:

```python
    seen_set = set(profile.seen_paper_ids or [])

    if profile.is_cold_start or not profile.vector:
        popular = await rank_popular(seen_paper_ids=seen_set, page_size=page_size)
        if not popular:
            # Corpus has no embedded papers yet — pull a curated default
            # pool from arXiv/S2 so the user sees something on first visit.
            default_topics = [
                "machine learning",
                "neural networks",
                "climate science",
                "neuroscience",
                "computer vision",
            ]
            fresh = await fetch_for_topics(default_topics)
            popular = []
            for paper in fresh[:page_size]:
                eid = paper.get("external_id")
                if not eid or eid in seen_set:
                    continue
                item = dict(paper)
                item["reason"] = "New from arXiv & Semantic Scholar"
                item["score"] = 0.0
                item["_final_score"] = 0.0
                popular.append(item)

        chosen_ids = [doc.get("external_id") for doc in popular if doc.get("external_id")]
        if chosen_ids:
            await record_impressions(username, chosen_ids)
        return FeedPage(
            papers=[_serialize_paper(doc) for doc in popular],
            next_cursor=cursor + len(popular),
            has_more=len(popular) >= page_size,
            profile_summary=_profile_summary(profile),
        )
```

Then **remove** the now-duplicate `seen_set = set(profile.seen_paper_ids or [])` line further down in the same function (search for it).

- [ ] **Step 3: Smoke test the import**

Run: `.venv/bin/python -c "from app.services.recommendations.pipeline import get_feed_page, ColdStartRequired; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Confirm all tests still pass**

Run: `.venv/bin/pytest tests/ -q`
Expected: all green (no test pinned the 409 path; it was UI-only).

- [ ] **Step 5: Commit**

```bash
git add app/services/recommendations/pipeline.py
git commit -m "feat(recs): popular fallback instead of cold-start raise"
```

---

## Task 6: `/explore/interactions` endpoint + drop the 409

**Files:**
- Modify: `app/api/routes/explore.py`

- [ ] **Step 1: Add the new request models**

Open `/home/jyoti/Documents/code/research-agent/app/api/routes/explore.py`. After the existing `ExploreProfileResponse` model (around line 92), add:

```python
class ExploreInteractionEvent(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=200)
    kind: str = Field(..., min_length=1, max_length=20)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        from app.services.recommendations.interactions import INTERACTION_WEIGHTS
        v = value.strip().lower()
        if v not in INTERACTION_WEIGHTS:
            raise ValueError(f"unknown interaction kind: {value}")
        return v


class ExploreInteractionsRequest(BaseModel):
    events: List[ExploreInteractionEvent] = Field(..., min_length=1, max_length=50)


class ExploreInteractionsResponse(BaseModel):
    recorded: int
```

- [ ] **Step 2: Remove the 409 reaction in `/explore/feed`**

Find the `explore_feed` handler (around lines 144-165) and replace its body with:

```python
    _ensure_enabled()
    page = await get_feed_page(
        _username(current_user),
        cursor=payload.cursor,
        page_size=payload.page_size,
    )
    return ExploreFeedResponse(
        papers=page.papers,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        profile_summary=page.profile_summary,
    )
```

The `ColdStartRequired` import can stay — `get_feed_page` no longer raises it after Task 5, but the symbol remains exported for backward compatibility.

- [ ] **Step 3: Add the new route**

After the `explore_diagnostics` handler (the last function in the file), add:

```python
@router.post(
    "/explore/interactions",
    response_model=ExploreInteractionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Record per-card user interactions (open / like / dislike / hide)",
)
async def record_explore_interactions(
    payload: ExploreInteractionsRequest,
    current_user: dict = Depends(get_current_user),
):
    _ensure_enabled()
    from app.services.recommendations.interactions import record_interaction

    username = _username(current_user)
    recorded = 0
    for event in payload.events:
        await record_interaction(username, event.external_id, event.kind)
        recorded += 1
    # Profile vector is rebuilt lazily on next /explore/feed; mark it stale.
    await profile_builder.invalidate(username)
    return ExploreInteractionsResponse(recorded=recorded)
```

- [ ] **Step 4: Manual smoke test**

Start the dev server:

```bash
cd /home/jyoti/Documents/code/research-agent && AUTH_DEV_BYPASS=1 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uv.log 2>&1 &
sleep 4
curl -s -X POST http://127.0.0.1:8000/explore/feed -H 'Content-Type: application/json' -d '{"page_size": 5}' | head -c 200
pkill -f "uvicorn app.main:app"
```

Expected: a JSON response with a `papers` array, possibly empty, but with NO 409 status — and definitely no `cold_start_required` detail.

If the server doesn't pick up `AUTH_DEV_BYPASS=1` (the project's config may require it as a settings field) the request 401s. That confirms wiring; the change to the 409 is verified by reading the handler code in step 2.

- [ ] **Step 5: Commit**

```bash
git add app/api/routes/explore.py
git commit -m "feat(explore): /explore/interactions endpoint and remove 409 cold-start path"
```

---

## Task 7: Frontend — drop the cold-start panel, always load

**Files:**
- Modify: `frontend/js/alpine/components/exploreFeed.js`
- Modify: `frontend/js/alpine/stores/appStore.js`
- Modify: `frontend/html/index.html`

- [ ] **Step 1: Simplify `exploreFeed.js`**

Replace the entire contents of `/home/jyoti/Documents/code/research-agent/frontend/js/alpine/components/exploreFeed.js` with:

```javascript
window.exploreFeed = function exploreFeed() {
    return {
        diagnostics: null,

        init() {
            const store = this.$store?.app;
            if (!store) return;
            if (store.currentView !== 'explore') return;
            this.refreshProfile();
            // Always try to load a first page on view show.
            this.loadMore();
        },

        async refreshProfile() {
            const store = this.$store.app;
            try {
                const data = await window.searchAPI.fetchExploreProfile();
                store.explore.profileSummary = data?.profile_summary || null;
            } catch (error) {
                store.explore.error = error?.message || 'Could not load explore profile';
            }
        },

        async loadMore() {
            const store = this.$store.app;
            if (store.explore.isLoadingPage || !store.explore.hasMore) return false;

            const requestId = ++store.explore.pageRequestId;
            store.explore.isLoadingPage = true;
            store.explore.error = '';

            try {
                const data = await window.searchAPI.fetchExploreFeed({
                    cursor: store.explore.nextCursor,
                    pageSize: window.ResearchAgent.exploreDefaults.pageSize,
                });
                if (requestId !== store.explore.pageRequestId) return false;

                const incoming = Array.isArray(data?.papers) ? data.papers : [];
                const seen = store.explore.seenIds;
                const newPapers = [];
                for (const paper of incoming) {
                    const key = paper.external_id || paper.url || paper.title;
                    if (!key || seen[key]) continue;
                    seen[key] = true;
                    newPapers.push(paper);
                }

                store.explore.papers = [...store.explore.papers, ...newPapers];
                store.explore.nextCursor = Number.isFinite(data?.next_cursor)
                    ? data.next_cursor
                    : store.explore.nextCursor;
                store.explore.hasMore = data?.has_more === true;
                if (data?.profile_summary) {
                    store.explore.profileSummary = data.profile_summary;
                }
                if (
                    store.explore.papers.length === 0 &&
                    data?.has_more !== true &&
                    !this.diagnostics
                ) {
                    await this.loadDiagnostics();
                }
                return true;
            } catch (error) {
                if (requestId === store.explore.pageRequestId) {
                    store.explore.error = error?.message || 'Could not load more recommendations';
                }
                return false;
            } finally {
                if (requestId === store.explore.pageRequestId) {
                    store.explore.isLoadingPage = false;
                }
            }
        },

        async loadDiagnostics() {
            try {
                this.diagnostics = await window.searchAPI.fetchExploreDiagnostics();
            } catch (e) {
                this.diagnostics = { notes: ['Diagnostics endpoint failed: ' + (e?.message || e)] };
            }
        },

        async recordInteraction(paper, kind) {
            if (!paper?.external_id || !kind) return;
            const store = this.$store.app;
            try {
                await window.searchAPI.recordExploreInteractions([
                    { external_id: paper.external_id, kind },
                ]);
            } catch (e) {
                // Best-effort — UI continues even on failure.
            }
            if (kind === 'hide' || kind === 'dislike') {
                store.explore.papers = store.explore.papers.filter(
                    (p) => p.external_id !== paper.external_id
                );
            }
            if (kind === 'open' && paper.url) {
                window.open(paper.url, '_blank', 'noopener,noreferrer');
            }
        },

        topTopicsList() {
            const summary = this.$store.app.explore.profileSummary;
            if (!summary || !Array.isArray(summary.top_topics)) return '';
            return summary.top_topics.slice(0, 3).join(' · ');
        },
    };
};
```

- [ ] **Step 2: Drop `explore.coldStart` from the store**

In `/home/jyoti/Documents/code/research-agent/frontend/js/alpine/stores/appStore.js`, find the `explore: { ... }` initial-state object (around line 265-275) and remove the `coldStart: false` line. Find `resetExplore()` and `resetExplorePapers()` (around line 377-397) and remove any line that resets or sets `coldStart`.

The whole `explore` block should now look like:

```javascript
        explore: {
            papers: [],
            seenIds: {},
            nextCursor: 0,
            hasMore: true,
            isLoadingPage: false,
            error: '',
            pageRequestId: 0,
            profileSummary: null,
        },
```

And `resetExplore`:

```javascript
        resetExplore() {
            this.explore = {
                papers: [],
                seenIds: {},
                nextCursor: 0,
                hasMore: true,
                isLoadingPage: false,
                error: '',
                pageRequestId: 0,
                profileSummary: null,
            };
        },
```

- [ ] **Step 3: Remove the cold-start panel in index.html**

In `/home/jyoti/Documents/code/research-agent/frontend/html/index.html`, find the block starting with `<div x-show="$store.app.explore.coldStart"` (around line 933) and ending with its closing `</div>` (the cold-start onboarding panel — about 18 lines). Delete the whole block.

Also find the header line `<span x-show="$store.app.explore.coldStart">Pick a few topics to get started</span>` (around line 918) and delete it. Find `<span x-show="!$store.app.explore.coldStart" x-text="...">` (around line 917) and change it to drop the `x-show="!$store.app.explore.coldStart"` attribute — it should always render.

Find `<div x-show="!$store.app.explore.coldStart" class="results-list"...>` (around line 955) and remove the `x-show` (replace with nothing — the div renders unconditionally). Apply the same removal to the other `!$store.app.explore.coldStart` x-show attributes on the loading / end / sentinel divs (lines 981, 986, 990, 994).

- [ ] **Step 4: Add the per-card action bar**

Inside the existing `<article class="gap-card-premium" ...>` block in index.html (around line 957-977 — the card template inside the explore feed `x-for`), find the div with `Open ↗` / `PDF` buttons (around lines 969-976). Replace that entire `<div>` with:

```html
                  <div style="display:flex; gap:0.5rem; margin-top:0.25rem; align-items:center; flex-wrap:wrap;">
                    <template x-if="paper.url">
                      <button type="button" class="btn-glass" @click="recordInteraction(paper, 'open')" style="padding:0.4rem 0.8rem; font-size:0.85rem;">Open ↗</button>
                    </template>
                    <template x-if="paper.pdf_url">
                      <a :href="paper.pdf_url" target="_blank" rel="noopener noreferrer" class="btn-glass" style="padding:0.4rem 0.8rem; font-size:0.85rem;">PDF</a>
                    </template>
                    <span style="flex:1;"></span>
                    <button type="button" class="btn-glass" @click="recordInteraction(paper, 'like')" title="More like this" style="padding:0.4rem 0.7rem; font-size:0.9rem;">👍</button>
                    <button type="button" class="btn-glass" @click="recordInteraction(paper, 'dislike')" title="Less like this" style="padding:0.4rem 0.7rem; font-size:0.9rem;">👎</button>
                    <button type="button" class="btn-glass" @click="recordInteraction(paper, 'hide')" title="Hide this" style="padding:0.4rem 0.7rem; font-size:0.9rem;">✕</button>
                  </div>
```

- [ ] **Step 5: Bump asset versions**

In index.html find the line `<script defer src="/js/alpine/components/exploreFeed.js?v=20260514b"></script>` and change to `?v=20260514d`. Find `<script defer src="/js/alpine/stores/appStore.js?v=20260514c"></script>` and change to `?v=20260514d`. Find `<link rel="stylesheet" href="/css/style.css?v=20260514c" />` and change to `?v=20260514d` (no CSS change needed but bumping keeps cache aligned).

- [ ] **Step 6: JS syntax check**

Run: `cd /home/jyoti/Documents/code/research-agent && node --check frontend/js/alpine/components/exploreFeed.js && node --check frontend/js/alpine/stores/appStore.js && echo JS_OK`
Expected: `JS_OK`.

- [ ] **Step 7: Commit**

```bash
git add frontend/js/alpine/components/exploreFeed.js frontend/js/alpine/stores/appStore.js frontend/html/index.html
git commit -m "feat(explore-ui): drop cold-start gate, always load, per-card actions"
```

---

## Task 8: `recordExploreInteractions` API helper

**Files:**
- Modify: `frontend/js/search.js`

- [ ] **Step 1: Add the function**

Open `/home/jyoti/Documents/code/research-agent/frontend/js/search.js`. After `fetchExploreDiagnostics` (around lines 134-139), add:

```javascript
async function recordExploreInteractions(events) {
    if (!Array.isArray(events) || events.length === 0) {
        return { recorded: 0 };
    }
    const response = await authenticatedFetch(`${BASE_URL}/explore/interactions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ events }),
    });
    return await parseResponse(response, "Could not record interactions");
}
```

Find the `window.searchAPI = { ... }` export (around line 195+) and add `recordExploreInteractions,` next to `fetchExploreDiagnostics,`.

- [ ] **Step 2: Syntax check**

Run: `cd /home/jyoti/Documents/code/research-agent && node --check frontend/js/search.js && echo OK`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/js/search.js
git commit -m "feat(explore-ui): add recordExploreInteractions API helper"
```

---

## Task 9: Re-export the new public surface

**Files:**
- Modify: `app/services/recommendations/__init__.py`

- [ ] **Step 1: Re-export entry points**

Replace the empty contents of `/home/jyoti/Documents/code/research-agent/app/services/recommendations/__init__.py` with:

```python
"""Public surface for the explore recommendation service.

Routes and tests should import from this module rather than reaching into
the internal submodules. Internal cross-module helpers (build_reason,
hydrate_components, etc.) are not re-exported on purpose.
"""
from app.services.recommendations.interactions import (
    INTERACTION_WEIGHTS,
    record_interaction,
)
from app.services.recommendations.pipeline import (
    ColdStartRequired,
    DEFAULT_PAGE_SIZE,
    FeedPage,
    get_feed_page,
)
from app.services.recommendations.popular import rank_popular
from app.services.recommendations.profile_builder import (
    invalidate,
    load_profile,
    set_seed_topics,
)

__all__ = [
    "ColdStartRequired",
    "DEFAULT_PAGE_SIZE",
    "FeedPage",
    "INTERACTION_WEIGHTS",
    "get_feed_page",
    "invalidate",
    "load_profile",
    "rank_popular",
    "record_interaction",
    "set_seed_topics",
]
```

- [ ] **Step 2: Confirm imports resolve**

Run: `cd /home/jyoti/Documents/code/research-agent && .venv/bin/python -c "from app.services.recommendations import get_feed_page, rank_popular, record_interaction, INTERACTION_WEIGHTS; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: All tests still green**

Run: `.venv/bin/pytest tests/ -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add app/services/recommendations/__init__.py
git commit -m "refactor(recs): re-export the explore service public surface"
```

---

## Task 10: E2E smoke — no onboarding gate

**Files:**
- Modify: `tests/e2e/explore.spec.js`

- [ ] **Step 1: Replace the spec with a no-onboarding assertion**

Replace the contents of `/home/jyoti/Documents/code/research-agent/tests/e2e/explore.spec.js` with:

```javascript
const { test, expect } = require("@playwright/test");

test.describe("explore feed", () => {
  test("first visit shows the feed directly, no onboarding form", async ({ page }) => {
    await page.goto("/workspace/explore");

    // The old cold-start onboarding heading must NOT appear.
    await expect(page.getByText(/Tell us what you're into/i)).toHaveCount(0, {
      timeout: 5_000,
    });

    // The page title / heading should render either way.
    await expect(async () => {
      const heading = await page.locator("h2.results-query-title").innerText();
      expect(heading.length).toBeGreaterThan(0);
    }).toPass({ timeout: 15_000 });

    // We expect either a list of papers OR the diagnostics empty-state.
    // Both are acceptable "first visit works" outcomes.
    const hasPapers = await page
      .locator("article.gap-card-premium")
      .first()
      .isVisible()
      .catch(() => false);
    const emptyState = await page
      .getByText("No recommendations yet.")
      .isVisible()
      .catch(() => false);
    expect(hasPapers || emptyState).toBe(true);
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add tests/e2e/explore.spec.js
git commit -m "test(e2e): assert /explore renders without an onboarding gate"
```

---

## Self-Review

**1. Spec coverage:**
- User requirement "show me anything first" → Task 5 (popular fallback) + Task 3 (popular ranker) + Task 5's empty-corpus default-topic branch.
- User requirement "adapt to my preferences" → Task 2 (interactions service) + Task 4 (profile builder consumes signals) + Task 6 (`/explore/interactions` endpoint) + Task 7 (per-card buttons) + Task 8 (frontend POST helper).
- User requirement "no onboarding gate" → Task 6 (drop 409) + Task 7 (delete cold-start panel) + Task 10 (regression test).

**2. Placeholder scan:** All code blocks contain actual content. No `TBD`, `TODO`, "fill in details", or "similar to" cross-references.

**3. Type / name consistency:**
- `INTERACTION_WEIGHTS` defined in Task 2, imported in Task 4, referenced in Task 6's validator, re-exported in Task 9. ✓
- `record_interaction(username, external_id, kind)` signature defined in Task 2, used in Task 6. ✓
- `rank_popular(seen_paper_ids, page_size)` signature defined in Task 3, used in Task 5. ✓
- `fetch_interaction_signals(username) -> list[InteractionSignal]` defined in Task 2, called in Task 4. ✓
- `recordExploreInteractions(events)` defined in Task 8, called from `recordInteraction` in Task 7. ✓ (Task 7 lists Task 8 as a sibling, but the call works because Alpine runs after both scripts load — index.html script order is preserved.)
- `ColdStartRequired` kept exported but no longer raised — confirmed in Tasks 5 and 6. ✓

**4. Behavior changes worth flagging:**
- `/explore/feed` no longer returns 409 for any user. Existing clients that branch on `cold_start_required` need an update (only the in-repo `exploreFeed.js` did; it's removed in Task 7).
- `paper_interactions` is a new collection — operators on Atlas should be aware (no manual migration required; it's created lazily on first write).
- Profile vector now updates on every like/dislike/hide. The existing `dirty` flag mechanism in `profile_builder.invalidate` is reused (Task 6 calls it), so no extra plumbing needed.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-14-reels-style-explore.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
