"""DisplayValidator — pre-flight checks before output goes live.

Pure, Qt-free validation of the output chain. Produces a
:class:`ValidationReport` with three buckets:

- errors — the switch MUST NOT happen (safe switching aborts).
- warnings — the switch can happen but conditions are suboptimal.
- recommendations — optional hardening / nice-to-haves.

Checks: renderer ready, display connected, projector available,
resolution / refresh rate valid for the target, GPU compatibility,
no duplicate preview/live output, window availability.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from projectionai.hardware.models import DisplayInfo, DisplayKind, DisplayMode

#: GPU names that indicate software rendering / no real GPU.
_SOFTWARE_GPU_MARKERS: tuple[str, ...] = (
    "microsoft basic display",
    "llvmpipe",
    "swiftshader",
    "software renderer",
    "virgl",
)

#: Minimum live resolution before we warn.
_MIN_LIVE_WIDTH = 1280
_MIN_LIVE_HEIGHT = 720

#: Minimum live refresh rate before we warn.
_MIN_LIVE_REFRESH = 50.0


class ValidationSeverity(StrEnum):
    """Severity of a validation finding."""

    ERROR = "error"
    WARNING = "warning"
    RECOMMENDATION = "recommendation"


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding."""

    severity: ValidationSeverity
    code: str
    message: str
    display_id: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    """Result of a validation pass."""

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        """Issues that block the switch."""
        return tuple(i for i in self.issues if i.severity is ValidationSeverity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        """Issues that do not block but degrade quality."""
        return tuple(i for i in self.issues if i.severity is ValidationSeverity.WARNING)

    @property
    def recommendations(self) -> tuple[ValidationIssue, ...]:
        """Optional hardening suggestions."""
        return tuple(
            i for i in self.issues if i.severity is ValidationSeverity.RECOMMENDATION
        )

    @property
    def is_ok(self) -> bool:
        """True when no errors are present (warnings allowed)."""
        return not self.errors

    @property
    def summary(self) -> str:
        """One-line summary, e.g. ``"2 errors, 1 warning"``."""
        parts = []
        if self.errors:
            parts.append(
                f"{len(self.errors)} error{'s' if len(self.errors) > 1 else ''}"
            )
        if self.warnings:
            parts.append(
                f"{len(self.warnings)} warning{'s' if len(self.warnings) > 1 else ''}"
            )
        if self.recommendations:
            parts.append(
                f"{len(self.recommendations)} recommendation"
                f"{'s' if len(self.recommendations) > 1 else ''}"
            )
        return ", ".join(parts) if parts else "all checks passed"


@dataclass(frozen=True)
class ValidateInputs:
    """Everything the validator needs to know about the current chain."""

    displays: Sequence[DisplayInfo] = ()
    live_display_id: str | None = None
    preview_display_id: str | None = None
    renderer_ready: bool = True
    target_mode: DisplayMode | None = None
    gpu_name: str = ""
    window_available: bool = True
    require_projector: bool = False


class DisplayValidator:
    """Stateless validation of the display/output chain."""

    def validate(self, inputs: ValidateInputs) -> ValidationReport:
        """Run all checks and return a :class:`ValidationReport`."""
        issues: list[ValidationIssue] = []
        by_id = {d.display_id: d for d in inputs.displays}

        # -- Renderer -------------------------------------------------------
        if not inputs.renderer_ready:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "renderer_not_ready",
                    "The renderer is not ready — live output would show nothing.",
                )
            )

        # -- Display presence -----------------------------------------------
        if not inputs.displays:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "no_display_connected",
                    "No display is connected.",
                )
            )

        live = by_id.get(inputs.live_display_id or "")
        if inputs.live_display_id is not None and live is None:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "live_display_not_found",
                    "The live display is no longer connected.",
                    display_id=inputs.live_display_id,
                )
            )

        preview = by_id.get(inputs.preview_display_id or "")
        if inputs.preview_display_id is not None and preview is None:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "preview_display_not_found",
                    "The preview display is no longer connected.",
                    display_id=inputs.preview_display_id,
                )
            )

        # -- Projector availability ------------------------------------------
        projectors = [d for d in inputs.displays if d.kind is DisplayKind.PROJECTOR]
        if (
            inputs.require_projector
            and inputs.live_display_id is None
            and not projectors
        ):
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "no_projector_available",
                    "No projector is available — live output cannot be routed.",
                )
            )
        if live is not None and live.kind is not DisplayKind.PROJECTOR:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.WARNING,
                    "live_target_not_projector",
                    "The live output target is not a projector.",
                    display_id=live.display_id,
                )
            )

        # -- Resolution / refresh validity ------------------------------------
        if live is not None:
            mode = inputs.target_mode or live.current_mode
            supported = live.supported_modes
            supported_keys = {(m.width, m.height, m.refresh_rate) for m in supported}
            if (
                supported
                and (mode.width, mode.height, mode.refresh_rate) not in supported_keys
            ):
                issues.append(
                    ValidationIssue(
                        ValidationSeverity.ERROR,
                        "resolution_unsupported",
                        f"{mode.label} is not a supported mode of {live.name!r}.",
                        display_id=live.display_id,
                    )
                )
            if mode.width < _MIN_LIVE_WIDTH or mode.height < _MIN_LIVE_HEIGHT:
                issues.append(
                    ValidationIssue(
                        ValidationSeverity.WARNING,
                        "low_resolution",
                        f"Live resolution {mode.width}x{mode.height} is below "
                        f"{_MIN_LIVE_WIDTH}x{_MIN_LIVE_HEIGHT}.",
                        display_id=live.display_id,
                    )
                )
            if mode.refresh_rate < _MIN_LIVE_REFRESH:
                issues.append(
                    ValidationIssue(
                        ValidationSeverity.WARNING,
                        "low_refresh_rate",
                        f"Live refresh rate {mode.refresh_rate:.0f} Hz "
                        f"is below {_MIN_LIVE_REFRESH:.0f} Hz — motion may stutter.",
                        display_id=live.display_id,
                    )
                )

        # -- GPU compatibility ------------------------------------------------
        gpu = inputs.gpu_name.lower()
        if any(marker in gpu for marker in _SOFTWARE_GPU_MARKERS):
            issues.append(
                ValidationIssue(
                    ValidationSeverity.WARNING,
                    "software_renderer",
                    "The active GPU is a software renderer — performance will "
                    "be limited.",
                )
            )

        # -- Duplicate output ---------------------------------------------------
        if (
            inputs.live_display_id is not None
            and inputs.live_display_id == inputs.preview_display_id
        ):
            issues.append(
                ValidationIssue(
                    ValidationSeverity.WARNING,
                    "duplicate_output",
                    "Live and preview are routed to the same display.",
                    display_id=inputs.live_display_id,
                )
            )

        # -- Window availability -------------------------------------------------
        if inputs.live_display_id is not None and not inputs.window_available:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "window_not_available",
                    "No output window exists to drive on live switch.",
                )
            )

        return ValidationReport(tuple(issues))
