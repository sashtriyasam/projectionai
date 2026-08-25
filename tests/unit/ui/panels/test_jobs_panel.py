"""Regression tests for JobsPanel row reuse.

refresh() must reuse row widgets when the job set (job ids and
statuses) is unchanged — updating progress and status text in place,
preserving selection and avoiding widget allocation on every poll tick.
Any add, removal, or status change rebuilds the list (which also keeps
the per-row cancel button accurate). Rendering happens offscreen
(``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.managers.job_manager import JobInfo, JobStatus
from projectionai.ui.panels.jobs_panel import JobsPanel

# qapp provided by pytest-qt (function-scoped) - custom module fixture removed to avoid leak


def _job(job_id: str, status: JobStatus, progress: float = 0.0) -> JobInfo:
    return JobInfo(job_id=job_id, name=job_id, status=status, progress=progress)


def _status_text(row: Any) -> str:
    """Return the status label text of a job row widget."""
    status_label = row.findChild(QLabel, "propValueLabel")
    assert status_label is not None
    return status_label.text()


class _FakeViewModel:
    """Duck-typed stand-in for JobsViewModel (bind_viewmodel accepts Any)."""

    def __init__(self, jobs: list[JobInfo]) -> None:
        self._jobs = jobs

    def set_jobs(self, jobs: list[JobInfo]) -> None:
        self._jobs = jobs

    def subscribe(self, handler: Any) -> None:
        """No-op: tests drive refresh() directly."""

    def unsubscribe(self, handler: Any) -> None:
        """No-op."""

    def jobs(self) -> list[JobInfo]:
        return self._jobs

    @property
    def running_count(self) -> int:
        return sum(1 for j in self._jobs if j.status is JobStatus.RUNNING)

    @property
    def pending_count(self) -> int:
        return sum(1 for j in self._jobs if j.status is JobStatus.PENDING)

    def cancel(self, job_id: str) -> bool:
        return False

    def cancel_all(self) -> int:
        return 0


class TestRowReuse:
    def test_in_place_update_reuses_row_widgets(self, qapp: QApplication) -> None:
        panel = JobsPanel()
        vm = _FakeViewModel([_job("j1", JobStatus.RUNNING, 0.3)])
        panel.bind_viewmodel(vm)
        first_item = panel.job_list.item(0)
        assert first_item is not None
        first_row = panel.job_list.itemWidget(first_item)
        assert first_row is not None
        # Progress tick: same job, same status — the row must be reused.
        vm.set_jobs([_job("j1", JobStatus.RUNNING, 0.7)])
        panel.refresh()
        assert panel.job_list.count() == 1
        assert panel.job_list.itemWidget(panel.job_list.item(0)) is first_row
        progress = first_row.findChild(QProgressBar)
        assert progress is not None
        assert progress.value() == 70

    def test_in_place_update_refreshes_status_text(self, qapp: QApplication) -> None:
        panel = JobsPanel()
        vm = _FakeViewModel([_job("j1", JobStatus.RUNNING)])
        panel.bind_viewmodel(vm)
        first_row = panel.job_list.itemWidget(panel.job_list.item(0))
        assert first_row is not None
        running = _job("j1", JobStatus.RUNNING)
        running.status_text = "Rendering frame 12"
        vm.set_jobs([running])
        panel.refresh()
        assert _status_text(first_row) == "Rendering frame 12"

    def test_selection_preserved_on_in_place_update(self, qapp: QApplication) -> None:
        panel = JobsPanel()
        vm = _FakeViewModel([_job("j1", JobStatus.RUNNING)])
        panel.bind_viewmodel(vm)
        panel.job_list.setCurrentRow(0)
        assert panel.job_list.currentRow() == 0
        vm.set_jobs([_job("j1", JobStatus.RUNNING, 0.5)])
        panel.refresh()
        assert panel.job_list.currentRow() == 0
        assert panel.job_list.currentItem() is panel.job_list.item(0)

    def test_added_job_rebuilds_rows(self, qapp: QApplication) -> None:
        panel = JobsPanel()
        vm = _FakeViewModel([_job("j1", JobStatus.RUNNING)])
        panel.bind_viewmodel(vm)
        old_row = panel.job_list.itemWidget(panel.job_list.item(0))
        assert old_row is not None
        vm.set_jobs([_job("j1", JobStatus.RUNNING), _job("j2", JobStatus.PENDING)])
        panel.refresh()
        assert panel.job_list.count() == 2
        assert panel.job_list.itemWidget(panel.job_list.item(0)) is not old_row

    def test_removed_job_rebuilds_rows(self, qapp: QApplication) -> None:
        panel = JobsPanel()
        vm = _FakeViewModel(
            [_job("j1", JobStatus.RUNNING), _job("j2", JobStatus.PENDING)]
        )
        panel.bind_viewmodel(vm)
        first_row = panel.job_list.itemWidget(panel.job_list.item(0))
        assert first_row is not None
        vm.set_jobs([_job("j2", JobStatus.PENDING)])
        panel.refresh()
        assert panel.job_list.count() == 1
        remaining_row = panel.job_list.itemWidget(panel.job_list.item(0))
        assert remaining_row is not first_row
        assert _status_text(remaining_row) == "Pending"

    def test_status_transition_rebuilds_and_drops_cancel_button(
        self, qapp: QApplication
    ) -> None:
        panel = JobsPanel()
        vm = _FakeViewModel([_job("j1", JobStatus.RUNNING)])
        panel.bind_viewmodel(vm)
        running_row = panel.job_list.itemWidget(panel.job_list.item(0))
        assert running_row is not None
        assert running_row.findChild(QPushButton) is not None
        vm.set_jobs([_job("j1", JobStatus.COMPLETED, 1.0)])
        panel.refresh()
        done_row = panel.job_list.itemWidget(panel.job_list.item(0))
        assert done_row is not None
        assert done_row.findChild(QPushButton) is None
        progress = done_row.findChild(QProgressBar)
        assert progress is not None
        assert progress.value() == 100
