"""Pattern presentation — Qt-free orchestration for calibration patterns.

Provides :class:`PatternPresentationSession` which consumes a
:class:`CalibrationSequence` and presents each pattern on a target display
deterministically, with proper frame boundaries, settle time, and
cancellation support.

The session is intentionally Qt-free: it depends only on the
:class:`PatternPresentationTarget` protocol, which implementations
(e.g. :class:`QTPatternPresentationTarget`) satisfy using whatever
toolkit they choose.

Safety is delegated to the application layer — this module does NOT
create a parallel safety state machine.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from projectionai.core.errors import ProjectionAIError
from projectionai.domain.calibration_session import (
    CalibrationPattern,
    CalibrationSequence,
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PresentationError(ProjectionAIError):
    """Raised when pattern presentation fails."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PresentationMode(StrEnum):
    """How to present patterns on the target display."""

    FULL_SEQUENCE = "full_sequence"
    SINGLE_PATTERN = "single_pattern"
    BLACK = "black"
    WHITE = "white"
    HIDE = "hide"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PresentationConfig:
    """Configuration for pattern presentation.

    Attributes:
        mode: Presentation strategy.
        pattern_index: Index into the sequence (``SINGLE_PATTERN`` only).
        settle_ms: Milliseconds to wait after each pattern is presented
            before returning the timestamp.  Gives the display time to
            settle so the camera captures a stable frame.
        presentation_timeout: Seconds to wait for the target to confirm
            presentation before raising.
    """

    mode: PresentationMode = PresentationMode.FULL_SEQUENCE
    pattern_index: int | None = None
    settle_ms: float = 20.0
    presentation_timeout: float = 2.0

    def __post_init__(self) -> None:
        if self.mode is PresentationMode.SINGLE_PATTERN and self.pattern_index is None:
            raise ValueError("SINGLE_PATTERN mode requires pattern_index")
        if self.pattern_index is not None and self.pattern_index < 0:
            raise ValueError(f"pattern_index must be >= 0, got {self.pattern_index}")
        if self.settle_ms < 0:
            raise ValueError(f"settle_ms must be >= 0, got {self.settle_ms}")
        if self.presentation_timeout <= 0:
            raise ValueError(
                f"presentation_timeout must be > 0, got {self.presentation_timeout}"
            )


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternPresentationState:
    """Snapshot of the current presentation session state.

    Accessible via :attr:`PatternPresentationSession.state`.
    """

    pattern_index: int | None
    total_patterns: int
    mode: PresentationMode
    timestamp_ns: int | None
    timestamp_kind: TimestampKind | None
    is_complete: bool


# ---------------------------------------------------------------------------
# Target protocol
# ---------------------------------------------------------------------------


class TimestampKind(StrEnum):
    """Semantic label for presentation timestamps.

    Callers MUST use this to determine whether a timestamp represents a
    real display-present boundary or merely a best-effort approximation.
    """

    BEST_EFFORT = "best_effort"
    """``time.monotonic_ns()`` taken after a ``show_pattern()`` call.

    NOT a real display-present boundary.  Use only for coarse settle-time
    coordination.  Do NOT use for frame-accurate capture synchronization.
    """


# Sentinel constant — documentation-first approach per Gate 2 review.
BEST_EFFORT_TIMESTAMP: TimestampKind = TimestampKind.BEST_EFFORT


class PatternPresentationTarget(Protocol):
    """Protocol for display targets that can show calibration patterns.

    This is intentionally Qt-free.  Implementations may use Qt, OpenGL,
    or any other toolkit.

    **Production path (Gate 1):**
    The production implementation is :class:`QTPatternPresentationTarget`
    wrapping :class:`~projectionai.infrastructure.display.qt.QtPatternProjector`.
    This path uses QLabel/QPixmap with ``Format_Grayscale8`` to display
    arbitrary grayscale calibration images at native resolution.

    ``GLOutputWindow`` is **not** the production path for calibration
    patterns — it only supports predefined ``PatternKind`` test patterns
    (solid colours, grids, etc.) via :class:`PatternPass`, not arbitrary
    grayscale images from :class:`CalibrationSequence`.

    **Timestamp semantics (Gate 2):**
    ``show_pattern()`` returns a ``time.monotonic_ns()`` timestamp that
    is a **best-effort approximation**, NOT a real display-present
    boundary.  Hardware vsync observation is not yet implemented.
    Callers MUST check ``timestamp_kind`` on the presentation state to
    determine how to interpret the timestamp.
    """

    async def enter_fullscreen(self) -> None:
        """Enter fullscreen mode on the target display."""
        ...

    async def show_pattern(self, pattern: CalibrationPattern) -> int:
        """Display *pattern* and return the presentation timestamp (ns).

        The returned timestamp is ``time.monotonic_ns()`` taken after
        the ``show`` call completes.  It is a **best-effort approximation**
        (see :class:`TimestampKind`), NOT a real display-present boundary.
        """
        ...

    async def hide(self) -> None:
        """Blank the display (show black)."""
        ...

    async def exit_fullscreen(self) -> None:
        """Exit fullscreen and restore the desktop."""
        ...

    @property
    def resolution(self) -> tuple[int, int]:
        """Target display resolution as ``(width, height)``."""
        ...


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class PatternPresentationSession:
    """Qt-free orchestrator for presenting calibration pattern sequences.

    Consumes a :class:`CalibrationSequence` and presents each pattern on
    the given :class:`PatternPresentationTarget`.  Supports full sequence,
    single pattern, black, white, and hide modes.

    Does **not** create a parallel safety state machine.  Safety is
    delegated to the application layer (``OutputManager``).

    Usage::

        target = QTPatternPresentationTarget(projector)
        session = PatternPresentationSession(target)
        await session.start()
        await session.show(sequence)
        await session.stop()
    """

    def __init__(
        self,
        target: PatternPresentationTarget,
        config: PresentationConfig | None = None,
    ) -> None:
        self._target = target
        self._config = config or PresentationConfig()
        self._pattern_index: int | None = None
        self._total_patterns: int = 0
        self._timestamp_ns: int | None = None
        self._timestamp_kind: TimestampKind | None = None
        self._is_complete: bool = False
        self._lock = asyncio.Lock()

    # -- Properties --------------------------------------------------------

    @property
    def state(self) -> PatternPresentationState:
        """Return the current presentation state."""
        return PatternPresentationState(
            pattern_index=self._pattern_index,
            total_patterns=self._total_patterns,
            mode=self._config.mode,
            timestamp_ns=self._timestamp_ns,
            timestamp_kind=self._timestamp_kind,
            is_complete=self._is_complete,
        )

    # -- Public API --------------------------------------------------------

    async def start(self) -> None:
        """Enter fullscreen on the target display."""
        async with self._lock:
            await self._target.enter_fullscreen()

    async def show(self, sequence: CalibrationSequence) -> None:
        """Present a calibration sequence according to the configured mode.

        Args:
            sequence: The calibration sequence to present.

        Raises:
            PresentationError: If presentation fails.
        """
        async with self._lock:
            self._total_patterns = len(sequence.patterns)
            self._is_complete = False

            try:
                if self._config.mode is PresentationMode.FULL_SEQUENCE:
                    await self._present_sequence(sequence)
                elif self._config.mode is PresentationMode.SINGLE_PATTERN:
                    await self._present_single(sequence)
                elif self._config.mode is PresentationMode.BLACK:
                    await self._target.hide()
                    self._timestamp_ns = time.monotonic_ns()
                    self._timestamp_kind = BEST_EFFORT_TIMESTAMP
                elif self._config.mode is PresentationMode.WHITE:
                    raise PresentationError(
                        "WHITE mode is not supported by the current target; "
                        "use BLACK mode instead"
                    )
                elif self._config.mode is PresentationMode.HIDE:
                    await self._target.hide()
                    self._timestamp_ns = time.monotonic_ns()
                    self._timestamp_kind = BEST_EFFORT_TIMESTAMP

                self._is_complete = True
            except asyncio.CancelledError:
                raise
            except PresentationError:
                raise
            except Exception as exc:
                raise PresentationError(f"Pattern presentation failed: {exc}") from exc

    async def show_single(self, pattern: CalibrationPattern) -> None:
        """Present a single pattern directly (bypasses mode config).

        Args:
            pattern: The pattern to display.
        """
        async with self._lock:
            self._total_patterns = 1
            self._pattern_index = 0
            self._is_complete = False
            try:
                self._timestamp_ns = await asyncio.wait_for(
                    self._target.show_pattern(pattern),
                    timeout=self._config.presentation_timeout,
                )
                self._timestamp_kind = BEST_EFFORT_TIMESTAMP
                if self._config.settle_ms > 0:
                    await asyncio.sleep(self._config.settle_ms / 1000.0)
                self._is_complete = True
            except asyncio.CancelledError:
                raise
            except PresentationError:
                raise
            except Exception as exc:
                raise PresentationError(
                    f"Single pattern presentation failed: {exc}"
                ) from exc

    async def hide(self) -> None:
        """Blank the display."""
        async with self._lock:
            await self._target.hide()
            self._timestamp_ns = time.monotonic_ns()
            self._timestamp_kind = BEST_EFFORT_TIMESTAMP

    async def stop(self) -> None:
        """Stop presentation, hide display, and exit fullscreen.

        Safe to call multiple times.
        """
        async with self._lock:
            try:
                await self._target.hide()
            except Exception:
                _logger.debug("hide() failed during stop", exc_info=True)
            try:
                await self._target.exit_fullscreen()
            except Exception:
                _logger.debug("exit_fullscreen() failed during stop", exc_info=True)

    # -- Private helpers ---------------------------------------------------

    async def _present_sequence(self, sequence: CalibrationSequence) -> None:
        """Present each pattern in the sequence sequentially."""
        for idx, pattern in enumerate(sequence.patterns):
            self._pattern_index = idx
            try:
                self._timestamp_ns = await asyncio.wait_for(
                    self._target.show_pattern(pattern),
                    timeout=self._config.presentation_timeout,
                )
                self._timestamp_kind = BEST_EFFORT_TIMESTAMP
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise PresentationError(
                    f"Failed to present pattern {idx}: {exc}"
                ) from exc

            if self._config.settle_ms > 0:
                await asyncio.sleep(self._config.settle_ms / 1000.0)

    async def _present_single(self, sequence: CalibrationSequence) -> None:
        """Present a single pattern from the sequence by index."""
        idx = self._config.pattern_index
        if idx is None or idx >= len(sequence.patterns):
            raise PresentationError(
                f"pattern_index {idx} out of range "
                f"for sequence of {len(sequence.patterns)}"
            )
        self._pattern_index = idx
        pattern = sequence.patterns[idx]
        try:
            self._timestamp_ns = await asyncio.wait_for(
                self._target.show_pattern(pattern),
                timeout=self._config.presentation_timeout,
            )
            self._timestamp_kind = BEST_EFFORT_TIMESTAMP
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise PresentationError(f"Failed to present pattern {idx}: {exc}") from exc

        if self._config.settle_ms > 0:
            await asyncio.sleep(self._config.settle_ms / 1000.0)
