"""Snap manager — grid, rotation, and scale snapping."""

from __future__ import annotations

from projectionai.editor.events import EditorEventBus, SnapToggled
from projectionai.editor.types import SnapMode


class SnapManager:
    """Configurable snapping for translate / rotate / scale operations.

    Each snap axis has its own increment value. Snapping is applied
    during transform operations to constrain values to fixed intervals.
    """

    def __init__(self, event_bus: EditorEventBus | None = None) -> None:
        self._event_bus = event_bus
        self._enabled: bool = False

        # Snap increments
        self._translation: float = 0.25  # world units
        self._rotation: float = 15.0  # degrees
        self._scale: float = 0.1  # factor

    # -- Properties ---------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        if value != self._enabled:
            self._enabled = value
            if self._event_bus:
                self._event_bus.emit(SnapToggled(enabled=value))

    @property
    def translation(self) -> float:
        """Snap increment for translation in world units."""
        return self._translation

    @translation.setter
    def translation(self, value: float) -> None:
        self._translation = max(value, 0.001)

    @property
    def rotation(self) -> float:
        """Snap increment for rotation in degrees."""
        return self._rotation

    @rotation.setter
    def rotation(self, value: float) -> None:
        self._rotation = max(value, 0.1)

    @property
    def scale(self) -> float:
        """Snap increment for scale factor."""
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        self._scale = max(value, 0.001)

    # -- Snap operations ----------------------------------------------------

    def snap_value(self, value: float, mode: SnapMode) -> float:
        """Snap a single float value to the nearest increment.

        Args:
            value: The input value.
            mode: Which snap increment to use.

        Returns:
            The snapped value.
        """
        if not self._enabled:
            return value
        increment = self._increment_for(mode)
        return round(round(value / increment) * increment, 10)

    def snap_vector(self, values: list[float], mode: SnapMode) -> list[float]:
        """Snap each element of a vector independently."""
        if not self._enabled:
            return values
        increment = self._increment_for(mode)
        return [round(round(v / increment) * increment, 10) for v in values]

    def snap_translation_value(self, value: float) -> float:
        """Snap a single translation axis value."""
        return self.snap_value(value, SnapMode.TRANSLATION)

    def snap_rotation_value(self, value_degrees: float) -> float:
        """Snap a rotation angle in degrees."""
        return self.snap_value(value_degrees, SnapMode.ROTATION)

    def snap_scale_value(self, value: float) -> float:
        """Snap a scale factor."""
        return self.snap_value(value, SnapMode.SCALE)

    # -- Presets ------------------------------------------------------------

    def set_preset(self, preset: str) -> None:
        """Apply a named snap preset.

        Args:
            preset: One of ``"fine"``, ``"medium"``, ``"coarse"``.
        """
        presets = {
            "fine": (0.05, 5.0, 0.01),
            "medium": (0.25, 15.0, 0.1),
            "coarse": (1.0, 45.0, 0.5),
        }
        if preset in presets:
            t, r, s = presets[preset]
            self._translation = t
            self._rotation = r
            self._scale = s

    def toggle(self) -> None:
        """Toggle snapping on/off."""
        self.enabled = not self._enabled

    # -- Internal -----------------------------------------------------------

    def _increment_for(self, mode: SnapMode) -> float:
        mapping = {
            SnapMode.TRANSLATION: self._translation,
            SnapMode.ROTATION: self._rotation,
            SnapMode.SCALE: self._scale,
        }
        return mapping[mode]
