"""Gray-code structured light projector calibration (MVP).

Implements the :class:`ProjectorCalibrationAlgorithm` service contract
for calibrating a projector relative to a calibrated camera: patterns
are generated, projected onto a planar surface, captured, decoded into
camera-to-projector correspondences, and solved for the projector's
intrinsics and pose.

Components:

- ``patterns`` — gray-code stripe pattern generation.
- ``capture`` — projection/capture orchestration for a sequence.
- ``correspondence`` — decoding captures into dense correspondences.
- ``estimators`` — intrinsics, pose, and corner estimation.
- ``validation`` — reprojection error and coverage quality gates.
- ``gray_code`` — the composed :class:`GrayCodeProjectorCalibration`
  algorithm implementing the service contract.
"""

from projectionai.infrastructure.projector_calibration.capture import (
    PatternCaptureSession,
)
from projectionai.infrastructure.projector_calibration.correspondence import (
    CorrespondenceMatcher,
    gray_decode,
)
from projectionai.infrastructure.projector_calibration.estimators import (
    CameraProjectorTransform,
    CameraProjectorTransformEstimator,
    ProjectorCornerEstimator,
    ProjectorExtrinsicsEstimator,
    ProjectorIntrinsicsEstimator,
)
from projectionai.infrastructure.projector_calibration.gray_code import (
    GrayCodeProjectorCalibration,
)
from projectionai.infrastructure.projector_calibration.patterns import (
    GrayCodePatternGenerator,
    StructuredLightPatternGenerator,
    gray_encode,
)
from projectionai.infrastructure.projector_calibration.validation import (
    ReprojectionValidator,
    ValidationReport,
)
from projectionai.services.projector_calibration import (
    FrameSource,
    PatternProjector,
)

__all__ = [
    "CameraProjectorTransform",
    "CameraProjectorTransformEstimator",
    "CorrespondenceMatcher",
    "FrameSource",
    "GrayCodePatternGenerator",
    "GrayCodeProjectorCalibration",
    "PatternCaptureSession",
    "PatternProjector",
    "ProjectorCornerEstimator",
    "ProjectorExtrinsicsEstimator",
    "ProjectorIntrinsicsEstimator",
    "ReprojectionValidator",
    "StructuredLightPatternGenerator",
    "ValidationReport",
    "gray_decode",
    "gray_encode",
]
