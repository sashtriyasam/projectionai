"""Job model — background task representation.

Jobs are self-contained units of work that run in a background thread
pool. The ``JobManager`` owns the queue and lifecycle. Each job reports
progress through callbacks.

Design decisions:
- ``Job`` is an ABC — concrete jobs override ``execute()``.
- Progress is pushed via ``report_progress()``, not polled.
- Jobs carry their own metadata so the queue UI can display them
  without knowing the concrete type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any
from uuid import uuid4


class JobStatus(StrEnum):
    """Lifecycle states for a job."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(int, Enum):
    """Priority levels. Higher value = higher priority."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


# ---------------------------------------------------------------------------
# Job log entry
# ---------------------------------------------------------------------------


@dataclass
class JobLogEntry:
    """A single log line from a job."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    message: str = ""


# ---------------------------------------------------------------------------
# Progress callback type
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[float, str], None]
LogCallback = Callable[[str, str], None]
StatusCallback = Callable[[JobStatus], None]


# ---------------------------------------------------------------------------
# Job base class
# ---------------------------------------------------------------------------


class Job(ABC):
    """Abstract base for all background jobs.

    Concrete subclasses override ``execute()`` and call
    ``report_progress()`` / ``log()`` during execution.
    """

    def __init__(
        self,
        name: str = "Job",
        priority: JobPriority = JobPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._id: str = uuid4().hex
        self._name: str = name
        self._priority: JobPriority = priority
        self._metadata: dict[str, Any] = metadata or {}

        self._status: JobStatus = JobStatus.QUEUED
        self._progress: float = 0.0
        self._stage: str = "Pending"
        self._error: str | None = None
        self._result: Any = None

        self._logs: list[JobLogEntry] = []
        self._created_at: datetime = datetime.now(UTC)
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._estimated_remaining_ms: float | None = None

        # Callbacks (set by JobManager)
        self._on_progress: ProgressCallback | None = None
        self._on_log: LogCallback | None = None
        self._on_status_change: StatusCallback | None = None
        self._cancel_requested: bool = False

    # -- Properties ---------------------------------------------------------

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> JobPriority:
        return self._priority

    @priority.setter
    def priority(self, value: JobPriority) -> None:
        self._priority = value

    @property
    def status(self) -> JobStatus:
        return self._status

    @property
    def progress(self) -> float:
        return self._progress

    @property
    def stage(self) -> str:
        return self._stage

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def result(self) -> Any:
        return self._result

    @property
    def logs(self) -> list[JobLogEntry]:
        return list(self._logs)

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    @property
    def completed_at(self) -> datetime | None:
        return self._completed_at

    @property
    def estimated_remaining_ms(self) -> float | None:
        return self._estimated_remaining_ms

    @property
    def is_cancel_requested(self) -> bool:
        return self._cancel_requested

    @property
    def duration_ms(self) -> float | None:
        """Return wall-clock duration, or ``None`` if not completed."""
        if self._completed_at is None or self._started_at is None:
            return None
        return (self._completed_at - self._started_at).total_seconds() * 1000

    # ------------------------------------------------------------------
    # Callbacks (called by JobManager)
    # ------------------------------------------------------------------

    def _set_callbacks(
        self,
        on_progress: ProgressCallback,
        on_log: LogCallback,
        on_status_change: StatusCallback,
    ) -> None:
        self._on_progress = on_progress
        self._on_log = on_log
        self._on_status_change = on_status_change

    # ------------------------------------------------------------------
    # Progress reporting
    # ------------------------------------------------------------------

    def report_progress(self, progress: float, stage: str = "") -> None:
        """Update the job progress.

        Args:
            progress: Value between 0.0 and 1.0.
            stage: Description of the current stage.
        """
        self._progress = max(0.0, min(1.0, progress))
        if stage:
            self._stage = stage
        if self._on_progress:
            self._on_progress(self._progress, self._stage)

    def log(self, message: str, level: str = "INFO") -> None:
        """Add a log entry."""
        entry = JobLogEntry(level=level, message=message)
        self._logs.append(entry)
        if self._on_log:
            self._on_log(message, level)

    def request_cancel(self) -> None:
        """Request cancellation. The job should check
        ``is_cancel_requested`` periodically and stop."""
        self._cancel_requested = True

    # ------------------------------------------------------------------
    # Lifecycle (called by JobManager)
    # ------------------------------------------------------------------

    def _set_status(self, status: JobStatus) -> None:
        self._status = status
        if status == JobStatus.RUNNING and self._started_at is None:
            self._started_at = datetime.now(UTC)
        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            self._completed_at = datetime.now(UTC)
        if self._on_status_change:
            self._on_status_change(status)

    # ------------------------------------------------------------------
    # Execution — override in subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(self) -> Any:
        """Execute the job.

        This runs in a background thread. Call ``report_progress()``,
        ``log()``, and check ``is_cancel_requested`` periodically.

        Returns:
            The job result (any picklable value).

        Raises:
            Exception: On failure. The exception is captured and
                the job transitions to ``FAILED``.
        """
        ...

    # ------------------------------------------------------------------
    # Descriptors for UI
    # ------------------------------------------------------------------

    @property
    def type_name(self) -> str:
        """Human-readable job type, shown in the UI."""
        return self.__class__.__name__

    @property
    def icon_name(self) -> str:
        """Icon identifier for the UI."""
        return "job_default"

    def get_summary(self) -> str:
        """One-line summary for the queue list."""
        return f"{self.type_name}: {self._name}"
