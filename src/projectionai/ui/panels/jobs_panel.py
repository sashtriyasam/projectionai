"""JobsPanel — background job queue (left dock).

Job rows show name, status, and a live progress bar with a per-row
cancel button. Progress updates asynchronously, so the panel re-renders
on every view-model notification (the main window also polls on a
timer).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from projectionai.managers.job_manager import JobInfo, JobStatus
from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_action_button, make_section_header
from projectionai.ui.theme import (
    ACCENT,
    LIVE_RED,
    OK_GREEN,
    TEXT_DIM,
    TEXT_FAINT,
)

_USER_ROLE = int(Qt.ItemDataRole.UserRole)
_STATUS_ROLE = int(Qt.ItemDataRole.UserRole) + 1

_STATUS_COLORS = {
    JobStatus.PENDING: TEXT_FAINT,
    JobStatus.RUNNING: ACCENT,
    JobStatus.COMPLETED: OK_GREEN,
    JobStatus.FAILED: LIVE_RED,
    JobStatus.CANCELLED: TEXT_DIM,
}


class JobsPanel(ViewModelPanel):
    """Jobs dock panel: queue with progress bars and cancellation."""

    panel_id = "jobs"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("jobsPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Header + action row -----------------------------------------------
        root.addWidget(make_section_header("JOBS", self._cancel_all))
        actions = QHBoxLayout()
        actions.setContentsMargins(4, 4, 4, 4)
        actions.setSpacing(4)
        self.count_label = QLabel()
        self.count_label.setObjectName("propValueLabel")
        actions.addWidget(self.count_label)
        actions.addStretch(1)
        actions.addWidget(make_action_button("Cancel All", self._cancel_all))
        root.addLayout(actions)

        # -- Job list ------------------------------------------------------------
        self.job_list = QListWidget()
        self.job_list.setObjectName("jobList")
        self.job_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        root.addWidget(self.job_list, stretch=1)

    # -- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        """Render the job rows from the view model.

        Reuses existing row widgets when the job set (job ids and
        statuses) is unchanged, updating progress and status text in
        place — preserving selection and avoiding widget allocation on
        every poll tick. The list is rebuilt only when jobs are added,
        removed, or change status.
        """
        if self._refreshing:
            return
        self._refreshing = True
        try:
            vm = self._viewmodel
            if vm is None:
                self.job_list.clear()
                self.count_label.setText("")
                return
            jobs = vm.jobs()
            self.count_label.setText(
                f"{vm.running_count} running · {vm.pending_count} queued"
            )
            current: list[tuple[Any, Any]] = []
            for i in range(self.job_list.count()):
                item = self.job_list.item(i)
                assert item is not None
                current.append((item.data(_USER_ROLE), item.data(_STATUS_ROLE)))
            updated = [(job.job_id, job.status) for job in jobs]
            if current == updated:
                for index, job in enumerate(jobs):
                    item = self.job_list.item(index)
                    assert item is not None
                    self._update_row(item, job)
                return
            self.job_list.clear()
            for job in jobs:
                item, row = self._make_row(job)
                self.job_list.addItem(item)
                self.job_list.setItemWidget(item, row)
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Empty the job list."""
        self.job_list.clear()
        self.count_label.setText("")

    # -- Row builder -----------------------------------------------------------

    def _make_row(self, job: JobInfo) -> tuple[QListWidgetItem, QWidget]:
        item = QListWidgetItem()
        item.setData(_USER_ROLE, job.job_id)
        item.setData(_STATUS_ROLE, job.status)

        row = QWidget()
        row.setObjectName("jobRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        name_label = QLabel(job.name)
        name_label.setObjectName("propLabel")
        status_text = job.status_text or job.status.value.title()
        status_label = QLabel(status_text)
        status_label.setObjectName("propValueLabel")
        color = _STATUS_COLORS.get(job.status, TEXT_FAINT)
        status_label.setStyleSheet(f"color: {color};")
        text_col.addWidget(name_label)
        text_col.addWidget(status_label)
        layout.addLayout(text_col, stretch=1)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(int(job.progress * 100))
        progress.setFixedWidth(80)
        layout.addWidget(progress)

        if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
            cancel_btn = QPushButton("✕")
            cancel_btn.setObjectName("sectionActionButton")
            cancel_btn.setFixedWidth(24)
            cancel_btn.setToolTip("Cancel job")
            cancel_btn.clicked.connect(lambda: self._cancel_job(job.job_id))
            layout.addWidget(cancel_btn)

        item.setSizeHint(row.sizeHint())
        return item, row

    def _update_row(self, item: QListWidgetItem, job: JobInfo) -> None:
        """Refresh an existing row's progress bar and status label in place."""
        row = self.job_list.itemWidget(item)
        if row is None:
            return
        progress = row.findChild(QProgressBar)
        if progress is not None:
            progress.setValue(int(job.progress * 100))
        status_label = row.findChild(QLabel, "propValueLabel")
        if status_label is not None:
            status_text = job.status_text or job.status.value.title()
            status_label.setText(status_text)
            status_label.setStyleSheet(
                f"color: {_STATUS_COLORS.get(job.status, TEXT_FAINT)};"
            )

    # -- Interactions -----------------------------------------------------------

    def _cancel_job(self, job_id: str) -> None:
        if self._viewmodel is not None:
            self._viewmodel.cancel(job_id)

    def _cancel_all(self) -> None:
        if self._viewmodel is not None:
            self._viewmodel.cancel_all()
