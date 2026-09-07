"""评测进度条开关。"""

from __future__ import annotations

import os

from app.eval.progress import eval_progress_enabled, track_cases


def test_track_cases_respects_env_off(monkeypatch) -> None:
    monkeypatch.setenv("FITPILOT_EVAL_PROGRESS", "0")
    items = list(track_cases([1, 2, 3], desc="t"))
    assert items == [1, 2, 3]
    assert eval_progress_enabled() is False


def test_track_cases_force_on(monkeypatch) -> None:
    monkeypatch.setenv("FITPILOT_EVAL_PROGRESS", "1")
    assert eval_progress_enabled() is True
    assert list(track_cases(["a", "b"], desc="t")) == ["a", "b"]


def test_progress_default_without_tty(monkeypatch) -> None:
    monkeypatch.delenv("FITPILOT_EVAL_PROGRESS", raising=False)
    monkeypatch.setattr("app.eval.progress.sys.stderr.isatty", lambda: False)
    assert eval_progress_enabled() is False
    # cleanup for other tests
    os.environ.pop("FITPILOT_EVAL_PROGRESS", None)
