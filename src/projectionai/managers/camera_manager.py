"""Camera manager — device lifecycle, enumeration, and frame capture.

Coordinates camera devices between the application layer and the
capture backends registered with ``CameraProviderFactory``. Frames can
be captured directly (one-shot), as a continuous event stream, or as
background jobs through the ``JobManager``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable
from typing import override

from projectionai.core.errors import (
    CameraDisconnectedError,
    CameraError,
    CameraNotFoundError,
)
from projectionai.core.events import (
    CameraCaptureFailed,
    CameraClosed,
    CameraDisconnected,
    CameraFrameCaptured,
    CameraListRefreshed,
    CameraOpened,
    CameraPropertyChanged,
    EventBus,
)
from projectionai.managers import Manager
from projectionai.managers.job_manager import JobInfo, JobManager
from projectionai.services.camera import (
    Camera,
    CameraInfo,
    CameraProperty,
    CameraProvider,
    CameraProviderFactory,
    Frame,
)

_logger = logging.getLogger(__name__)


class CameraManager(Manager):
    """Manages camera enumeration, opening, and frame capture."""

    def __init__(
        self,
        event_bus: EventBus,
        job_manager: JobManager | None = None,
        provider: CameraProvider | None = None,
        provider_name: str = "opencv",
    ) -> None:
        super().__init__(event_bus)
        self._job_manager: JobManager | None = job_manager
        self._provider: CameraProvider | None = provider
        self._provider_name: str = provider_name
        self._camera_infos: dict[str, CameraInfo] = {}
        self._cameras: dict[str, Camera] = {}
        self._capture_tasks: dict[str, asyncio.Task[None]] = {}
        self._frame_subscribers: dict[str, list[Callable[[Frame], None]]] = {}

    # -- Enumeration --------------------------------------------------------

    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        """Return metadata for all detected cameras (empty if none)."""
        self._require_initialized()
        provider = self._get_provider()
        if provider is None:
            return ()
        infos = await provider.list_cameras()
        self._camera_infos = {info.camera_id: info for info in infos}
        return infos

    async def refresh_cameras(self) -> tuple[CameraInfo, ...]:
        """Re-enumerate cameras and emit ``CameraListRefreshed``."""
        infos = await self.list_cameras()
        self._emit_nowait(
            CameraListRefreshed(camera_ids=tuple(info.camera_id for info in infos))
        )
        return infos

    # -- Lifecycle ----------------------------------------------------------

    async def open_camera(self, camera_id: str) -> Camera:
        """Open a camera and emit ``CameraOpened``. Idempotent."""
        self._require_initialized()
        camera = self._cameras.get(camera_id)
        if camera is not None and camera.is_open:
            return camera
        provider = self._get_provider()
        if provider is None:
            raise CameraError("No camera provider is available")
        camera = await provider.open(camera_id)
        self._cameras[camera_id] = camera
        self._camera_infos[camera_id] = camera.info
        self._emit_nowait(CameraOpened(camera_id=camera_id, name=camera.info.name))
        _logger.info("Opened camera %s (%s)", camera_id, camera.info.name)
        return camera

    async def close_camera(self, camera_id: str) -> None:
        """Stop capture and close a camera, emitting ``CameraClosed``."""
        await self.stop_capture(camera_id)
        camera = self._cameras.pop(camera_id, None)
        self._frame_subscribers.pop(camera_id, None)
        if camera is None:
            return
        await camera.close()
        self._emit_nowait(CameraClosed(camera_id=camera_id))

    def is_open(self, camera_id: str) -> bool:
        """Return whether *camera_id* is currently open."""
        camera = self._cameras.get(camera_id)
        return camera is not None and camera.is_open

    def open_camera_ids(self) -> tuple[str, ...]:
        """Ids of all cameras currently open, in open order."""
        return tuple(
            camera_id for camera_id, camera in self._cameras.items() if camera.is_open
        )

    # -- Capture ------------------------------------------------------------

    async def capture_frame(self, camera_id: str) -> Frame:
        """Capture a single frame, emit ``CameraFrameCaptured``, and deliver
        it to registered frame subscribers."""
        self._require_initialized()
        camera = self._require_camera(camera_id)
        frame = await camera.capture()
        self._emit_nowait(
            CameraFrameCaptured(
                camera_id=camera_id,
                frame_number=frame.frame_number,
                width=frame.width,
                height=frame.height,
            )
        )
        self._deliver_frame(camera_id, frame)
        return frame

    def snapshot(self, camera_id: str, name: str = "camera.snapshot") -> JobInfo | None:
        """Enqueue a snapshot capture job (``None`` without a JobManager)."""
        self._require_initialized()
        if self._job_manager is None:
            return None
        job_id = f"snapshot-{uuid.uuid4().hex[:8]}"
        return self._job_manager.enqueue(
            job_id, name, self._capture_snapshot_impl, args=(camera_id,)
        )

    async def start_capture(self, camera_id: str, fps: int = 30) -> None:
        """Start a continuous capture loop emitting ``CameraFrameCaptured``."""
        self._require_initialized()
        if self._is_capturing(camera_id):
            return
        camera = await self.open_camera(camera_id)
        await camera.set_fps(fps)
        # Re-check after the awaits: a concurrent start_capture may have
        # registered a task while this coroutine was suspended.
        if self._is_capturing(camera_id):
            return
        interval = 1.0 / max(fps, 1)
        task = asyncio.create_task(
            self._capture_loop(camera_id, camera, interval),
            name=f"camera-capture-{camera_id}",
        )
        self._capture_tasks[camera_id] = task
        task.add_done_callback(self._make_capture_done_callback(camera_id))

    async def stop_capture(self, camera_id: str) -> None:
        """Stop the continuous capture loop for *camera_id* (no-op if idle)."""
        task = self._capture_tasks.pop(camera_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # A start_capture that was already in flight may have registered a
        # new task while we were waiting; the stop wins either way.
        task = self._capture_tasks.pop(camera_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _is_capturing(self, camera_id: str) -> bool:
        """Return True when a live capture task is registered for *camera_id*."""
        task = self._capture_tasks.get(camera_id)
        return task is not None and not task.done()

    def _make_capture_done_callback(
        self, camera_id: str
    ) -> Callable[[asyncio.Task[None]], None]:
        """Return an identity-safe done callback for a capture task.

        The callback only removes the entry when it still refers to the
        completing task, so a stale task finishing late can never pop a
        newer task registered for the same camera.
        """

        def _done(task: asyncio.Task[None]) -> None:
            if self._capture_tasks.get(camera_id) is task:
                self._capture_tasks.pop(camera_id, None)

        return _done

    # -- Frame subscribers ----------------------------------------------------

    def subscribe_frames(
        self, camera_id: str, handler: Callable[[Frame], None]
    ) -> None:
        """Register *handler* to receive frames captured for *camera_id*.

        Handlers receive frames produced by the continuous capture loop
        (:meth:`start_capture`) and by direct single-frame captures
        (:meth:`capture_frame`). One-shot snapshots taken through
        :meth:`snapshot` do not stream to subscribers — they capture a
        single frame for the caller only.

        Handlers run synchronously on the event-loop thread for each
        captured frame. A failing handler is logged and skipped — it does
        not stop the capture loop. Unsubscribe with :meth:`unsubscribe_frames`.
        """
        self._require_initialized()
        subscribers = self._frame_subscribers.setdefault(camera_id, [])
        if handler not in subscribers:
            subscribers.append(handler)

    def unsubscribe_frames(
        self, camera_id: str, handler: Callable[[Frame], None]
    ) -> None:
        """Remove a previously registered frame handler (no-op if absent)."""
        subscribers = self._frame_subscribers.get(camera_id)
        if subscribers is None:
            return
        if handler in subscribers:
            subscribers.remove(handler)
        if not subscribers:
            self._frame_subscribers.pop(camera_id, None)

    def frame_subscriber_count(self, camera_id: str) -> int:
        """Number of registered frame handlers for *camera_id*."""
        return len(self._frame_subscribers.get(camera_id, ()))

    def _deliver_frame(self, camera_id: str, frame: Frame) -> None:
        """Call every registered frame handler, isolating handler failures."""
        for handler in list(self._frame_subscribers.get(camera_id, ())):
            try:
                handler(frame)
            except Exception:
                _logger.exception("Frame handler failed for camera %s", camera_id)

    # -- Properties ---------------------------------------------------------

    async def get_property(self, camera_id: str, prop: CameraProperty) -> float | None:
        """Read a camera property (``None`` if unsupported or closed)."""
        camera = self._require_camera(camera_id)
        return await camera.get_property(prop)

    async def set_property(
        self, camera_id: str, prop: CameraProperty, value: float
    ) -> bool:
        """Set a camera property; emits ``CameraPropertyChanged`` on success."""
        camera = self._require_camera(camera_id)
        if not await camera.set_property(prop, value):
            return False
        self._emit_nowait(
            CameraPropertyChanged(
                camera_id=camera_id, property_name=prop.value, value=value
            )
        )
        return True

    async def set_resolution(self, camera_id: str, width: int, height: int) -> bool:
        """Request a capture resolution for *camera_id*."""
        camera = self._require_camera(camera_id)
        return await camera.set_resolution(width, height)

    async def set_fps(self, camera_id: str, fps: int) -> bool:
        """Request a capture frame rate for *camera_id*."""
        camera = self._require_camera(camera_id)
        return await camera.set_fps(fps)

    # -- Internal -----------------------------------------------------------

    async def _capture_snapshot_impl(self, camera_id: str) -> Frame:
        camera = self._require_camera(camera_id)
        return await camera.capture()

    async def _capture_loop(
        self, camera_id: str, camera: Camera, interval: float
    ) -> None:
        while True:
            try:
                frame = await camera.capture()
            except CameraDisconnectedError as exc:
                self._emit_nowait(CameraDisconnected(camera_id=camera_id))
                _logger.warning("Camera %s disconnected: %s", camera_id, exc)
                break
            except CameraError as exc:
                _logger.warning("Capture error on camera %s", camera_id, exc_info=True)
                self._emit_nowait(
                    CameraCaptureFailed(camera_id=camera_id, reason=str(exc))
                )
                await asyncio.sleep(interval)
                continue
            self._emit_nowait(
                CameraFrameCaptured(
                    camera_id=camera_id,
                    frame_number=frame.frame_number,
                    width=frame.width,
                    height=frame.height,
                )
            )
            self._deliver_frame(camera_id, frame)
            await asyncio.sleep(interval)

    def _get_provider(self) -> CameraProvider | None:
        if self._provider is None:
            try:
                self._provider = CameraProviderFactory.create(self._provider_name)
            except ValueError:
                _logger.warning(
                    "Camera provider %r is not registered", self._provider_name
                )
                return None
        return self._provider

    def _require_camera(self, camera_id: str) -> Camera:
        camera = self._cameras.get(camera_id)
        if camera is None:
            raise CameraNotFoundError(f"Camera {camera_id!r} is not open")
        return camera

    # -- Lifecycle hooks ----------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        try:
            infos = await self.list_cameras()
        except CameraError:
            _logger.warning("Camera enumeration failed", exc_info=True)
            infos = ()
        self._emit_nowait(
            CameraListRefreshed(camera_ids=tuple(info.camera_id for info in infos))
        )
        _logger.debug("CameraManager initialized: %d camera(s) detected", len(infos))

    @override
    async def _on_shutdown(self) -> None:
        for camera_id in list(self._capture_tasks):
            await self.stop_capture(camera_id)
        for camera_id in list(self._cameras):
            camera = self._cameras.pop(camera_id)
            await camera.close()
            self._emit_nowait(CameraClosed(camera_id=camera_id))
        self._frame_subscribers.clear()
