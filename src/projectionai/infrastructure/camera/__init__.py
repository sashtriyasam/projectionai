"""Camera capture backends.

Importing this package registers the available providers with
``CameraProviderFactory``.
"""

from projectionai.infrastructure.camera.mock_camera import (
    MockCamera,
    MockCameraProvider,
)
from projectionai.infrastructure.camera.opencv_camera import (
    OpenCVCamera,
    OpenCVCameraProvider,
)

__all__ = [
    "MockCamera",
    "MockCameraProvider",
    "OpenCVCamera",
    "OpenCVCameraProvider",
]
