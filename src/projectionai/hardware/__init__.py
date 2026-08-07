"""Hardware management & display validation subsystem.

Public API:

- Models: :class:`DisplayInfo`, :class:`DisplayMode`, :class:`DisplayCapabilities`,
  :class:`HardwareStatus`, :class:`OutputWindow`
- Managers: :class:`DisplayManager`, :class:`DisplayWatcher`,
  :class:`OutputManager`, :class:`HardwareManager`
- Validation: :class:`DisplayValidator`, :class:`ValidationReport`,
  :class:`ValidationIssue`, :class:`ValidateInputs`
- Classification: :class:`DisplayClassifier`, :class:`DisplayKind`
- Events: typed bus events live in :mod:`projectionai.hardware.events`
  and are not re-exported here
- Patterns: :data:`PATTERNS`, :class:`PatternSpec`, :class:`PatternKind`
- Errors: :class:`HardwareError` hierarchy
"""

from projectionai.hardware.classifier import DEFAULT_CLASSIFIER, DisplayClassifier
from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.display_validator import (
    DisplayValidator,
    ValidateInputs,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from projectionai.hardware.display_watcher import DisplayWatcher
from projectionai.hardware.errors import (
    DisplayNotFoundError,
    HardwareError,
    OutputSessionError,
    OutputSwitchError,
)
from projectionai.hardware.hardware_manager import HardwareManager
from projectionai.hardware.models import (
    DisplayCapabilities,
    DisplayConnection,
    DisplayInfo,
    DisplayKind,
    DisplayMode,
    DisplayOrientation,
    HardwareStatus,
    OutputWindow,
)
from projectionai.hardware.output_manager import (
    OutputManager,
    OutputSession,
    OutputState,
)
from projectionai.hardware.patterns import (
    PATTERNS,
    PatternKind,
    PatternSpec,
    get_pattern,
)

__all__ = [
    "DEFAULT_CLASSIFIER",
    "PATTERNS",
    "DisplayCapabilities",
    "DisplayClassifier",
    "DisplayConnection",
    "DisplayInfo",
    "DisplayKind",
    "DisplayManager",
    "DisplayMode",
    "DisplayNotFoundError",
    "DisplayOrientation",
    "DisplayValidator",
    "DisplayWatcher",
    "HardwareError",
    "HardwareManager",
    "HardwareStatus",
    "OutputManager",
    "OutputSession",
    "OutputSessionError",
    "OutputState",
    "OutputSwitchError",
    "OutputWindow",
    "PatternKind",
    "PatternSpec",
    "ValidateInputs",
    "ValidationIssue",
    "ValidationReport",
    "ValidationSeverity",
    "get_pattern",
]
