"""Tests for TimelineModel BPM/frame-rate separation.

BPM (musical tempo) is independent state from the frame rate: setting
``bpm`` must never affect ``fps`` and vice versa, and the model notifies
observers on either change.
"""

from __future__ import annotations

import pytest

from projectionai.ui.viewmodels.timeline_model import TimelineModel


def _subscribe(model: TimelineModel) -> list[int]:
    calls: list[int] = []

    def _handler() -> None:
        calls.append(1)

    model.subscribe(_handler)
    return calls


def test_bpm_default_is_120() -> None:
    assert TimelineModel().bpm == 120.0


def test_fps_default_is_30() -> None:
    assert TimelineModel().fps == 30.0


def test_bpm_setter_notifies() -> None:
    model = TimelineModel()
    calls = _subscribe(model)
    model.bpm = 140.0
    assert model.bpm == 140.0
    assert len(calls) == 1


def test_fps_setter_notifies() -> None:
    model = TimelineModel()
    calls = _subscribe(model)
    model.fps = 25.0
    assert model.fps == 25.0
    assert len(calls) == 1


def test_bpm_and_fps_are_independent() -> None:
    model = TimelineModel()
    model.bpm = 140.0
    assert model.fps == 30.0  # frame rate untouched by tempo
    model.fps = 25.0
    assert model.bpm == 140.0  # tempo untouched by frame rate


def test_bpm_rejects_non_positive() -> None:
    model = TimelineModel()
    with pytest.raises(ValueError, match="bpm"):
        model.bpm = 0.0
    with pytest.raises(ValueError, match="bpm"):
        model.bpm = -10.0
    assert model.bpm == 120.0


def test_custom_bpm_constructor() -> None:
    model = TimelineModel(fps=24.0, bpm=128.0)
    assert model.fps == 24.0
    assert model.bpm == 128.0


def test_constructor_rejects_non_positive_bpm() -> None:
    with pytest.raises(ValueError, match="bpm"):
        TimelineModel(bpm=0.0)
    with pytest.raises(ValueError, match="bpm"):
        TimelineModel(bpm=-10.0)


def test_constructor_rejects_non_positive_fps() -> None:
    with pytest.raises(ValueError, match="fps"):
        TimelineModel(fps=0.0)
    with pytest.raises(ValueError, match="fps"):
        TimelineModel(fps=-10.0)


def test_constructor_rejects_non_finite_fps() -> None:
    with pytest.raises(ValueError, match="fps"):
        TimelineModel(fps=float("nan"))
    with pytest.raises(ValueError, match="fps"):
        TimelineModel(fps=float("inf"))


def test_fps_setter_rejects_non_positive_and_non_finite() -> None:
    model = TimelineModel()
    for bad in (0.0, -10.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="fps"):
            model.fps = bad
    assert model.fps == 30.0


def test_to_dict_includes_bpm() -> None:
    model = TimelineModel(bpm=128.0)
    assert model.to_dict()["bpm"] == 128.0
    assert model.to_dict()["fps"] == 30.0
