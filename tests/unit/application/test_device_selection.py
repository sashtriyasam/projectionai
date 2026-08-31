"""Tests for device selection UX model â€” enumeration, selection, safety."""

import pytest

from projectionai.application.device_selection import (
    CameraSelection,
    ProjectorSelection,
    SelectionState,
    SelectionStore,
)
from projectionai.hardware.models import DisplayInfo
from projectionai.services.camera import CameraInfo


def _cam_info(cam_id="cam-0"):
    return CameraInfo(
        camera_id=cam_id,
        name=f"Camera {cam_id}",
        backend="opencv",
        max_resolution=(1280, 720),
    )


def _display_info(did="disp-0", kind="monitor", fullscreen=True):
    from unittest.mock import MagicMock

    cap = MagicMock()
    cap.kind = kind
    cap.supports_fullscreen = fullscreen
    mode = MagicMock()
    mode.width = 1920
    mode.height = 1080
    mode.refresh_rate = 60.0
    info = MagicMock(spec=DisplayInfo)
    info.display_id = did
    info.name = f"Display {did}"
    info.position = (0, 0)
    info.current_mode = mode
    info.is_primary = True
    info.capabilities = cap
    return info


def test_camera_selection_from_info():
    info = _cam_info("cam-1")
    sel = CameraSelection.from_camera_info(
        info, state=SelectionState.AVAILABLE, is_open=False
    )
    assert sel.camera_id == "cam-1"
    assert sel.resolution == (1280, 720)
    assert sel.state == SelectionState.AVAILABLE


def test_projector_selection_from_display():
    info = _display_info("disp-1", kind="projector", fullscreen=True)
    sel = ProjectorSelection.from_display_info(
        info, state=SelectionState.AVAILABLE, validation_ok=True
    )
    assert sel.display_id == "disp-1"
    assert sel.supports_fullscreen is True
    assert sel.state == SelectionState.AVAILABLE


def test_selection_store_camera():
    store = SelectionStore()
    store.select_camera("cam-0")
    assert store.selected_camera_id == "cam-0"
    store.select_camera(None)
    assert store.selected_camera_id is None


def test_selection_store_display_and_resolution():
    store = SelectionStore()
    store.select_display("disp-1")
    assert store.selected_display_id == "disp-1"
    store.set_resolution((1920, 1080))
    assert store.selected_resolution == (1920, 1080)
    with pytest.raises(ValueError):
        store.set_resolution((0, 1080))


def test_invalid_display_kind_not_bypassed():
    # Monitor classified as "monitor" must not silently become projector â€” validation_ok False
    info = _display_info("disp-2", kind="monitor", fullscreen=True)
    sel = ProjectorSelection.from_display_info(
        info,
        state=SelectionState.UNAVAILABLE,
        validation_ok=False,
        error="Display not suitable for projector use",
    )
    assert sel.kind == "monitor"
    assert sel.validation_ok is False
    assert sel.error is not None and "not suitable" in sel.error


def test_refresh_persistence():
    store = SelectionStore()
    store.select_camera("cam-0")
    store.select_display("disp-0")
    snap = store.snapshot()
    assert snap["camera_id"] == "cam-0"
    assert snap["display_id"] == "disp-0"
    # Simulate refresh â€” store retains selection until explicitly cleared
    assert store.selected_camera_id == "cam-0"


def test_backend_selection():
    store = SelectionStore()
    store.set_backend("opencv")
    assert store.selected_backend == "opencv"
    store.set_backend(None)
    assert store.selected_backend is None


def test_selection_state_enum():
    assert SelectionState.AVAILABLE.value == "available"
    assert SelectionState.SELECTED.value == "selected"
    assert SelectionState.UNAVAILABLE.value == "unavailable"
    assert SelectionState.ERROR.value == "error"


def test_camera_disappears_after_selection():
    store = SelectionStore()
    store.select_camera("cam-0")
    assert store.selected_camera_id == "cam-0"
    # Simulate camera disconnect — provider no longer lists cam-0
    available = [_cam_info("cam-1")]
    # Selection remains but should be considered stale; UI must show UNAVAILABLE
    sel = CameraSelection.from_camera_info(
        available[0], state=SelectionState.AVAILABLE, is_open=False
    )
    assert sel.camera_id != store.selected_camera_id
    # Store still holds stale ID — caller must clear or revalidate
    assert store.selected_camera_id == "cam-0"
    # After revalidation, stale selection should be cleared explicitly
    store.select_camera(None)
    assert store.selected_camera_id is None


def test_display_disappears_after_selection():
    store = SelectionStore()
    store.select_display("disp-0")
    assert store.selected_display_id == "disp-0"
    # Display no longer in enumeration
    available_ids = ["disp-1"]
    assert store.selected_display_id not in available_ids
    # Store retains stale ID until cleared — safety check must not allow arm/live
    assert store.selected_display_id == "disp-0"
    store.select_display(None)
    assert store.selected_display_id is None


def test_selected_display_changes_classification():
    # Initially projector
    info_proj = _display_info("disp-0", kind="projector", fullscreen=True)
    sel1 = ProjectorSelection.from_display_info(
        info_proj, state=SelectionState.SELECTED, validation_ok=True
    )
    assert sel1.validation_ok is True
    # Reclassified as monitor (e.g., driver update)
    info_mon = _display_info("disp-0", kind="monitor", fullscreen=True)
    sel2 = ProjectorSelection.from_display_info(
        info_mon,
        state=SelectionState.UNAVAILABLE,
        validation_ok=False,
        error="Display not suitable for projector use",
    )
    assert sel2.kind == "monitor"
    assert sel2.validation_ok is False
    assert sel2.error is not None


def test_refresh_with_selected_device_missing():
    store = SelectionStore()
    store.select_camera("cam-0")
    store.select_display("disp-0")
    # Refresh returns new inventory without selected devices
    new_cameras = [_cam_info("cam-1")]
    new_displays = ["disp-1"]
    # Selections are stale — UI must show UNAVAILABLE, not auto-switch to new device
    assert store.selected_camera_id not in [c.camera_id for c in new_cameras]
    assert store.selected_display_id not in new_displays
    # Snapshot still holds stale IDs — caller must handle invalidation
    snap = store.snapshot()
    assert snap["camera_id"] == "cam-0"
    assert snap["display_id"] == "disp-0"


def test_invalid_backend():
    store = SelectionStore()
    # Backend is free-form string but should be validated against known providers
    # For now, any non-empty string is accepted; empty string is treated as None
    store.set_backend("opencv")
    assert store.selected_backend == "opencv"
    store.set_backend("mock")
    assert store.selected_backend == "mock"
    # Clearing
    store.set_backend(None)
    assert store.selected_backend is None
    store.set_backend("")
    assert store.selected_backend == ""


def test_clearing_selections():
    store = SelectionStore()
    store.select_camera("cam-0")
    store.select_display("disp-0")
    store.set_resolution((1920, 1080))
    store.set_backend("opencv")
    assert store.selected_camera_id == "cam-0"
    store.select_camera(None)
    store.select_display(None)
    store.set_resolution(None)
    store.set_backend(None)
    assert store.selected_camera_id is None
    assert store.selected_display_id is None
    assert store.selected_resolution is None
    assert store.selected_backend is None
    snap = store.snapshot()
    assert snap["camera_id"] is None
    assert snap["display_id"] is None


def test_snapshot_correctness_after_failure_recovery():
    store = SelectionStore()
    # Initial valid selection
    store.select_camera("cam-0")
    store.select_display("disp-0")
    snap1 = store.snapshot()
    assert snap1["camera_id"] == "cam-0"
    # Simulate failure — camera disconnect, display remains
    store.select_camera(None)  # recovery: clear stale camera
    snap2 = store.snapshot()
    assert snap2["camera_id"] is None
    assert snap2["display_id"] == "disp-0"
    # Re-select new camera
    store.select_camera("cam-1")
    snap3 = store.snapshot()
    assert snap3["camera_id"] == "cam-1"
    assert snap3["display_id"] == "disp-0"
    # Full clear
    store.select_camera(None)
    store.select_display(None)
    snap4 = store.snapshot()
    assert snap4["camera_id"] is None
    assert snap4["display_id"] is None
