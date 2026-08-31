"""Tests for calibration persistence — save/load/checksum/atomic write.

Covers:
- Save/load round-trip for CalibrationResult, WarpMesh, ProjectionMapping
- Checksum verification (valid, corrupted, missing)
- Schema version check
- Atomic write (no temp files remain after successful write)
- Overwrite guard
- Compatibility checks via CalibrationRecall
- History persistence via CalibrationHistoryStore
- Filesystem safety
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from projectionai.calibration._persistence_utils import (
    compute_checksum,
    verify_checksum,
)
from projectionai.calibration.history import CalibrationHistory
from projectionai.calibration.history_store import CalibrationHistoryStore
from projectionai.calibration.persistence import (
    SCHEMA_VERSION,
    CalibrationPersistence,
    CompatibilityError,
    IntegrityError,
    PersistenceError,
    SchemaVersionError,
)
from projectionai.calibration.recall import CalibrationRecall
from projectionai.calibration.types import (
    CalibrationData,
    CalibrationResult,
)
from projectionai.calibration.types import (
    CalibrationMethod as LegacyCalibrationMethod,
)
from projectionai.domain.calibration_session import (
    CalibrationMethod,
)
from projectionai.domain.calibration_session import (
    CalibrationResult as CanonicalCalibrationResult,
)
from projectionai.domain.projection import ProjectionMapping
from projectionai.domain.warp_mesh import WarpMesh, WarpMeshGeneration

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_canonical_result(
    *,
    calibration_id: str = "cal_001",
    projector_id: str = "proj_001",
    camera_id: str = "cam_001",
    surface_id: str = "surf_001",
) -> CanonicalCalibrationResult:
    """Create a minimal valid canonical CalibrationResult."""
    return CanonicalCalibrationResult(
        calibration_id=calibration_id,
        sequence_id="seq_001",
        method=CalibrationMethod.MANUAL,
        projector_id=projector_id,
        camera_id=camera_id,
        surface_id=surface_id,
        projector_intrinsics=np.eye(3, dtype=np.float64),
        projector_pose=np.eye(4, dtype=np.float64),
        projector_resolution=(1920, 1080),
        reprojection_error=0.5,
        coverage=0.85,
        num_correspondences=100,
        confidence=0.9,
    )


def _make_warp_mesh(
    *,
    surface_id: str = "surf_001",
    projector_id: str = "proj_001",
) -> WarpMesh:
    """Create a minimal valid WarpMesh."""
    return WarpMesh(
        surface_id=surface_id,
        projector_id=projector_id,
        vertices=np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float64,
        ),
        projector_uvs=np.array(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            dtype=np.float64,
        ),
        content_uvs=np.array(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            dtype=np.float64,
        ),
        indices=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32),
        grid_rows=2,
        grid_cols=2,
        generation_method=WarpMeshGeneration.GRID,
    )


def _make_projection_mapping(
    *,
    projector_id: str = "proj_001",
    surface_id: str = "surf_001",
    calibration_id: str = "cal_001",
) -> ProjectionMapping:
    """Create a minimal valid ProjectionMapping."""
    return ProjectionMapping(
        id="proj_map_001",
        name="Test Mapping",
        projector_id=projector_id,
        surface_id=surface_id,
        calibration_id=calibration_id,
    )


def _make_legacy_result(
    quality: float = 0.8, method: str = "manual"
) -> CalibrationResult:
    """Create a legacy CalibrationResult for history tests."""
    return CalibrationResult(
        success=True,
        data=CalibrationData(
            method=LegacyCalibrationMethod(method),
            confidence=0.9,
        ),
        quality_score=quality,
    )


# ---------------------------------------------------------------------------
# Checksum tests
# ---------------------------------------------------------------------------


class TestChecksum:
    def testcompute_checksum_deterministic(self) -> None:
        data = {"key": "value", "nested": [1, 2, 3]}
        cs1 = compute_checksum(data)
        cs2 = compute_checksum(data)
        assert cs1 == cs2
        assert len(cs1) == 64  # SHA-256 hex

    def testverify_checksum_valid(self) -> None:
        data = {"key": "value"}
        cs = compute_checksum(data)
        assert verify_checksum(data, cs) is True

    def testverify_checksum_invalid(self) -> None:
        data = {"key": "value"}
        assert verify_checksum(data, "bad_checksum") is False

    def test_checksum_differs_for_different_data(self) -> None:
        cs1 = compute_checksum({"a": 1})
        cs2 = compute_checksum({"a": 2})
        assert cs1 != cs2


# ---------------------------------------------------------------------------
# CalibrationPersistence — save/load round-trip
# ---------------------------------------------------------------------------


class TestCalibrationPersistence:
    def test_save_load_roundtrip_minimal(self, tmp_path: Path) -> None:
        """Save and load a CalibrationResult without optional assets."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()

        persistence.save(tmp_path, calibration_result=result)
        bundle = persistence.load(tmp_path)

        assert bundle.calibration.calibration_id == "cal_001"
        assert bundle.calibration.projector_id == "proj_001"
        assert bundle.warp_mesh is None
        assert bundle.projection is None

    def test_save_load_roundtrip_with_warp_mesh(self, tmp_path: Path) -> None:
        """Save and load with WarpMesh."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        mesh = _make_warp_mesh()

        persistence.save(tmp_path, calibration_result=result, warp_mesh=mesh)
        bundle = persistence.load(tmp_path)

        assert bundle.warp_mesh is not None
        assert bundle.warp_mesh.surface_id == "surf_001"
        assert bundle.warp_mesh.num_vertices == 4

    def test_save_load_roundtrip_with_projection(self, tmp_path: Path) -> None:
        """Save and load with ProjectionMapping."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        proj = _make_projection_mapping()

        persistence.save(tmp_path, calibration_result=result, projection_mapping=proj)
        bundle = persistence.load(tmp_path)

        assert bundle.projection is not None
        assert bundle.projection.id == "proj_map_001"

    def test_save_load_roundtrip_full(self, tmp_path: Path) -> None:
        """Save and load all three: CalibrationResult + WarpMesh + ProjectionMapping."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        mesh = _make_warp_mesh()
        proj = _make_projection_mapping()

        persistence.save(
            tmp_path,
            calibration_result=result,
            warp_mesh=mesh,
            projection_mapping=proj,
        )
        bundle = persistence.load(tmp_path)

        assert bundle.calibration.calibration_id == "cal_001"
        assert bundle.warp_mesh is not None
        assert bundle.warp_mesh.num_vertices == 4
        assert bundle.projection is not None
        assert bundle.projection.id == "proj_map_001"

    def test_manifest_schema_version(self, tmp_path: Path) -> None:
        """Manifest contains correct schema version."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["schema_version"] == SCHEMA_VERSION

    def test_manifest_has_checksums(self, tmp_path: Path) -> None:
        """Manifest contains checksums for all saved files."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        mesh = _make_warp_mesh()
        persistence.save(tmp_path, calibration_result=result, warp_mesh=mesh)

        manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert "calibration" in manifest["checksums"]
        assert "warp_mesh" in manifest["checksums"]
        assert "projection" not in manifest["checksums"]

    def test_manifest_has_hardware_ids(self, tmp_path: Path) -> None:
        """Manifest stores projector/camera/surface IDs."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["projector_id"] == "proj_001"
        assert manifest["camera_id"] == "cam_001"
        assert manifest["surface_id"] == "surf_001"


# ---------------------------------------------------------------------------
# Overwrite guard
# ---------------------------------------------------------------------------


class TestOverwriteGuard:
    def test_raises_when_overwrite_false(self, tmp_path: Path) -> None:
        """Saving over existing data without overwrite=True raises."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        with pytest.raises(PersistenceError, match="already exists"):
            persistence.save(tmp_path, calibration_result=result)

    def test_overwrite_true_succeeds(self, tmp_path: Path) -> None:
        """Saving with overwrite=True replaces existing data."""
        persistence = CalibrationPersistence()
        result1 = _make_canonical_result(calibration_id="cal_old")
        persistence.save(tmp_path, calibration_result=result1)

        result2 = _make_canonical_result(calibration_id="cal_new")
        persistence.save(tmp_path, calibration_result=result2, overwrite=True)

        bundle = persistence.load(tmp_path)
        assert bundle.calibration.calibration_id == "cal_new"

    def test_overwrite_on_corrupt_manifest(self, tmp_path: Path) -> None:
        """Overwriting a corrupt manifest is allowed even without overwrite=True."""
        persistence = CalibrationPersistence()
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "manifest.json").write_text("not valid json {", encoding="utf-8")

        result = _make_canonical_result()
        # Should not raise — corrupt manifest is treated as no valid data
        persistence.save(tmp_path, calibration_result=result)
        bundle = persistence.load(tmp_path)
        assert bundle.calibration.calibration_id == "cal_001"


# ---------------------------------------------------------------------------
# Integrity / corruption tests
# ---------------------------------------------------------------------------


class TestIntegrity:
    def test_corrupted_calibration_file(self, tmp_path: Path) -> None:
        """Loading a corrupted calibration.json raises IntegrityError."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        # Corrupt the calibration file
        cal_path = tmp_path / "calibration.json"
        cal_path.write_text("CORRUPTED DATA", encoding="utf-8")

        with pytest.raises((IntegrityError, json.JSONDecodeError)):
            persistence.load(tmp_path)

    def test_tampered_calibration_file(self, tmp_path: Path) -> None:
        """Loading a tampered (valid JSON but wrong content) calibration raises IntegrityError."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        # Tamper: change a value but keep valid JSON
        cal_path = tmp_path / "calibration.json"
        data = json.loads(cal_path.read_text(encoding="utf-8"))
        data["projector_id"] = "TAMPERED"
        cal_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(IntegrityError, match="checksum mismatch"):
            persistence.load(tmp_path)

    def test_tampered_warp_mesh_file(self, tmp_path: Path) -> None:
        """Loading a tampered warp_mesh.json raises IntegrityError."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        mesh = _make_warp_mesh()
        persistence.save(tmp_path, calibration_result=result, warp_mesh=mesh)

        # Tamper the warp mesh file
        wm_path = tmp_path / "warp_mesh.json"
        data = json.loads(wm_path.read_text(encoding="utf-8"))
        data["surface_id"] = "TAMPERED"
        wm_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(IntegrityError, match=r"WarpMesh.*checksum mismatch"):
            persistence.load(tmp_path)

    def test_missing_calibration_file(self, tmp_path: Path) -> None:
        """Loading with missing calibration.json raises FileNotFoundError."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        # Delete the calibration file
        (tmp_path / "calibration.json").unlink()

        with pytest.raises(FileNotFoundError):
            persistence.load(tmp_path)

    def test_missing_manifest(self, tmp_path: Path) -> None:
        """Loading with missing manifest raises FileNotFoundError."""
        persistence = CalibrationPersistence()
        with pytest.raises(FileNotFoundError, match="No manifest"):
            persistence.load(tmp_path)


# ---------------------------------------------------------------------------
# Schema version tests
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_future_schema_version_raises(self, tmp_path: Path) -> None:
        """Loading data with a newer schema version raises SchemaVersionError."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        # Tamper: set schema version to future
        manifest_path = tmp_path / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = SCHEMA_VERSION + 100
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with pytest.raises(SchemaVersionError, match="newer than supported"):
            persistence.load(tmp_path)


# ---------------------------------------------------------------------------
# CalibrationRecall — compatibility checks
# ---------------------------------------------------------------------------


class TestCalibrationRecall:
    def test_recall_matching_ids(self, tmp_path: Path) -> None:
        """Recall with matching expected IDs returns no warnings."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        recall = CalibrationRecall()
        rr = recall.recall(
            tmp_path,
            expected_projector_id="proj_001",
            expected_camera_id="cam_001",
            expected_surface_id="surf_001",
        )
        assert rr.warnings == []
        assert rr.calibration.calibration_id == "cal_001"

    def test_recall_mismatched_projector(self, tmp_path: Path) -> None:
        """Recall with wrong projector_id produces a warning."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        recall = CalibrationRecall()
        rr = recall.recall(
            tmp_path,
            expected_projector_id="WRONG_PROJECTOR",
        )
        assert len(rr.warnings) == 1
        assert "Projector mismatch" in rr.warnings[0]

    def test_recall_mismatched_camera(self, tmp_path: Path) -> None:
        """Recall with wrong camera_id produces a warning."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        recall = CalibrationRecall()
        rr = recall.recall(
            tmp_path,
            expected_camera_id="WRONG_CAMERA",
        )
        assert len(rr.warnings) == 1
        assert "Camera mismatch" in rr.warnings[0]

    def test_recall_mismatched_surface(self, tmp_path: Path) -> None:
        """Recall with wrong surface_id produces a warning."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        recall = CalibrationRecall()
        rr = recall.recall(
            tmp_path,
            expected_surface_id="WRONG_SURFACE",
        )
        assert len(rr.warnings) == 1
        assert "Surface mismatch" in rr.warnings[0]

    def test_recall_multiple_mismatches(self, tmp_path: Path) -> None:
        """Recall with multiple wrong IDs produces multiple warnings."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        recall = CalibrationRecall()
        rr = recall.recall(
            tmp_path,
            expected_projector_id="WRONG_P",
            expected_camera_id="WRONG_C",
            expected_surface_id="WRONG_S",
        )
        assert len(rr.warnings) == 3

    def test_recall_strict_raises_on_mismatch(self, tmp_path: Path) -> None:
        """recall_strict raises CompatibilityError on any mismatch."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        recall = CalibrationRecall()
        with pytest.raises(CompatibilityError, match="compatibility failures"):
            recall.recall_strict(
                tmp_path,
                expected_projector_id="WRONG",
                expected_camera_id="cam_001",
                expected_surface_id="surf_001",
            )

    def test_recall_strict_succeeds_on_match(self, tmp_path: Path) -> None:
        """recall_strict succeeds when all IDs match."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        recall = CalibrationRecall()
        rr = recall.recall_strict(
            tmp_path,
            expected_projector_id="proj_001",
            expected_camera_id="cam_001",
            expected_surface_id="surf_001",
        )
        assert rr.warnings == []

    def test_recall_no_optional_expectations(self, tmp_path: Path) -> None:
        """Recall without expected IDs produces no compatibility warnings."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        recall = CalibrationRecall()
        rr = recall.recall(tmp_path)
        assert rr.warnings == []

    def test_recall_preserves_warp_mesh(self, tmp_path: Path) -> None:
        """Recall returns the WarpMesh when present."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        mesh = _make_warp_mesh()
        persistence.save(tmp_path, calibration_result=result, warp_mesh=mesh)

        recall = CalibrationRecall()
        rr = recall.recall(tmp_path)
        assert rr.warp_mesh is not None
        assert rr.warp_mesh.num_vertices == 4


# ---------------------------------------------------------------------------
# CalibrationHistoryStore
# ---------------------------------------------------------------------------


class TestCalibrationHistoryStore:
    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        """Save and load calibration history."""
        store = CalibrationHistoryStore()
        history = CalibrationHistory(max_entries=10)
        history.add_entry(_make_legacy_result(quality=0.9))
        history.add_entry(_make_legacy_result(quality=0.7))

        store.save(history, tmp_path)
        restored = store.load(tmp_path)

        assert restored.count == 2
        assert restored.max_entries == 10
        # Entries are newest-first
        assert restored.entries[0].result.quality_score == 0.7
        assert restored.entries[1].result.quality_score == 0.9

    def test_save_load_empty_history(self, tmp_path: Path) -> None:
        """Save and load an empty history."""
        store = CalibrationHistoryStore()
        history = CalibrationHistory()

        store.save(history, tmp_path)
        restored = store.load(tmp_path)

        assert restored.count == 0

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Loading from a directory with no history file returns empty history."""
        store = CalibrationHistoryStore()
        restored = store.load(tmp_path)
        assert restored.count == 0

    def test_checksum_verification(self, tmp_path: Path) -> None:
        """Loading tampered history raises ValueError."""
        store = CalibrationHistoryStore()
        history = CalibrationHistory()
        history.add_entry(_make_legacy_result())

        store.save(history, tmp_path)

        # Tamper the history file
        entries_path = tmp_path / "history" / "entries.json"
        data = json.loads(entries_path.read_text(encoding="utf-8"))
        data["entries"] = []  # Remove entries but keep checksum
        entries_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ValueError, match="checksum mismatch"):
            store.load(tmp_path)

    def test_exists(self, tmp_path: Path) -> None:
        """exists() returns True when history file is present."""
        store = CalibrationHistoryStore()
        assert store.exists(tmp_path) is False

        history = CalibrationHistory()
        store.save(history, tmp_path)
        assert store.exists(tmp_path) is True

    def test_active_entry_preserved(self, tmp_path: Path) -> None:
        """Active entry ID is preserved through save/load."""
        store = CalibrationHistoryStore()
        history = CalibrationHistory()
        history.add_entry(_make_legacy_result(quality=0.5))
        e2 = history.add_entry(_make_legacy_result(quality=0.9))
        # e2 is active (most recent)
        assert history.active_entry_id == e2.id

        store.save(history, tmp_path)
        restored = store.load(tmp_path)
        assert restored.active_entry_id == e2.id


# ---------------------------------------------------------------------------
# Filesystem safety
# ---------------------------------------------------------------------------


class TestFilesystemSafety:
    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        """save() creates the target directory if it doesn't exist."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        target = tmp_path / "nested" / "dir" / "calibration"

        persistence.save(target, calibration_result=result)
        assert target.is_dir()
        assert (target / "manifest.json").exists()

    def test_atomic_write_no_partial_files(self, tmp_path: Path) -> None:
        """After save, no .tmp files remain."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_exists_returns_false_for_empty_dir(self, tmp_path: Path) -> None:
        """exists() returns False for an empty directory."""
        persistence = CalibrationPersistence()
        assert persistence.exists(tmp_path) is False

    def test_exists_returns_true_after_save(self, tmp_path: Path) -> None:
        """exists() returns True after saving."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)
        assert persistence.exists(tmp_path) is True

    def test_get_manifest_returns_none_for_empty_dir(self, tmp_path: Path) -> None:
        """get_manifest() returns None when no manifest exists."""
        persistence = CalibrationPersistence()
        assert persistence.get_manifest(tmp_path) is None

    def test_get_manifest_returns_dict_after_save(self, tmp_path: Path) -> None:
        """get_manifest() returns a dict after saving."""
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)
        manifest = persistence.get_manifest(tmp_path)
        assert manifest is not None
        assert manifest["schema_version"] == SCHEMA_VERSION

    # ---------------------------------------------------------------------------
    # FileLock tests
    # ---------------------------------------------------------------------------
    """Tests for _persistence_utils.atomic_write_json."""

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        from projectionai.calibration._persistence_utils import atomic_write_json

        target = tmp_path / "deep" / "nested" / "file.json"
        atomic_write_json(target, {"hello": "world"})
        assert target.exists()

    def test_atomic_no_temp_files_remain(self, tmp_path: Path) -> None:
        from projectionai.calibration._persistence_utils import atomic_write_json

        target = tmp_path / "data.json"
        atomic_write_json(target, {"step": 1})
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        from projectionai.calibration._persistence_utils import atomic_write_json

        target = tmp_path / "data.json"
        atomic_write_json(target, {"v": 1})
        atomic_write_json(target, {"v": 2})
        import json as _json

        assert _json.loads(target.read_text(encoding="utf-8")) == {"v": 2}


# ---------------------------------------------------------------------------
# FileLock tests
# ---------------------------------------------------------------------------


class TestFileLock:
    """Tests for _persistence_utils.FileLock."""

    def test_acquire_release(self, tmp_path: Path) -> None:
        from projectionai.calibration._persistence_utils import FileLock

        lock = FileLock(tmp_path / ".lock")
        lock.acquire()
        assert (tmp_path / ".lock").exists()
        lock.release()
        assert not (tmp_path / ".lock").exists()

    def test_context_manager(self, tmp_path: Path) -> None:
        from projectionai.calibration._persistence_utils import FileLock

        with FileLock(tmp_path / ".lock"):
            assert (tmp_path / ".lock").exists()
        assert not (tmp_path / ".lock").exists()

    def test_stale_lock_reclaimed(self, tmp_path: Path) -> None:
        from projectionai.calibration._persistence_utils import FileLock

        lock_path = tmp_path / ".lock"
        lock_path.write_text("stale\n", encoding="utf-8")
        # Stale: mtime is now, so set it 120s in the past
        import os
        import time

        old_time = time.time() - 120
        os.utime(str(lock_path), (old_time, old_time))

        with FileLock(lock_path, stale_after=60.0):
            assert lock_path.exists()

    def test_timeout_raises(self, tmp_path: Path) -> None:
        import threading

        from projectionai.calibration._persistence_utils import FileLock

        lock_path = tmp_path / ".lock"
        held = threading.Event()
        proceed = threading.Event()

        def holder():
            with FileLock(lock_path):
                held.set()
                proceed.wait(timeout=5.0)

        t = threading.Thread(target=holder)
        t.start()
        try:
            held.wait(timeout=5.0)

            lock2 = FileLock(lock_path, timeout=0.1)
            with pytest.raises(TimeoutError):
                lock2.acquire()
        finally:
            proceed.set()
            t.join(timeout=5.0)

    def test_concurrent_writes_exclusive(self, tmp_path: Path) -> None:
        import threading

        from projectionai.calibration._persistence_utils import FileLock

        lock_path = tmp_path / ".lock"
        errors: list[Exception] = []
        # Record (entry_time, exit_time) for each critical section
        sections: list[tuple[float, float]] = []
        sections_lock = threading.Lock()

        def writer(val: int, writer_idx: int) -> None:
            try:
                with FileLock(lock_path):
                    import time

                    entry = time.monotonic()
                    with sections_lock:
                        idx = len(sections)
                        sections.append((entry, entry))  # placeholder
                    target = tmp_path / f"result_{val}.txt"
                    target.write_text(str(val), encoding="utf-8")
                    exit_t = time.monotonic()
                    with sections_lock:
                        # Replace this writer's placeholder with actual exit time
                        sections[idx] = (entry, exit_t)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i, i)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert not errors, f"Thread errors: {errors}"
        written = list(tmp_path.glob("result_*.txt"))
        assert len(written) == 3

        # Verify no critical sections overlapped (mutual exclusion)
        sorted_sections = sorted(sections)
        for i in range(1, len(sorted_sections)):
            prev_exit = sorted_sections[i - 1][1]
            curr_entry = sorted_sections[i][0]
            assert curr_entry >= prev_exit, (
                f"Critical sections overlapped: section {i - 1} exited at "
                f"{prev_exit}, section {i} entered at {curr_entry}"
            )

    def test_lock_pid_in_file(self, tmp_path: Path) -> None:
        import os

        from projectionai.calibration._persistence_utils import FileLock

        lock_path = tmp_path / ".lock"
        with FileLock(lock_path):
            content = lock_path.read_text(encoding="utf-8")
            pid_line = content.strip().split("\n")[0]
            assert int(pid_line) == os.getpid()


# ---------------------------------------------------------------------------
# Crash recovery — partial writes don't corrupt existing data
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    """Simulate crash scenarios and verify data integrity is preserved."""

    def test_existing_calibration_survives_failed_overwrite(
        self, tmp_path: Path
    ) -> None:
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        original = persistence.load(tmp_path)
        assert original.calibration.calibration_id == result.calibration_id

        with pytest.raises(PersistenceError):
            persistence.save(tmp_path, calibration_result=result, overwrite=False)

        reloaded = persistence.load(tmp_path)
        assert reloaded.calibration.calibration_id == result.calibration_id

    def test_checksum_catches_truncated_file(self, tmp_path: Path) -> None:
        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)

        cal_path = tmp_path / "calibration.json"
        original = cal_path.read_text(encoding="utf-8")
        cal_path.write_text(original[: len(original) // 2], encoding="utf-8")

        with pytest.raises((IntegrityError, json.JSONDecodeError)):
            persistence.load(tmp_path)

    def test_stale_lock_doesnt_block_save(self, tmp_path: Path) -> None:
        import os
        import time

        lock_path = tmp_path / ".lock"
        lock_path.write_text("orphaned\n", encoding="utf-8")
        old_time = time.time() - 120
        os.utime(str(lock_path), (old_time, old_time))

        persistence = CalibrationPersistence()
        result = _make_canonical_result()
        persistence.save(tmp_path, calibration_result=result)
        assert persistence.exists(tmp_path)

    def test_missing_manifest_dir_not_crash(self, tmp_path: Path) -> None:
        persistence = CalibrationPersistence()
        assert persistence.exists(tmp_path / "nonexistent") is False
        assert persistence.get_manifest(tmp_path / "nonexistent") is None

    def test_load_raises_on_corrupt_entries_file(self, tmp_path: Path) -> None:
        history_dir = tmp_path / "history"
        history_dir.mkdir(parents=True)
        entries_path = history_dir / "entries.json"
        entries_path.write_text("{invalid json", encoding="utf-8")

        store = CalibrationHistoryStore()
        with pytest.raises((ValueError, json.JSONDecodeError)):
            store.load(tmp_path)

    def test_empty_dir_load_raises_file_not_found(self, tmp_path: Path) -> None:
        persistence = CalibrationPersistence()
        with pytest.raises(FileNotFoundError):
            persistence.load(tmp_path)
