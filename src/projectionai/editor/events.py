"""Editor-specific events, separate from the core event bus."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from projectionai.editor.types import (
    CameraPreset,
    CameraProjection,
    GizmoDomain,
    SelectionMode,
    TransformMode,
    TransformSpace,
)


@dataclass(frozen=True)
class EditorEvent:
    """Base type for all editor events."""


@dataclass(frozen=True)
class SelectionChanged(EditorEvent):
    """Emitted when the selection is modified."""

    object_ids: tuple[str, ...] = ()
    active_id: str | None = None
    mode: SelectionMode = SelectionMode.REPLACE


@dataclass(frozen=True)
class TransformModeChanged(EditorEvent):
    """Emitted when the active transform tool changes."""

    mode: TransformMode = TransformMode.NONE


@dataclass(frozen=True)
class TransformPerformed(EditorEvent):
    """Emitted after a transform operation completes."""

    object_ids: tuple[str, ...] = ()
    mode: TransformMode = TransformMode.TRANSLATE


@dataclass(frozen=True)
class CameraChanged(EditorEvent):
    """Emitted when the viewport camera is modified."""


@dataclass(frozen=True)
class CameraProjectionChanged(EditorEvent):
    """Emitted when the projection mode changes."""

    projection: CameraProjection = CameraProjection.PERSPECTIVE


@dataclass(frozen=True)
class CameraPresetApplied(EditorEvent):
    """Emitted when a camera preset view is applied."""

    preset: CameraPreset = CameraPreset.PERSPECTIVE


@dataclass(frozen=True)
class GizmoDomainChanged(EditorEvent):
    """Emitted when the active gizmo domain changes."""

    domain: GizmoDomain = GizmoDomain.TRANSFORM


@dataclass(frozen=True)
class SnapToggled(EditorEvent):
    """Emitted when snapping is toggled on/off."""

    enabled: bool = False


@dataclass(frozen=True)
class SpaceChanged(EditorEvent):
    """Emitted when the transform space changes."""

    space: TransformSpace = TransformSpace.WORLD


@dataclass(frozen=True)
class EditorPreferenceChanged(EditorEvent):
    """Emitted when an editor preference is modified."""

    key: str = ""
    value: object = None


@dataclass(frozen=True)
class ViewportDirty(EditorEvent):
    """Emitted when the viewport needs a redraw."""


# -- Composite listener helper -----------------------------------------------


class EditorEventBus:
    """Simple typed event bus for editor-local events.

    Separate from the core :class:`EventBus` to keep editor concerns
    isolated from application events. Core events and editor events
    have different lifecycle and serialisation requirements.
    """

    def __init__(self) -> None:
        self._listeners: dict[
            type[EditorEvent], list[Callable[[EditorEvent], None]]
        ] = {}

    def on(
        self, event_type: type[EditorEvent]
    ) -> Callable[[Callable[[EditorEvent], None]], Callable[[EditorEvent], None]]:
        """Decorator to register a listener."""

        def decorator(
            fn: Callable[[EditorEvent], None],
        ) -> Callable[[EditorEvent], None]:
            self._listeners.setdefault(event_type, []).append(fn)
            return fn

        return decorator

    def subscribe(
        self, event_type: type[EditorEvent], listener: Callable[[EditorEvent], None]
    ) -> None:
        """Register a listener explicitly."""
        self._listeners.setdefault(event_type, []).append(listener)

    def unsubscribe(
        self, event_type: type[EditorEvent], listener: Callable[[EditorEvent], None]
    ) -> None:
        """Remove a listener."""
        lst = self._listeners.get(event_type)
        if lst and listener in lst:
            lst.remove(listener)

    def emit(self, event: EditorEvent) -> None:
        """Emit an event synchronously to all listeners."""
        event_type = type(event)
        for listener in self._listeners.get(event_type, []):
            listener(event)

    def clear(self) -> None:
        """Remove all listeners."""
        self._listeners.clear()
