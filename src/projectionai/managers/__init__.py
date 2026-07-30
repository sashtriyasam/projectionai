"""Manager layer — application orchestration and state management.

Managers are the bridge between the UI/application layer and the domain/
infrastructure layer. Each manager owns a specific concern:

- ``SettingsManager`` — Typed application settings with persistence.
- ``PluginManager`` — Capability-based plugin lifecycle.
- ``SceneManager`` — Active scene graph management.
- ``AssetManager`` — Asset import, lookup, and dependency tracking.
- ``CommandManager`` — Undo/redo command history.
- ``JobManager`` — Background job queue with progress and cancellation.
- ``ProjectManager`` — Project save/load/open/close.
- ``WorkspaceManager`` — UI layout and panel state persistence.

Managers communicate through the ``EventBus``. Dependencies between
managers are resolved by the ``ManagerRegistry`` and exposed via
properties on the application context.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypeVar

from projectionai.core.errors import ManagerNotInitializedError

if TYPE_CHECKING:
    from projectionai.core.events import EventBus

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base manager
# ---------------------------------------------------------------------------


class Manager(ABC):
    """Base class for all managers.

    Subclasses must implement ``_on_initialize`` and ``_on_shutdown``.
    The public ``initialize`` / ``shutdown`` methods track state and
    prevent double-initialization.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus: EventBus = event_bus
        self._initialized: bool = False
        self._pending_tasks: set[asyncio.Task[None]] = set()

    # -- Public API ---------------------------------------------------------

    @property
    def event_bus(self) -> EventBus:
        """Return the shared event bus instance."""
        return self._event_bus

    @property
    def is_initialized(self) -> bool:
        """Return ``True`` if the manager has been initialized."""
        return self._initialized

    async def initialize(self) -> None:
        """Initialize the manager. Idempotent — safe to call multiple times."""
        if self._initialized:
            return
        _logger.debug("Initializing %s", type(self).__name__)
        self._initialized = True
        try:
            await self._on_initialize()
        except Exception:
            self._initialized = False
            raise
        _logger.info("%s initialized", type(self).__name__)

    async def shutdown(self) -> None:
        """Shut down the manager. Idempotent."""
        if not self._initialized:
            return
        _logger.debug("Shutting down %s", type(self).__name__)
        await self._on_shutdown()
        self._initialized = False
        _logger.info("%s shut down", type(self).__name__)

    def _require_initialized(self) -> None:
        """Guard for operations that need the manager to be initialized."""
        if not self._initialized:
            raise ManagerNotInitializedError(
                f"{type(self).__name__} is not initialized"
            )

    def _emit_nowait(self, event: Any) -> None:
        """Emit an event without awaiting (fire-and-forget).

        The returned task is retained in ``_pending_tasks`` and removed
        via a done callback to prevent garbage-collection issues.
        Logs a debug message when no event loop is available.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _logger.debug("No running event loop — dropping %s", type(event).__name__)
            return

        task = loop.create_task(self._event_bus.emit(event))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    # -- Subclass hooks -----------------------------------------------------

    @abstractmethod
    async def _on_initialize(self) -> None:
        """Subclass-specific initialization logic."""

    @abstractmethod
    async def _on_shutdown(self) -> None:
        """Subclass-specific shutdown logic."""


# ---------------------------------------------------------------------------
# Manager registry
# ---------------------------------------------------------------------------

_M = TypeVar("_M", bound=Manager)


class ManagerRegistry:
    """Holds initialized manager instances and resolves dependencies.

    Usage::

        registry = ManagerRegistry(event_bus)
        registry.add("settings", SettingsManager(event_bus))
        await registry.initialize_all()
        ...
        await registry.shutdown_all()
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus: EventBus = event_bus
        self._managers: dict[str, Manager] = {}
        self._initialized: bool = False

    def add(self, name: str, manager: Manager) -> None:
        """Register a manager instance by name."""
        if name in self._managers:
            _logger.warning("Overriding existing manager: %s", name)
        self._managers[name] = manager

    def get(self, name: str) -> Manager:
        """Return the manager instance for *name*.

        Raises ``KeyError`` if not registered.
        """
        return self._managers[name]

    def get_typed(self, name: str, cls: type[_M]) -> _M:
        """Return and type-narrow a manager instance."""
        mgr = self.get(name)
        if not isinstance(mgr, cls):
            raise TypeError(f"Manager {name!r} is not an instance of {cls.__name__}")
        return mgr

    @property
    def names(self) -> list[str]:
        """Return sorted manager names."""
        return sorted(self._managers)

    @property
    def all(self) -> list[Manager]:
        """Return all manager instances."""
        return list(self._managers.values())

    async def initialize_all(self) -> None:
        """Initialize all registered managers in dependency-safe order."""
        _logger.info("Initializing all managers...")
        for _name, mgr in sorted(self._managers.items(), key=lambda x: x[0]):
            await mgr.initialize()
        self._initialized = True
        _logger.info("All managers initialized")

    async def shutdown_all(self) -> None:
        """Shut down all managers in reverse-alphabetical order."""
        _logger.info("Shutting down all managers...")
        for _name, mgr in reversed(sorted(self._managers.items())):
            await mgr.shutdown()
        self._initialized = False
        _logger.info("All managers shut down")
