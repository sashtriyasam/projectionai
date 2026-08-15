"""Tests for the CLI entry point flags (--version, --no-splash).

``main`` is exercised with the Qt/IO-heavy steps stubbed at their
source modules so flag parsing and the ``run_app`` call contract can
be asserted without launching the shell.
"""

from __future__ import annotations

from typing import Any

import pytest

from projectionai import __version__
from projectionai.main import main


class _Recorder:
    """Records the last run_app call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        config: Any,
        project_path: str | None,
        show_splash: bool,
    ) -> int:
        self.calls.append(
            {
                "config": config,
                "project_path": project_path,
                "show_splash": show_splash,
            }
        )
        return 0


@pytest.fixture
def stub_app(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Stub config/logging/hooks/run_app; return the run_app recorder."""
    recorder = _Recorder()
    monkeypatch.setattr(
        "projectionai.core.config.load_config", lambda _path=None: object()
    )
    monkeypatch.setattr(
        "projectionai.core.logging.configure_logging", lambda _config: None
    )
    monkeypatch.setattr(
        "projectionai.ui.dialogs.error_dialog.install_exception_hooks",
        lambda: None,
    )
    monkeypatch.setattr("projectionai.app.run_app", recorder)
    return recorder


class TestVersionFlag:
    def test_prints_version_and_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["--version"])
        out = capsys.readouterr().out
        assert code == 0
        assert f"ProjectionAI v{__version__}" in out


class TestSplashFlag:
    def test_splash_enabled_by_default(self, stub_app: _Recorder) -> None:
        main([])
        assert stub_app.calls[-1]["show_splash"] is True

    def test_no_splash_disables_splash(self, stub_app: _Recorder) -> None:
        main(["--no-splash"])
        assert stub_app.calls[-1]["show_splash"] is False

    def test_project_path_passed_through(self, stub_app: _Recorder) -> None:
        main(["demo.projectionai"])
        assert stub_app.calls[-1]["project_path"] == "demo.projectionai"
