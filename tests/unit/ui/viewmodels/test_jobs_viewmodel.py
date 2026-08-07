"""Regression tests for JobsViewModel.jobs() ordering.

``jobs()`` must keep the running-first status ordering while listing
newest first within each status group, and must not rely on numeric
negation of ``created_at`` (so the sort keeps working if the field
ever becomes a datetime).
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from projectionai.managers.job_manager import JobInfo, JobManager, JobStatus
from projectionai.ui.viewmodels.jobs import JobsViewModel


class _FakeJobManager:
    """Doubles as a JobManager with the surface JobsViewModel consumes."""

    def __init__(self, jobs: list[JobInfo]) -> None:
        self._jobs = {j.job_id: j for j in jobs}

    def list_jobs(self) -> list[JobInfo]:
        return list(self._jobs.values())


def _fake_manager(jobs: list[JobInfo]) -> JobManager:
    return cast(JobManager, _FakeJobManager(jobs))


def _vm(jobs: list[JobInfo]) -> JobsViewModel:
    return JobsViewModel(_fake_manager(jobs))


class TestJobsOrdering:
    def test_running_first_status_order(self) -> None:
        vm = _vm(
            [
                JobInfo(
                    job_id="c", name="c", status=JobStatus.COMPLETED, created_at=1.0
                ),
                JobInfo(job_id="r", name="r", status=JobStatus.RUNNING, created_at=2.0),
                JobInfo(job_id="p", name="p", status=JobStatus.PENDING, created_at=3.0),
                JobInfo(job_id="f", name="f", status=JobStatus.FAILED, created_at=4.0),
            ]
        )
        assert [j.status for j in vm.jobs()] == [
            JobStatus.RUNNING,
            JobStatus.PENDING,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
        ]

    def test_newest_first_within_status(self) -> None:
        vm = _vm(
            [
                JobInfo(
                    job_id="old",
                    name="old",
                    status=JobStatus.COMPLETED,
                    created_at=100.0,
                ),
                JobInfo(
                    job_id="new",
                    name="new",
                    status=JobStatus.COMPLETED,
                    created_at=200.0,
                ),
                JobInfo(
                    job_id="run", name="run", status=JobStatus.RUNNING, created_at=500.0
                ),
            ]
        )
        assert [j.job_id for j in vm.jobs()] == ["run", "new", "old"]

    def test_datetime_created_at_is_supported(self) -> None:
        # Numeric negation of created_at would raise TypeError on a
        # datetime; the sort must be datetime-safe.
        later = cast(float, datetime(2026, 8, 5, 12, 0, 0))
        earlier = cast(float, datetime(2026, 8, 5, 10, 0, 0))
        vm = _vm(
            [
                JobInfo(
                    job_id="older",
                    name="older",
                    status=JobStatus.COMPLETED,
                    created_at=earlier,
                ),
                JobInfo(
                    job_id="newer",
                    name="newer",
                    status=JobStatus.COMPLETED,
                    created_at=later,
                ),
            ]
        )
        assert [j.job_id for j in vm.jobs()] == ["newer", "older"]
