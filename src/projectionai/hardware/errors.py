"""Hardware subsystem errors.

Follows the core error hierarchy: everything derives from
:class:`ProjectionAIError` so callers can catch one base type.

Error usage note:
- ArmNotAuthorizedError: Currently not raised (arm() returns report). Reserved for future use if arm() behavior changes.
- LiveNotAuthorizedError: Raised by go_live() when validation gate blocks live transition.
- OutputActivationError: Reserved for future GL window activation failures.
- SafeStopError: Reserved for future safe_stop() failure handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from projectionai.core.errors import ProjectionAIError

if TYPE_CHECKING:
    from projectionai.calibration.validation_gate import ValidationGateResult
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


class ArmNotAuthorizedError(HardwareError):
    """Arming was rejected by the validation gate."""

    def __init__(
        self, message: str, gate_result: ValidationGateResult | None = None
    ) -> None:
        super().__init__(message)
        self.gate_result = gate_result


class LiveNotAuthorizedError(HardwareError):
    """Going live was rejected by the validation gate."""

    def __init__(
        self, message: str, gate_result: ValidationGateResult | None = None
    ) -> None:
        super().__init__(message)
        self.gate_result = gate_result


class DisplayLostError(HardwareError):
    """The live display disconnected unexpectedly."""

    def __init__(self, display_id: str) -> None:
        super().__init__(f"Live display lost: {display_id}")
        self.display_id = display_id


class CalibrationInvalidError(HardwareError):
    """Active calibration became incompatible or was invalidated."""

    def __init__(self, reason: str, calibration_id: str | None = None) -> None:
        super().__init__(reason)
        self.calibration_id = calibration_id


class OutputActivationError(HardwareError):
    """GL output window failed to activate."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)


class SafeStopError(HardwareError):
    """Safe stop operation failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
