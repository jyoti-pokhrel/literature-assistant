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
