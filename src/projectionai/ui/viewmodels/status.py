"""StatusViewModel — aggregates shell status for the status bar.

Qt-free. The status bar widget polls ``revision`` on a timer and calls
``refresh()`` to re-read manager state. Performance fields (fps, GPU,
memory) are placeholders updated through ``update_performance`` until
the real renderer is wired in. Hardware fields (displays, projectors,
health) come from the optional hardware provider.
"""

from __future__ import annotations

from collections.abc import Callable

from projectionai.hardware.models import HardwareStatus
from projectionai.managers.job_manager import JobManager
from projectionai.managers.project_manager import ProjectManager
from projectionai.managers.scene_manager import SceneManager
from projectionai.ui.viewmodels.output import OutputViewModel

PollHandler = Callable[[], None]


class StatusViewModel:
    """One-stop status feed for the status bar."""

    def __init__(
        self,
        projects: ProjectManager,
        scenes: SceneManager,
        jobs: JobManager,
        output: OutputViewModel,
        camera_count_provider: Callable[[], int] | None = None,
        hardware_provider: Callable[[], HardwareStatus] | None = None,
    ) -> None:
        self._projects = projects
        self._scenes = scenes
        self._jobs = jobs
        self._output = output
        self._camera_count_provider = camera_count_provider
        self._hardware_provider = hardware_provider
        self._handlers: list[PollHandler] = []
        self._revision: int = 0

        # Placeholder telemetry (future renderer integration).
        self._fps: float = 0.0
        self._gpu_name: str = "GPU —"
        self._memory_mb: int = 0

    # -- Observation ----------------------------------------------------------

    @property
    def revision(self) -> int:
        """Increment on every refresh (poll target)."""
        return self._revision

    def subscribe(self, handler: PollHandler) -> None:
        """Register a callback invoked on every refresh."""
        if handler not in self._handlers:
            self._handlers.append(handler)

    def unsubscribe(self, handler: PollHandler) -> None:
        """Remove a previously registered callback."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def refresh(self) -> None:
        """Pull fresh state from the managers and notify listeners."""
        self._revision += 1
        for handler in list(self._handlers):
            handler()

    # -- Project --------------------------------------------------------------

    @property
    def project_name(self) -> str:
        """Name of the current project, or ``"No Project"``."""
        project = self._projects.current
        return project.name if project is not None else "No Project"

    @property
    def project_dirty(self) -> bool:
        """True when the current project has unsaved changes."""
        return self._projects.is_dirty

    @property
    def active_scene_name(self) -> str:
        """Name of the active scene, or ``"—"``."""
        scene = self._scenes.active_scene
        return scene.name if scene is not None else "—"

    @property
    def scene_count(self) -> int:
        """Number of registered scenes."""
        return self._scenes.scene_count

    # -- Jobs ------------------------------------------------------------------

    @property
    def pending_jobs(self) -> int:
        """Number of queued jobs."""
        return self._jobs.pending_count

    @property
    def running_jobs(self) -> int:
        """Number of running jobs."""
        return self._jobs.running_count

    @property
    def job_summary(self) -> str:
        """Short job summary for the status bar."""
        if self.running_jobs == 0 and self.pending_jobs == 0:
            return "Jobs idle"
        parts = []
        if self.running_jobs:
            parts.append(f"{self.running_jobs} running")
        if self.pending_jobs:
            parts.append(f"{self.pending_jobs} queued")
        return ", ".join(parts)

    # -- Devices ---------------------------------------------------------------

    @property
    def camera_count(self) -> int:
        """Number of detected cameras."""
        if self._camera_count_provider is not None:
            return self._camera_count_provider()
        return 0

    # -- Hardware ----------------------------------------------------------------

    @property
    def hardware_status(self) -> HardwareStatus | None:
        """Aggregated hardware status, when a provider is wired in."""
        if self._hardware_provider is not None:
            return self._hardware_provider()
        return None

    @property
    def display_count(self) -> int:
        """Number of detected displays."""
        status = self.hardware_status
        return status.display_count if status is not None else 0

    @property
    def projector_count(self) -> int:
        """Number of projector-classified displays."""
        status = self.hardware_status
        return status.projector_count if status is not None else 0

    @property
    def hardware_healthy(self) -> bool:
        """True when the hardware layer reports no errors."""
        status = self.hardware_status
        return status.healthy if status is not None else True

    # -- Output ----------------------------------------------------------------

    @property
    def output_label(self) -> str:
        """Live-state label for the status bar."""
        return self._output.label

    @property
    def output_color(self) -> str:
        """Theme color for the current output state."""
        return self._output.color

    @property
    def is_live(self) -> bool:
        """True when the projector shows program content."""
        return self._output.is_live

    # -- Performance (placeholders for the future renderer) --------------------

    @property
    def fps(self) -> float:
        """Last reported preview frame rate."""
        return self._fps

    @property
    def gpu_name(self) -> str:
        """Detected GPU name (placeholder)."""
        return self._gpu_name

    @property
    def memory_mb(self) -> int:
        """Approximate used memory in MB (placeholder)."""
        return self._memory_mb

    def update_performance(self, fps: float, gpu_name: str, memory_mb: int) -> None:
        """Update performance telemetry (future renderer integration)."""
        self._fps = fps
        self._gpu_name = gpu_name
        self._memory_mb = memory_mb
