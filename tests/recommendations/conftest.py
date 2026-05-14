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
