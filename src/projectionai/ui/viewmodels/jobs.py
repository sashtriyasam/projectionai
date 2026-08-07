"""JobsViewModel — job queue listing and cancellation.

Qt-free. Snapshot methods for the Jobs panels and the status bar;
jobs progress asynchronously, so widgets poll ``revision`` after
``refresh()``.
"""

from __future__ import annotations

from projectionai.managers.job_manager import JobInfo, JobManager, JobStatus
from projectionai.ui.viewmodels.observable import Observable


class JobsViewModel(Observable):
    """Observable job-queue facade."""

    def __init__(self, job_manager: JobManager) -> None:
        super().__init__()
        self._jobs = job_manager

    # -- Listing --------------------------------------------------------------

    @staticmethod
    def _status_rank(status: JobStatus) -> int:
        return {
            JobStatus.RUNNING: 0,
            JobStatus.PENDING: 1,
            JobStatus.COMPLETED: 2,
            JobStatus.FAILED: 3,
            JobStatus.CANCELLED: 4,
        }.get(status, 5)

    def jobs(self) -> list[JobInfo]:
        """All tracked jobs, running first, then newest first."""
        newest_first = sorted(
            self._jobs.list_jobs(),
            key=lambda j: j.created_at,
            reverse=True,
        )
        return sorted(newest_first, key=lambda j: self._status_rank(j.status))

    @property
    def pending_count(self) -> int:
        """Number of queued jobs."""
        return self._jobs.pending_count

    @property
    def running_count(self) -> int:
        """Number of running jobs."""
        return self._jobs.running_count

    @property
    def completed_count(self) -> int:
        """Number of completed jobs."""
        return len(self._jobs.get_jobs_by_status(JobStatus.COMPLETED))

    @property
    def failed_count(self) -> int:
        """Number of failed jobs."""
        return len(self._jobs.get_jobs_by_status(JobStatus.FAILED))

    @property
    def job_count(self) -> int:
        """Total number of tracked jobs."""
        return self._jobs.job_count

    # -- Mutations ------------------------------------------------------------

    def cancel(self, job_id: str) -> bool:
        """Cancel a job; returns True when cancelled."""
        cancelled = self._jobs.cancel(job_id)
        if cancelled:
            self._notify()
        return cancelled

    def cancel_all(self) -> int:
        """Cancel all jobs; returns the number cancelled."""
        count = self._jobs.cancel_all()
        if count:
            self._notify()
        return count

    def refresh(self) -> None:
        """Force a revision bump (call on a poll timer)."""
        self._notify()
