"""Typed event bus for decoupled intra-process communication.

Usage::

    bus = EventBus()

    @bus.on(SceneChanged)
    async def handle(event: SceneChanged) -> None:
        ...

    await bus.emit(SceneChanged(scene_id="abc"))

Listeners are async. The event bus supports:
- Weak references to prevent UI memory leaks.
- Once-only listeners.
- Error isolation (a failing listener does not block others).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast, override
from weakref import WeakMethod, ref

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types (marker dataclasses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    """Base type for all events. Subclass and add domain-specific fields."""


# -- Application lifecycle --------------------------------------------------


@dataclass(frozen=True)
class ApplicationStarted(Event):
    """Emitted after the application finishes initializing."""


@dataclass(frozen=True)
class ApplicationShuttingDown(Event):
    """Emitted when the application is about to shut down."""


# -- Project events ---------------------------------------------------------


@dataclass(frozen=True)
class ProjectOpened(Event):
    """Emitted when a project is opened."""

    project_id: str
    path: str


@dataclass(frozen=True)
class ProjectClosed(Event):
    """Emitted when a project is closed."""

    project_id: str


@dataclass(frozen=True)
class ProjectSaved(Event):
    """Emitted when a project is saved."""

    project_id: str
    path: str


@dataclass(frozen=True)
class ProjectModified(Event):
    """Emitted when the project is modified (dirty flag set)."""

    project_id: str


@dataclass(frozen=True)
class ProjectCreated(Event):
    """Emitted when a new project is created."""

    project_id: str
    name: str


# -- Scene events -----------------------------------------------------------


@dataclass(frozen=True)
class SceneChanged(Event):
    """Emitted when the active scene is modified (add/remove/transform)."""

    scene_id: str


@dataclass(frozen=True)
class SceneCreated(Event):
    """Emitted when a new scene is created."""

    scene_id: str
    name: str


@dataclass(frozen=True)
class SceneDeleted(Event):
    """Emitted when a scene is deleted."""

    scene_id: str


@dataclass(frozen=True)
class SceneActivated(Event):
    """Emitted when a different scene becomes the active scene."""

    scene_id: str


@dataclass(frozen=True)
class ObjectAdded(Event):
    """Emitted when a 3D object is added to the scene."""

    scene_id: str
    object_id: str


@dataclass(frozen=True)
class ObjectRemoved(Event):
    """Emitted when a 3D object is removed from the scene."""

    scene_id: str
    object_id: str


@dataclass(frozen=True)
class NodeSelected(Event):
    """Emitted when a node is selected or deselected."""

    scene_id: str
    node_id: str
    selected: bool


@dataclass(frozen=True)
class NodeTransformChanged(Event):
    """Emitted when a node's transform is modified."""

    scene_id: str
    node_id: str


# -- Asset events -----------------------------------------------------------


@dataclass(frozen=True)
class AssetImported(Event):
    """Emitted when an asset is imported into the project."""

    asset_id: str
    asset_type: str
    source_path: str


@dataclass(frozen=True)
class AssetDeleted(Event):
    """Emitted when an asset is deleted."""

    asset_id: str


@dataclass(frozen=True)
class AssetUpdated(Event):
    """Emitted when an asset's metadata or content is updated."""

    asset_id: str


@dataclass(frozen=True)
class AssetDependencyChanged(Event):
    """Emitted when an asset's dependencies change."""

    asset_id: str


# -- Job events -------------------------------------------------------------


@dataclass(frozen=True)
class JobQueued(Event):
    """Emitted when a job is added to the queue."""

    job_id: str
    job_type: str


@dataclass(frozen=True)
class JobStarted(Event):
    """Emitted when a job begins execution."""

    job_id: str


@dataclass(frozen=True)
class JobProgress(Event):
    """Emitted during job execution to report progress (0.0 — 1.0)."""

    job_id: str
    progress: float
    status: str


@dataclass(frozen=True)
class JobCompleted(Event):
    """Emitted when a job finishes successfully."""

    job_id: str


@dataclass(frozen=True)
class JobFailed(Event):
    """Emitted when a job fails."""

    job_id: str
    reason: str


@dataclass(frozen=True)
class JobCancelled(Event):
    """Emitted when a job is cancelled by the user."""

    job_id: str


# -- Command/undo events ----------------------------------------------------


@dataclass(frozen=True)
class CommandExecuted(Event):
    """Emitted after a command is executed."""

    command_id: str
    command_name: str


@dataclass(frozen=True)
class CommandUndone(Event):
    """Emitted after a command is undone."""

    command_id: str
    command_name: str


@dataclass(frozen=True)
class CommandRedone(Event):
    """Emitted after a command is redone."""

    command_id: str
    command_name: str


@dataclass(frozen=True)
class CommandHistoryCleared(Event):
    """Emitted when the undo/redo history is cleared."""


# -- Plugin events ----------------------------------------------------------


@dataclass(frozen=True)
class PluginLoaded(Event):
    """Emitted when a plugin is loaded."""

    plugin_name: str
    capability: str


@dataclass(frozen=True)
class PluginUnloaded(Event):
    """Emitted when a plugin is unloaded."""

    plugin_name: str


@dataclass(frozen=True)
class PluginError(Event):
    """Emitted when a plugin encounters a non-fatal error."""

    plugin_name: str
    error: str


# -- Settings events --------------------------------------------------------


@dataclass(frozen=True)
class SettingsChanged(Event):
    """Emitted when a setting value is changed."""

    category: str
    key: str
    old_value: Any | None = None
    new_value: Any | None = None


# -- Workspace events -------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceLayoutChanged(Event):
    """Emitted when the workspace layout is modified."""


@dataclass(frozen=True)
class WorkspaceSettingsChanged(Event):
    """Emitted when workspace settings are updated."""


# -- Calibration events -----------------------------------------------------


@dataclass(frozen=True)
class CalibrationStarted(Event):
    """Emitted when a calibration process begins."""

    scene_id: str


@dataclass(frozen=True)
class CalibrationProgress(Event):
    """Emitted during calibration to report progress (0.0 — 1.0)."""

    scene_id: str
    progress: float
    status: str


@dataclass(frozen=True)
class CalibrationComplete(Event):
    """Emitted when calibration finishes successfully."""

    scene_id: str


@dataclass(frozen=True)
class CalibrationFailed(Event):
    """Emitted when calibration fails."""

    scene_id: str
    reason: str


# -- Generation events ------------------------------------------------------


@dataclass(frozen=True)
class GenerationStarted(Event):
    """Emitted when content generation begins."""

    job_id: str
    prompt: str


@dataclass(frozen=True)
class GenerationProgress(Event):
    """Emitted during generation to report progress."""

    job_id: str
    progress: float


@dataclass(frozen=True)
class GenerationComplete(Event):
    """Emitted when generation finishes successfully."""

    job_id: str
    output_path: str


@dataclass(frozen=True)
class GenerationFailed(Event):
    """Emitted when generation fails."""

    job_id: str
    reason: str


# -- Warp & Preview events --------------------------------------------------


@dataclass(frozen=True)
class WarpUpdated(Event):
    """Emitted when a warp projection is recalculated."""

    scene_id: str


@dataclass(frozen=True)
class PreviewToggled(Event):
    """Emitted when the preview is toggled on/off."""

    active: bool


# -- Status / Error events --------------------------------------------------


@dataclass(frozen=True)
class ErrorEvent(Event):
    """Emitted when a non-fatal error occurs (UI shows a toast)."""

    source: str
    message: str
    details: str | None = None


@dataclass(frozen=True)
class StatusMessage(Event):
    """Emitted to show a status bar message."""

    message: str
    level: str = "info"  # info, warning, error


# ---------------------------------------------------------------------------
# Listener protocol
# ---------------------------------------------------------------------------

EventHandler = Callable[[Event], Awaitable[None]]


class _WeakListener:
    """Wrapper that holds a weak reference to a listener.

    Uses ``WeakMethod`` for bound-method listeners to allow the
    instance to be garbage-collected independently of the wrapper.
    Falls back to a plain ``ref`` for regular callables.
    """

    __slots__: tuple[str, ...] = ("_hash", "_ref")
    _ref: Any
    _hash: int

    def __init__(self, listener: EventHandler) -> None:
        if inspect.ismethod(listener):
            self._ref = WeakMethod(listener)
            self._hash = hash((id(listener.__self__), id(listener.__func__)))
        else:
            self._ref = ref(listener)
            self._hash = hash(listener)

    def __call__(self, event: Event) -> Awaitable[None]:
        cb = self._ref()
        if cb is not None:
            return cast("Awaitable[None]", cb(event))
        return _noop()

    @property
    def alive(self) -> bool:
        return self._ref() is not None

    @override
    def __hash__(self) -> int:
        return self._hash

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _WeakListener):
            return NotImplemented
        return self._hash == other._hash


async def _noop() -> None:
    pass


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class EventBus:
    """Central event bus. Inject this singleton into components that emit
    or listen to events."""

    def __init__(self) -> None:
        self._listeners: dict[type[Event], set[_WeakListener]] = {}
        self._once_listeners: dict[type[Event], set[_WeakListener]] = {}

    def on(self, event_type: type[Event]) -> Callable[[EventHandler], EventHandler]:
        """Decorator to register an async listener for *event_type*.

        The listener is held by weak reference. If it is a bound method,
        the containing object can be garbage-collected without explicit
        deregistration.
        """

        def decorator(fn: EventHandler) -> EventHandler:
            self._register(event_type, fn, once=False)
            return fn

        return decorator

    def once(self, event_type: type[Event]) -> Callable[[EventHandler], EventHandler]:
        """Decorator variant that removes the listener after the first event."""

        def decorator(fn: EventHandler) -> EventHandler:
            self._register(event_type, fn, once=True)
            return fn

        return decorator

    def _register(
        self, event_type: type[Event], fn: EventHandler, *, once: bool
    ) -> None:
        target = self._once_listeners if once else self._listeners
        target.setdefault(event_type, set()).add(_WeakListener(fn))

    def subscribe(self, event_type: type[Event], listener: EventHandler) -> None:
        """Explicit subscribe (non-decorator form)."""
        self._listeners.setdefault(event_type, set()).add(_WeakListener(listener))

    def unsubscribe(self, event_type: type[Event], listener: EventHandler) -> None:
        """Explicit unsubscribe."""
        lst = self._listeners.get(event_type)
        if lst:
            lst.discard(_WeakListener(listener))

    async def emit(self, event: Event) -> None:
        """Emit an event to all registered listeners.

        Listeners are called concurrently via ``asyncio.gather``.
        A failing listener does not block others — errors are logged.
        """
        event_type = type(event)
        regular = self._alive_listeners(self._listeners.get(event_type, set()))
        once = self._alive_listeners(self._once_listeners.get(event_type, set()))

        if once:
            self._once_listeners[event_type] = set()

        all_listeners = list(regular | once)
        if not all_listeners:
            return

        _logger.debug(
            "Emitting %s to %d listener(s)", event_type.__name__, len(all_listeners)
        )

        results = await asyncio.gather(
            *(listener(event) for listener in all_listeners),
            return_exceptions=True,
        )
        for listener, result in zip(all_listeners, results, strict=True):
            if isinstance(result, Exception):
                _logger.exception(
                    "Listener %r failed handling %s: %s",
                    listener,
                    event_type.__name__,
                    result,
                )

    def _alive_listeners(self, lst: set[_WeakListener]) -> set[_WeakListener]:
        return {wl for wl in lst if wl.alive}

    async def clear(self) -> None:
        """Remove all listeners."""
        self._listeners.clear()
        self._once_listeners.clear()
