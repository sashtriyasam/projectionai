"""Camera abstraction.

Device-agnostic interface for enumerating and capturing from camera
sources. Concrete implementations (OpenCV, mock, future capture cards /
phone streaming) live in ``infrastructure.camera`` and are created
through :class:`CameraProviderFactory`.

The abstraction is deliberately independent of vision, calibration, and
AI algorithms — higher layers consume :class:`Frame` objects without
knowing which physical device produced them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class CameraProperty(StrEnum):
    """Camera properties that may be exposed by a device."""

    FOCUS = "focus"
    EXPOSURE = "exposure"
    GAIN = "gain"
    WHITE_BALANCE = "white_balance"


@dataclass(frozen=True)
class CameraInfo:
    """Static metadata describing a camera device.

    ``camera_id`` is the opaque device identifier used with
    :meth:`CameraProvider.open`. Backend-specific implementations decide
    its format (e.g. ``"0"`` for the first OpenCV device).
    """

    camera_id: str
    name: str
    backend: str = "opencv"  # opencv, mock, capture_card, phone, ...
    interface: str = "usb"  # usb, ethernet, hdmi, mipi, virtual
    vendor: str = ""
    model: str = ""
    serial_number: str = ""
    max_resolution: tuple[int, int] = (1920, 1080)
    supported_properties: tuple[CameraProperty, ...] = ()


@dataclass(frozen=True)
class Frame:
    """A single captured frame in RGB color space."""

    image: NDArray[np.uint8] = field(compare=False)  # (H, W, 3) RGB
    timestamp: float  # time.monotonic() seconds
    camera_id: str
    frame_number: int

    @property
    def width(self) -> int:
        """Frame width in pixels."""
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        """Frame height in pixels."""
        return int(self.image.shape[0])


# ---------------------------------------------------------------------------
# Camera — abstract interface
# ---------------------------------------------------------------------------


class Camera(ABC):
    """Abstract camera device.

    Implementations wrap a physical or virtual capture source. All
    methods are async so blocking capture backends can run on the
    event loop's executor without blocking the UI thread.
    """

    @property
    @abstractmethod
    def info(self) -> CameraInfo:
        """Return static device metadata."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Return ``True`` when the device is open and capturing."""

    @abstractmethod
    async def open(self) -> None:
        """Open the device.

        Raises:
            CameraOpenError: If the device cannot be opened.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close the device. Safe to call on an already-closed camera."""

    @abstractmethod
    async def capture(self) -> Frame:
        """Capture the next frame.

        Returns:
            An RGB frame with a monotonic timestamp.

        Raises:
            CameraUnavailableError: If the camera is not open.
            CameraDisconnectedError: If the device disconnected.
            CameraCaptureError: If frame acquisition failed.
        """

    @abstractmethod
    async def set_resolution(self, width: int, height: int) -> bool:
        """Request a capture resolution. Returns ``True`` if accepted."""

    @abstractmethod
    async def set_fps(self, fps: int) -> bool:
        """Request a capture frame rate. Returns ``True`` if accepted."""

    @abstractmethod
    async def get_property(self, prop: CameraProperty) -> float | None:
        """Read a camera property, or ``None`` if unsupported."""

    @abstractmethod
    async def set_property(self, prop: CameraProperty, value: float) -> bool:
        """Set a camera property. Returns ``False`` if unsupported."""


# ---------------------------------------------------------------------------
# Camera provider — enumeration + device opening
# ---------------------------------------------------------------------------


class CameraProvider(ABC):
    """Abstract camera source: discovers devices and opens them."""

    @abstractmethod
    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        """Enumerate all connected cameras.

        Returns:
            Metadata for each detected device. Empty tuple when no
            cameras are available — never raises for missing hardware.
        """

    @abstractmethod
    async def open(self, camera_id: str) -> Camera:
        """Open a camera by its ``camera_id``.

        Raises:
            CameraNotFoundError: If the device is not available.
            CameraOpenError: If the device cannot be opened.
        """


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class CameraProviderFactory:
    """Creates camera providers by backend name."""

    _registry: ClassVar[dict[str, type[CameraProvider]]] = {}

    @classmethod
    def register(cls, name: str, provider_cls: type[CameraProvider]) -> None:
        """Register a provider class under *name*."""
        cls._registry[name] = provider_cls

    @classmethod
    def create(cls, name: str, **kwargs: object) -> CameraProvider:
        """Create a provider instance by registered name."""
        if name not in cls._registry:
            cls._ensure_builtin_providers()
        if name not in cls._registry:
            msg = f"Unknown camera provider: {name!r}. Available: {list(cls._registry)}"
            raise ValueError(msg)
        return cls._registry[name](**kwargs)

    @classmethod
    def _ensure_builtin_providers(cls) -> None:
        """Register the built-in ``mock``/``opencv`` providers on demand.

        Importing the provider modules registers their classes with this
        factory, so ``create()`` works regardless of whether the
        ``infrastructure.camera`` package was imported first.
        """
        from projectionai.infrastructure.camera.mock_camera import (
            MockCameraProvider,
        )
        from projectionai.infrastructure.camera.opencv_camera import (
            OpenCVCameraProvider,
        )

        cls.register("mock", MockCameraProvider)
        cls.register("opencv", OpenCVCameraProvider)

    @classmethod
    def available(cls) -> tuple[str, ...]:
        """Return all registered provider names."""
        return tuple(sorted(cls._registry))
