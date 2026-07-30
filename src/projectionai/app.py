"""Application bootstrap and lifecycle.

Creates and wires all managers, then starts the Qt event loop.
Managers are created in dependency-safe order and exposed via
the ``ManagerRegistry``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Protocol

import anyio
from platformdirs import user_data_dir

from projectionai import __version__
from projectionai.core.config import AppConfig
from projectionai.core.events import EventBus
from projectionai.managers import ManagerRegistry
from projectionai.managers.asset_manager import AssetManager
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

    def __init__(self, config: AppConfig) -> None:
        self._config: AppConfig = config
        self._event_bus: EventBus = EventBus()
        self._registry: ManagerRegistry = ManagerRegistry(self._event_bus)
        self._managers_initialized: bool = False
        self._data_dir: Path | None = None

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
        job_mgr = JobManager(self._event_bus)
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

        # -- Register in dependency-safe order ------------------------------

        self._registry.add("settings", settings_mgr)
        self._registry.add("plugins", plugin_mgr)
        self._registry.add("commands", command_mgr)
        self._registry.add("jobs", job_mgr)
        self._registry.add("scenes", scene_mgr)
        self._registry.add("assets", asset_mgr)
        self._registry.add("project", project_mgr)
        self._registry.add("workspace", workspace_mgr)

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


def run_app(config: AppConfig, project_path: str | None = None) -> int:
    """Create the application, initialize, and enter the Qt event loop."""
    app = Application(config)

    async def _async_main() -> int:
        await app.initialize()
        return await _run_qt(app, project_path)

    try:
        return anyio.run(_async_main)
    except RuntimeError:
        _logger.critical("Fatal initialization failure — exiting")
        return 1
    except KeyboardInterrupt:
        _logger.info("Interrupted by user")
        return 0


async def _run_qt(app: Application, project_path: str | None = None) -> int:
    """Start the PySide6 event loop."""
    from PySide6.QtWidgets import QApplication

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("ProjectionAI")
    qapp.setOrganizationName("ProjectionAI")

    from projectionai.ui.main_window import MainWindow

    window = MainWindow(app)
    window.show()

    # Load project if specified
    if project_path:
        try:
            project = await app.project.open_project(Path(project_path))
            window.load_project(project)
        except Exception as exc:
            _logger.error("Failed to open project %s: %s", project_path, exc)

    exit_code = qapp.exec()

    await app.shutdown()
    return exit_code
