"""Hardware subsystem errors.

Follows the core error hierarchy: everything derives from
:class:`ProjectionAIError` so callers can catch one base type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from projectionai.core.errors import ProjectionAIError

if TYPE_CHECKING:
    from projectionai.hardware.display_validator import ValidationReport


class HardwareError(ProjectionAIError):
    """Base error for the hardware subsystem."""


class DisplayNotFoundError(HardwareError):
    """A display id was referenced that is not currently connected."""


class OutputSwitchError(HardwareError):
    """A live output switch was rejected by validation.

    The offending :class:`~hardware.display_validator.ValidationReport`
    is attached as ``report`` for diagnostics.
    """

    def __init__(self, message: str, report: ValidationReport | None = None) -> None:
        super().__init__(message)
        self.report = report


class OutputSessionError(HardwareError):
    """An output session operation was invalid for the current state."""
