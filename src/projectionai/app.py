"""Application bootstrap and lifecycle.

Creates and wires all managers, then starts the Qt event loop.
Managers are created in dependency-safe order and exposed via
the ``ManagerRegistry``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication, QSplashScreen, QWidget

import anyio
from platformdirs import user_data_dir

from projectionai import __version__
from projectionai.calibration import CalibrationManager
from projectionai.core.config import AppConfig
from projectionai.core.events import EventBus
from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.display_validator import DisplayValidator
from projectionai.hardware.display_watcher import DisplayWatcher
from projectionai.hardware.hardware_manager import HardwareManager
from projectionai.hardware.output_manager import OutputManager
from projectionai.managers import ManagerRegistry
from projectionai.managers.asset_manager import AssetManager
from projectionai.managers.camera_manager import CameraManager
from projectionai.managers.command_manager import CommandManager
from projectionai.managers.job_manager import JobManager
from projectionai.managers.plugin_manager import PluginManager
from projectionai.managers.project_manager import ProjectManager
from projectionai.managers.scene_manager import SceneManager
from projectionai.managers.settings_manager import SettingsManager
from projectionai.managers.workspace_manager import WorkspaceManager

_logger = logging.getLogger(__name__)


class _Shutdownable(Protocol):
    """Minimal lifecycle protocol for infrastructure services."""

    async def shutdown(self) -> None: ...


class Application:
    """Top-level application container.

    Owns the event bus, all managers (via ``ManagerRegistry``), and
    top-level services. Uses dependency injection to wire components.
    """

    def __init__(
        self,
        config: AppConfig,
        camera_manager: CameraManager | None = None,
        job_manager: JobManager | None = None,
        hardware_manager: HardwareManager | None = None,
    ) -> None:
        self._config: AppConfig = config
        self._event_bus: EventBus = EventBus()
        self._registry: ManagerRegistry = ManagerRegistry(self._event_bus)
        self._managers_initialized: bool = False
        self._data_dir: Path | None = None

        # Injectable managers — used by tests; None = construct in initialize()
        self._camera_manager: CameraManager | None = camera_manager
        self._job_manager: JobManager | None = job_manager
        self._hardware_manager: HardwareManager | None = hardware_manager

        # Services — lazy-initialized after managers
        self._ai_service: _Shutdownable | None = None
        self._vision_pipeline: _Shutdownable | None = None
        self._renderer: _Shutdownable | None = None
        self._storage: _Shutdownable | None = None
        self._calibrator: _Shutdownable | None = None

    # -- Core properties ----------------------------------------------------

    def _get_data_dir(self) -> Path:
        """Return the resolved application data directory.

        Uses ``self._config.data_dir`` when explicitly configured; otherwise
        falls back to the platform-appropriate user data directory (same
        resolution as :class:`SQLiteStorageService`).
        """
        if self._data_dir is None:
            self._data_dir = Path(
                self._config.data_dir
                if self._config.data_dir
                else user_data_dir("projectionai", ensure_exists=True)
            )
        return self._data_dir

    @property
    def config(self) -> AppConfig:
        """Return the application configuration."""
        return self._config

    @property
    def event_bus(self) -> EventBus:
        """Return the shared event bus."""
        return self._event_bus

    @property
    def managers(self) -> ManagerRegistry:
        """Return the manager registry."""
        return self._registry

    @property
    def settings(self) -> SettingsManager:
        """Shortcut to the settings manager."""
        return self._registry.get_typed("settings", SettingsManager)

    @property
    def plugins(self) -> PluginManager:
        """Shortcut to the plugin manager."""
        return self._registry.get_typed("plugins", PluginManager)

    @property
    def scenes(self) -> SceneManager:
        """Shortcut to the scene manager."""
        return self._registry.get_typed("scenes", SceneManager)

    @property
    def assets(self) -> AssetManager:
        """Shortcut to the asset manager."""
        return self._registry.get_typed("assets", AssetManager)

    @property
    def commands(self) -> CommandManager:
        """Shortcut to the command manager."""
        return self._registry.get_typed("commands", CommandManager)

    @property
    def cameras(self) -> CameraManager:
        """Shortcut to the camera manager."""
        return self._registry.get_typed("cameras", CameraManager)

    @property
    def jobs(self) -> JobManager:
        """Shortcut to the job manager."""
        return self._registry.get_typed("jobs", JobManager)

    @property
    def project(self) -> ProjectManager:
        """Shortcut to the project manager."""
        return self._registry.get_typed("project", ProjectManager)

    @property
    def workspace(self) -> WorkspaceManager:
        """Shortcut to the workspace manager."""
        return self._registry.get_typed("workspace", WorkspaceManager)

    @property
    def calibration(self) -> CalibrationManager:
        """Shortcut to the calibration manager."""
        return self._registry.get_typed("calibration", CalibrationManager)

    @property
    def hardware(self) -> HardwareManager:
        """Shortcut to the hardware manager."""
        return self._registry.get_typed("hardware", HardwareManager)

    # -- Lifecycle ----------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize all managers and subsystems.

        Order:
        1. Event bus (always ready)
        2. Settings + Plugin (no dependencies)
        3. Command + Job (depend on event bus only)
        4. Scene + Asset (domain managers)
        5. Project + Workspace (top-level managers)
        6. Infrastructure services (storage, AI, vision, renderer, calibrator)
        """
        _logger.info(
            "Initializing ProjectionAI v%s",
            __version__,
        )

        # -- Create all managers --------------------------------------------

        data_dir = self._get_data_dir()
        settings_mgr = SettingsManager(
            self._event_bus,
            settings_path=data_dir / "settings.json",
        )
        plugin_mgr = PluginManager(
            self._event_bus,
            plugin_dirs=[data_dir / "plugins"],
        )
        command_mgr = CommandManager(self._event_bus)
        job_mgr = self._job_manager or JobManager(self._event_bus)
        camera_mgr = self._camera_manager or CameraManager(
            self._event_bus,
            job_manager=job_mgr,
            provider_name=self._config.camera_provider,
        )
        scene_mgr = SceneManager(self._event_bus)
        asset_mgr = AssetManager(self._event_bus)
        project_mgr = ProjectManager(
            self._event_bus,
            recent_projects_path=data_dir / "recent_projects.json",
        )
        workspace_mgr = WorkspaceManager(
            self._event_bus,
            workspace_path=data_dir / "workspace.json",
        )
        calibration_mgr = CalibrationManager(
            self._event_bus,
            camera_manager=camera_mgr,
            job_manager=job_mgr,
        )
        calibration_mgr.data_dir = data_dir / "calibration"

        if self._hardware_manager is None:
            display_mgr = DisplayManager(self._event_bus)
            watcher = DisplayWatcher(
                self._event_bus,
                display_manager=display_mgr,
                poll_interval_s=1.0,
            )
            validator = DisplayValidator()
            output_mgr = OutputManager(
                self._event_bus,
                display_manager=display_mgr,
                validator=validator,
                renderer_ready_provider=lambda: self._renderer is not None,
            )
            hardware_mgr = HardwareManager(
                self._event_bus,
                display_manager=display_mgr,
                watcher=watcher,
                output_manager=output_mgr,
                validator=validator,
            )
        else:
            hardware_mgr = self._hardware_manager

        # -- Register in dependency-safe order ------------------------------

        self._registry.add("settings", settings_mgr)
        self._registry.add("plugins", plugin_mgr)
        self._registry.add("commands", command_mgr)
        self._registry.add("cameras", camera_mgr)
        self._registry.add("jobs", job_mgr)
        self._registry.add("scenes", scene_mgr)
        self._registry.add("assets", asset_mgr)
        self._registry.add("project", project_mgr)
        self._registry.add("workspace", workspace_mgr)
        self._registry.add("calibration", calibration_mgr)
        self._registry.add("hardware", hardware_mgr)

        # -- Initialize all managers ----------------------------------------

        await self._registry.initialize_all()
        self._managers_initialized = True

        # -- Initialize infrastructure services -----------------------------

        await self._init_storage()
        await self._init_ai_service()
        await self._init_vision_pipeline()
        await self._init_renderer()
        await self._init_calibrator()

        _logger.info("Application initialized successfully")

    async def _init_storage(self) -> None:
        """Initialize the storage/persistence layer.

        A failure here is fatal — the application cannot persist
        projects, settings, or workspace state without storage.
        """
        try:
            from projectionai.infrastructure.persistence.database import (
                SQLiteStorageService,
            )

            storage = SQLiteStorageService(self._config)
            await storage.initialize()
            self._storage = storage
        except Exception as exc:
            _logger.critical(
                "Storage initialization failed — cannot persist data: %s",
                exc,
            )
            raise RuntimeError("Storage backend unavailable") from exc

    async def _init_ai_service(self) -> None:
        """Initialize the AI service using the configured provider."""
        try:
            from projectionai.services.ai import AIService

            provider_name = self._config.ai_provider
            instances = self.plugins.get_instances_by_capability("llm_provider")
            provider = next(
                (p for p in instances if getattr(p, "name", "") == provider_name),
                None,
            )
            if provider is not None:
                ai = AIService(provider)
                await ai.initialize()
                self._ai_service = ai
            else:
                _logger.info("No AI provider plugin loaded for %r", provider_name)
        except Exception as exc:
            _logger.warning(
                "AI service (%s) unavailable — proceeding without AI: %s",
                self._config.ai_provider,
                exc,
            )

    async def _init_vision_pipeline(self) -> None:
        """Initialize the vision pipeline."""
        try:
            from projectionai.infrastructure.vision.opencv_pipeline import (
                OpenCVPipeline,
            )

            vision = OpenCVPipeline()
            await vision.initialize()
            self._vision_pipeline = vision
        except Exception as exc:
            _logger.warning(
                "Vision pipeline unavailable — scanning disabled: %s",
                exc,
            )

    async def _init_renderer(self) -> None:
        """Initialize the renderer."""
        try:
            from projectionai.infrastructure.renderer.moderngl_renderer import (
                ModernGLRenderer,
            )

            renderer = ModernGLRenderer()
            await renderer.initialize(self._event_bus)
            self._renderer = renderer
        except Exception as exc:
            _logger.warning(
                "Renderer unavailable — 3D preview disabled: %s",
                exc,
            )

    async def _init_calibrator(self) -> None:
        """Initialize the calibrator."""
        try:
            from projectionai.infrastructure.calibration.manual import (
                ManualCalibrator,
            )

            calibrator = ManualCalibrator()
            await calibrator.initialize()
            self._calibrator = calibrator
        except Exception as exc:
            _logger.warning(
                "Calibrator unavailable — manual calibration disabled: %s",
                exc,
            )

    async def shutdown(self) -> None:
        """Shutdown all subsystems in reverse order."""
        _logger.info("Shutting down ProjectionAI")

        # Shutdown infrastructure services
        for service in [
            self._calibrator,
            self._renderer,
            self._vision_pipeline,
            self._ai_service,
            self._storage,
        ]:
            if service is not None and hasattr(service, "shutdown"):
                try:
                    await service.shutdown()
                except Exception:
                    _logger.exception("Error shutting down %s", type(service).__name__)

        # Shutdown all managers
        if self._managers_initialized:
            await self._registry.shutdown_all()

        # Clear event bus
        await self._event_bus.clear()
        _logger.info("Shutdown complete")


def run_app(
    config: AppConfig,
    project_path: str | None = None,
    *,
    show_splash: bool = True,
) -> int:
    """Create the application, initialize, and enter the Qt event loop."""
    from PySide6.QtWidgets import QApplication

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("ProjectionAI")
    qapp.setOrganizationName("ProjectionAI")

    app = Application(config)
    splash = _build_splash(qapp) if show_splash else None
    if splash is not None:
        splash.show()

    async def _pump_qt_events() -> None:
        while True:
            qapp.processEvents()
            await anyio.sleep(0.02)

    async def _async_main() -> int:
        async with anyio.create_task_group() as tg:
            tg.start_soon(_pump_qt_events)
            await app.initialize()
            tg.cancel_scope.cancel()
        return await _run_qt(app, qapp, project_path, splash=splash)

    try:
        return anyio.run(_async_main)
    except RuntimeError:
        _logger.critical("Fatal initialization failure — exiting")
        raise
    except KeyboardInterrupt:
        _logger.info("Interrupted by user")
        return 0


async def _drive_qt_loop(qapp: QApplication, window: QWidget) -> None:
    """Run the Qt event loop cooperatively with the asyncio loop.

    A blocking ``qapp.exec()`` would starve every asyncio task scheduled
    from Qt callbacks via ``run_async`` (see ``ui.widgets.panel_base``):
    the asyncio loop never regains control, so fire-and-forget view-model
    work (camera refresh, open/close, preview) silently never runs. Pump
    Qt events and yield to asyncio until the main window closes.

    ``exec()``-only quit signals (``closingDown()``, ``aboutToQuit``,
    ``lastWindowClosed``) are never emitted by a manual ``processEvents``
    pump, so the loop watches the window's visibility instead — the
    application quits exactly when ``MainWindow.close()`` runs.

    ``processEvents()`` also does not deliver ``DeferredDelete`` events,
    so each iteration explicitly flushes them with
    ``sendPostedEvents(None, QEvent.Type.DeferredDelete)``; otherwise
    objects scheduled via ``deleteLater()`` would leak until process
    exit.
    """
    from PySide6.QtCore import QEvent

    while window.isVisible() and not qapp.closingDown():
        qapp.processEvents()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        await anyio.sleep(0.02)


async def _run_qt(
    app: Application,
    qapp: QApplication,
    project_path: str | None = None,
    *,
    splash: QSplashScreen | None = None,
) -> int:
    """Start the PySide6 event loop with the already-created app."""
    from projectionai.ui.main_window import MainWindow

    window = MainWindow(app)
    window.show()
    if splash is not None:
        splash.finish(window)

    # Load project if specified
    if project_path:
        try:
            project = await app.project.open_project(Path(project_path))
            window.load_project(project)
        except Exception as exc:
            _logger.error("Failed to open project %s: %s", project_path, exc)

    # The Qt loop is the source of truth for application lifetime. If it
    # raises (or is cancelled), application resources must still be
    # released: run shutdown unconditionally, but never let a shutdown
    # failure hide the original Qt-loop failure.
    drive_error: BaseException | None = None
    try:
        await _drive_qt_loop(qapp, window)
    except (Exception, asyncio.CancelledError) as exc:
        drive_error = exc

    try:
        await app.shutdown()
    except Exception:
        _logger.critical("Application shutdown failed", exc_info=True)
        if drive_error is not None:
            raise drive_error
        return 1

    if drive_error is not None:
        raise drive_error
    return 0


def _build_splash(qapp: QApplication) -> QSplashScreen:
    """Build a programmatic dark-brand splash screen (no asset files)."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    from projectionai.ui.theme import ACCENT, TEXT, TEXT_DIM, WINDOW_BG

    size = (520, 300)
    pixmap = QPixmap(*size)
    pixmap.fill(QColor(WINDOW_BG))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    title_font = QFont("Segoe UI", 26, QFont.Weight.DemiBold)
    painter.setFont(title_font)
    painter.setPen(QColor(TEXT))
    painter.drawText(
        QRect(0, 110, size[0], 48), Qt.AlignmentFlag.AlignCenter, "ProjectionAI"
    )

    tag_font = QFont("Segoe UI", 11)
    painter.setFont(tag_font)
    painter.setPen(QColor(ACCENT))
    painter.drawText(
        QRect(0, 160, size[0], 24), Qt.AlignmentFlag.AlignCenter, "Developer Preview"
    )

    version_font = QFont("Segoe UI", 9)
    painter.setFont(version_font)
    painter.setPen(QColor(TEXT_DIM))
    painter.drawText(
        QRect(0, 190, size[0], 20),
        Qt.AlignmentFlag.AlignCenter,
        f"v{__version__}",
    )
    painter.end()

    splash = QSplashScreen(pixmap)
    splash.show()
    qapp.processEvents()
    return splash
