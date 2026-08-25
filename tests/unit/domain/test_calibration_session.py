"""Phase 6.2 — canonical calibration domain + lifecycle tests."""

import time

import numpy as np
import pytest

from projectionai.domain.calibration import CalibrationResult as LegacyDomainResult
from projectionai.domain.calibration import ProjectorCalibration
from projectionai.domain.calibration_session import (
    CalibrationFrame,
    CalibrationMethod,
    CalibrationPattern,
    CalibrationResult,
    CalibrationSequence,
    CalibrationSession,
    CalibrationSessionStatus,
    CameraCapture,
    CorrespondenceSet,
    PatternAxis,
    ReconstructionResult,
)
from projectionai.domain.geometry import Pose
from projectionai.services.camera import Frame


def _pattern(
    pid: int, seq: str = "seq-1", w: int = 8, h: int = 6
) -> CalibrationPattern:
    img = np.zeros((h, w), dtype=np.uint8)
    return CalibrationPattern(
        pattern_id=pid,
        sequence_id=seq,
        axis=PatternAxis.COLUMN,
        bit_index=0,
        bit_value=1,
        image=img,
        width=w,
        height=h,
    )


def _seq(seq_id: str = "seq-1", w: int = 8, h: int = 6) -> CalibrationSequence:
    p0 = _pattern(0, seq_id, w, h)
    p1 = CalibrationPattern(
        pattern_id=1,
        sequence_id=seq_id,
        axis=PatternAxis.ROW,
        bit_index=0,
        bit_value=0,
        image=np.zeros((h, w), dtype=np.uint8),
        width=w,
        height=h,
    )
    return CalibrationSequence(
        sequence_id=seq_id,
        method=CalibrationMethod.GRAY_CODE,
        patterns=(p0, p1),
        width=w,
        height=h,
        bits_x=1,
        bits_y=1,
    )


def _capture(seq: str = "seq-1", pid: int = 0) -> CameraCapture:
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    return CameraCapture(
        image=img,
        timestamp=time.monotonic(),
        timestamp_ns=time.monotonic_ns(),
        camera_id="cam-0",
        frame_number=1,
        sequence_id=seq,
        pattern_id=pid,
        projector_state=f"pattern_{pid}",
    )


class TestCalibrationPattern:
    def test_valid(self) -> None:
        p = _pattern(0)
        assert p.pattern_id == 0

    def test_invalid_seq(self) -> None:
        with pytest.raises(ValueError, match="sequence_id"):
            CalibrationPattern(
                pattern_id=0,
                sequence_id="",
                axis=PatternAxis.COLUMN,
                bit_index=0,
                bit_value=1,
                image=np.zeros((6, 8), dtype=np.uint8),
                width=8,
                height=6,
            )

    def test_invalid_pattern_id(self) -> None:
        with pytest.raises(ValueError, match="pattern_id"):
            CalibrationPattern(
                pattern_id=-1,
                sequence_id="s",
                axis=PatternAxis.COLUMN,
                bit_index=0,
                bit_value=1,
                image=np.zeros((6, 8), dtype=np.uint8),
                width=8,
                height=6,
            )

    def test_invalid_bit_value(self) -> None:
        with pytest.raises(ValueError, match="bit_value"):
            CalibrationPattern(
                pattern_id=0,
                sequence_id="s",
                axis=PatternAxis.COLUMN,
                bit_index=0,
                bit_value=2,
                image=np.zeros((6, 8), dtype=np.uint8),
                width=8,
                height=6,
            )

    def test_invalid_resolution(self) -> None:
        with pytest.raises(ValueError, match="resolution must be positive"):
            CalibrationPattern(
                pattern_id=0,
                sequence_id="s",
                axis=PatternAxis.COLUMN,
                bit_index=0,
                bit_value=1,
                image=np.zeros((6, 8), dtype=np.uint8),
                width=0,
                height=6,
            )

    def test_invalid_image_shape(self) -> None:
        with pytest.raises(ValueError, match="must be 2D"):
            CalibrationPattern(
                pattern_id=0,
                sequence_id="s",
                axis=PatternAxis.COLUMN,
                bit_index=0,
                bit_value=1,
                image=np.zeros((6, 8, 3), dtype=np.uint8),
                width=8,
                height=6,
            )


class TestCalibrationSequence:
    def test_valid(self) -> None:
        s = _seq()
        assert s.resolution == (8, 6)

    def test_invalid_seq_id(self) -> None:
        with pytest.raises(ValueError, match="sequence_id"):
            CalibrationSequence(
                sequence_id="",
                method=CalibrationMethod.GRAY_CODE,
                patterns=(_pattern(0, "x"),),
                width=8,
                height=6,
                bits_x=1,
                bits_y=0,
            )

    def test_invalid_resolution(self) -> None:
        with pytest.raises(ValueError, match="resolution must be positive"):
            CalibrationSequence(
                sequence_id="s",
                method=CalibrationMethod.GRAY_CODE,
                patterns=(_pattern(0, "s"),),
                width=0,
                height=6,
                bits_x=1,
                bits_y=0,
            )

    def test_mismatched_bits(self) -> None:
        with pytest.raises(ValueError, match="bits_x\\+bits_y"):
            CalibrationSequence(
                sequence_id="s",
                method=CalibrationMethod.GRAY_CODE,
                patterns=(_pattern(0, "s"),),
                width=8,
                height=6,
                bits_x=2,
                bits_y=1,
            )

    def test_duplicate_pattern_id(self) -> None:
        p0 = _pattern(0, "s")
        p1 = _pattern(0, "s")
        with pytest.raises(ValueError, match="duplicate pattern_id"):
            CalibrationSequence(
                sequence_id="s",
                method=CalibrationMethod.GRAY_CODE,
                patterns=(p0, p1),
                width=8,
                height=6,
                bits_x=1,
                bits_y=1,
            )

    def test_pattern_seq_mismatch(self) -> None:
        p0 = _pattern(0, "a")
        p1 = CalibrationPattern(
            pattern_id=1,
            sequence_id="b",
            axis=PatternAxis.ROW,
            bit_index=0,
            bit_value=0,
            image=np.zeros((6, 8), dtype=np.uint8),
            width=8,
            height=6,
        )
        with pytest.raises(ValueError, match="sequence_id"):
            CalibrationSequence(
                sequence_id="a",
                method=CalibrationMethod.GRAY_CODE,
                patterns=(p0, p1),
                width=8,
                height=6,
                bits_x=1,
                bits_y=1,
            )

    def test_empty_patterns(self) -> None:
        with pytest.raises(ValueError, match="at least one pattern"):
            CalibrationSequence(
                sequence_id="s",
                method=CalibrationMethod.GRAY_CODE,
                patterns=(),
                width=8,
                height=6,
                bits_x=0,
                bits_y=0,
            )


class TestCameraCapture:
    def test_valid(self) -> None:
        c = _capture()
        assert c.width == 4

    def test_invalid_image(self) -> None:
        with pytest.raises(ValueError, match="must be \\(H,W,3\\)"):
            CameraCapture(
                image=np.zeros((4, 4), dtype=np.uint8),
                timestamp=0.0,
                timestamp_ns=0,
                camera_id="c",
                frame_number=0,
                sequence_id="",
                pattern_id=-1,
                projector_state="unknown",
            )

    def test_invalid_pattern_id(self) -> None:
        with pytest.raises(ValueError, match="pattern_id"):
            CameraCapture(
                image=np.zeros((4, 4, 3), dtype=np.uint8),
                timestamp=0.0,
                timestamp_ns=0,
                camera_id="c",
                frame_number=0,
                sequence_id="s",
                pattern_id=-2,
                projector_state="unknown",
            )

    def test_invalid_timestamp_ns(self) -> None:
        with pytest.raises(ValueError, match="timestamp_ns"):
            CameraCapture(
                image=np.zeros((4, 4, 3), dtype=np.uint8),
                timestamp=0.0,
                timestamp_ns=-1,
                camera_id="c",
                frame_number=0,
                sequence_id="",
                pattern_id=-1,
                projector_state="unknown",
            )

    def test_frame_adapter(self) -> None:
        f = Frame(
            image=np.zeros((4, 4, 3), dtype=np.uint8),
            timestamp=1.0,
            timestamp_ns=12345,
            camera_id="cam",
            frame_number=2,
            sequence_id="seq-1",
            pattern_id=5,
        )
        cc = f.to_camera_capture()
        assert cc.sequence_id == "seq-1"
        assert cc.pattern_id == 5
        assert cc.timestamp_ns == 12345


class TestCalibrationFrame:
    def test_valid_pairing(self) -> None:
        cap = _capture("seq-1", 0)
        pat = _pattern(0, "seq-1")
        cf = CalibrationFrame(capture=cap, pattern=pat)
        assert cf.capture.pattern_id == 0

    def test_mismatched_sequence(self) -> None:
        cap = _capture("seq-1", 0)
        pat = _pattern(0, "seq-2")
        with pytest.raises(ValueError, match="sequence_id mismatch"):
            CalibrationFrame(capture=cap, pattern=pat)

    def test_mismatched_pattern_id(self) -> None:
        cap = _capture("seq-1", 0)
        pat = _pattern(1, "seq-1")
        with pytest.raises(ValueError, match="pattern_id mismatch"):
            CalibrationFrame(capture=cap, pattern=pat)


class TestCorrespondenceSet:
    def _valid(self) -> CorrespondenceSet:
        h, w = 4, 4
        return CorrespondenceSet(
            projector_x=np.zeros((h, w), dtype=np.float32),
            projector_y=np.zeros((h, w), dtype=np.float32),
            mask=np.zeros((h, w), dtype=np.bool_),
            image_size=(w, h),
            projector_resolution=(8, 6),
            sequence_id="seq-1",
        )

    def test_valid(self) -> None:
        cs = self._valid()
        assert cs.num_correspondences == 0

    def test_invalid_image_size(self) -> None:
        with pytest.raises(ValueError, match="image_size must be positive"):
            CorrespondenceSet(
                projector_x=np.zeros((4, 4), dtype=np.float32),
                projector_y=np.zeros((4, 4), dtype=np.float32),
                mask=np.zeros((4, 4), dtype=np.bool_),
                image_size=(0, 4),
                projector_resolution=(8, 6),
                sequence_id="s",
            )

    def test_invalid_projector_resolution(self) -> None:
        with pytest.raises(ValueError, match="projector_resolution must be positive"):
            CorrespondenceSet(
                projector_x=np.zeros((4, 4), dtype=np.float32),
                projector_y=np.zeros((4, 4), dtype=np.float32),
                mask=np.zeros((4, 4), dtype=np.bool_),
                image_size=(4, 4),
                projector_resolution=(0, 6),
                sequence_id="s",
            )

    def test_invalid_mask_shape(self) -> None:
        with pytest.raises(ValueError, match="mask shape"):
            CorrespondenceSet(
                projector_x=np.zeros((4, 4), dtype=np.float32),
                projector_y=np.zeros((4, 4), dtype=np.float32),
                mask=np.zeros((2, 2), dtype=np.bool_),
                image_size=(4, 4),
                projector_resolution=(8, 6),
                sequence_id="s",
            )

    def test_invalid_valid_ratio(self) -> None:
        with pytest.raises(ValueError, match="valid_ratio"):
            CorrespondenceSet(
                projector_x=np.zeros((4, 4), dtype=np.float32),
                projector_y=np.zeros((4, 4), dtype=np.float32),
                mask=np.zeros((4, 4), dtype=np.bool_),
                image_size=(4, 4),
                projector_resolution=(8, 6),
                sequence_id="s",
                valid_ratio=2.0,
            )


class TestReconstructionResult:
    def test_valid(self) -> None:
        r = ReconstructionResult(
            points_camera=np.zeros((2, 3), dtype=np.float64),
            projector_pixels=np.zeros((2, 2), dtype=np.float64),
            sequence_id="s",
        )
        assert len(r.points_camera) == 2

    def test_mismatched_len(self) -> None:
        with pytest.raises(ValueError, match="len mismatch"):
            ReconstructionResult(
                points_camera=np.zeros((2, 3), dtype=np.float64),
                projector_pixels=np.zeros((3, 2), dtype=np.float64),
                sequence_id="s",
            )

    def test_empty(self) -> None:
        with pytest.raises(ValueError, match="at least one point"):
            ReconstructionResult(
                points_camera=np.zeros((0, 3), dtype=np.float64),
                projector_pixels=np.zeros((0, 2), dtype=np.float64),
                sequence_id="s",
            )

    def test_invalid_normals(self) -> None:
        with pytest.raises(ValueError, match="normals shape"):
            ReconstructionResult(
                points_camera=np.zeros((2, 3), dtype=np.float64),
                projector_pixels=np.zeros((2, 2), dtype=np.float64),
                sequence_id="s",
                normals=np.zeros((2, 2), dtype=np.float64),
            )

    def test_invalid_sequence(self) -> None:
        with pytest.raises(ValueError, match="sequence_id"):
            ReconstructionResult(
                points_camera=np.zeros((1, 3), dtype=np.float64),
                projector_pixels=np.zeros((1, 2), dtype=np.float64),
                sequence_id="",
            )


class TestCalibrationResult:
    def _valid(self) -> CalibrationResult:
        return CalibrationResult(
            calibration_id="cal-1",
            sequence_id="seq-1",
            method=CalibrationMethod.GRAY_CODE,
            projector_id="proj-1",
            camera_id="cam-0",
            surface_id="surf-1",
            projector_intrinsics=np.eye(3, dtype=np.float64),
            projector_pose=np.eye(4, dtype=np.float64),
            projector_resolution=(1920, 1080),
            reprojection_error=0.5,
            coverage=0.8,
            num_correspondences=100,
            confidence=0.9,
        )

    def test_valid(self) -> None:
        r = self._valid()
        assert r.coverage == 0.8

    def test_invalid_resolution(self) -> None:
        with pytest.raises(ValueError, match="projector_resolution must be positive"):
            CalibrationResult(
                calibration_id="c",
                sequence_id="s",
                method=CalibrationMethod.GRAY_CODE,
                projector_id="p",
                camera_id="c",
                surface_id="",
                projector_intrinsics=np.eye(3),
                projector_pose=np.eye(4),
                projector_resolution=(0, 1080),
                reprojection_error=0,
                coverage=0.5,
                num_correspondences=10,
                confidence=0.5,
            )

    def test_invalid_reprojection(self) -> None:
        with pytest.raises(ValueError, match="reprojection_error"):
            CalibrationResult(
                calibration_id="c",
                sequence_id="s",
                method=CalibrationMethod.GRAY_CODE,
                projector_id="p",
                camera_id="c",
                surface_id="",
                projector_intrinsics=np.eye(3),
                projector_pose=np.eye(4),
                projector_resolution=(1920, 1080),
                reprojection_error=-1,
                coverage=0.5,
                num_correspondences=10,
                confidence=0.5,
            )

    def test_invalid_coverage(self) -> None:
        with pytest.raises(ValueError, match="coverage must be in"):
            CalibrationResult(
                calibration_id="c",
                sequence_id="s",
                method=CalibrationMethod.GRAY_CODE,
                projector_id="p",
                camera_id="c",
                surface_id="",
                projector_intrinsics=np.eye(3),
                projector_pose=np.eye(4),
                projector_resolution=(1920, 1080),
                reprojection_error=0,
                coverage=1.5,
                num_correspondences=10,
                confidence=0.5,
            )

    def test_invalid_confidence(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            CalibrationResult(
                calibration_id="c",
                sequence_id="s",
                method=CalibrationMethod.GRAY_CODE,
                projector_id="p",
                camera_id="c",
                surface_id="",
                projector_intrinsics=np.eye(3),
                projector_pose=np.eye(4),
                projector_resolution=(1920, 1080),
                reprojection_error=0,
                coverage=0.5,
                num_correspondences=10,
                confidence=2.0,
            )

    def test_invalid_intrinsics_shape(self) -> None:
        with pytest.raises(ValueError, match="3x3"):
            CalibrationResult(
                calibration_id="c",
                sequence_id="s",
                method=CalibrationMethod.GRAY_CODE,
                projector_id="p",
                camera_id="c",
                surface_id="",
                projector_intrinsics=np.eye(2),
                projector_pose=np.eye(4),
                projector_resolution=(1920, 1080),
                reprojection_error=0,
                coverage=0.5,
                num_correspondences=10,
                confidence=0.5,
            )


class TestCalibrationSessionLifecycle:
    def test_initial_created(self) -> None:
        s = CalibrationSession()
        assert s.status == CalibrationSessionStatus.CREATED

    def test_transition_path(self) -> None:
        s = CalibrationSession()
        s.transition(CalibrationSessionStatus.PREPARING)
        s.transition(CalibrationSessionStatus.CAPTURING)
        s.transition(CalibrationSessionStatus.PROCESSING)
        s.transition(CalibrationSessionStatus.SOLVING)
        s.transition(CalibrationSessionStatus.VALIDATING)
        s.transition(CalibrationSessionStatus.COMPLETED)
        assert s.status == CalibrationSessionStatus.COMPLETED

    def test_invalid_transition(self) -> None:
        s = CalibrationSession()
        with pytest.raises(ValueError, match="Invalid transition"):
            s.transition(CalibrationSessionStatus.COMPLETED)

    def test_idempotent(self) -> None:
        s = CalibrationSession(status=CalibrationSessionStatus.PREPARING)
        s.transition(CalibrationSessionStatus.PREPARING)
        assert s.status == CalibrationSessionStatus.PREPARING

    def test_add_frame_requires_sequence(self) -> None:
        s = CalibrationSession()
        cap = _capture("seq-1", 0)
        pat = _pattern(0, "seq-1")
        cf = CalibrationFrame(capture=cap, pattern=pat)
        with pytest.raises(ValueError, match="sequence must be set"):
            s.add_frame(cf)

    def test_add_frame_seq_mismatch(self) -> None:
        s = CalibrationSession(sequence=_seq("seq-1"))
        cap = _capture("seq-2", 0)
        pat = _pattern(0, "seq-2")
        cf = CalibrationFrame(capture=cap, pattern=pat)
        with pytest.raises(ValueError, match="sequence_id mismatch"):
            s.add_frame(cf)


class TestSerialization:
    def test_sequence_roundtrip(self) -> None:
        seq = _seq("seq-rt")
        d = seq.to_dict()
        seq2 = CalibrationSequence.from_dict(d)
        assert seq2.sequence_id == seq.sequence_id
        assert len(seq2.patterns) == 2

    def test_result_roundtrip(self) -> None:
        r = CalibrationResult(
            calibration_id="cal-rt",
            sequence_id="seq-rt",
            method=CalibrationMethod.GRAY_CODE,
            projector_id="proj-1",
            camera_id="cam-0",
            surface_id="",
            projector_intrinsics=np.eye(3),
            projector_pose=np.eye(4),
            projector_resolution=(640, 480),
            reprojection_error=1.0,
            coverage=0.5,
            num_correspondences=10,
            confidence=0.8,
            per_point_errors=(0.1, 0.2),
            image_size=(640, 480),
        )
        d = r.to_dict()
        r2 = CalibrationResult.from_dict(d)
        assert r2.calibration_id == "cal-rt"
        assert r2.per_point_errors == (0.1, 0.2)

    def test_session_roundtrip(self) -> None:
        seq = _seq("seq-sess")
        s = CalibrationSession(
            session_id="sess-1", sequence=seq, projector_id="p1", camera_id="c1"
        )
        d = s.to_dict()
        s2 = CalibrationSession.from_dict(d)
        assert s2.session_id == "sess-1"
        assert s2.sequence is not None and s2.sequence.sequence_id == "seq-sess"

    def test_legacy_domain_conversion(self) -> None:
        legacy = LegacyDomainResult(
            object_pose=Pose(),
            projectors=(
                ProjectorCalibration(
                    projector_id="p1",
                    pose=Pose(),
                    resolution_width=800,
                    resolution_height=600,
                    fov_degrees=60,
                ),
            ),
            reprojection_error=0.7,
            confidence=0.9,
            metadata={"sequence_id": "seq-legacy", "camera_pose": np.eye(4).tolist()},
        )
        canon = legacy.to_canonical()
        assert canon.projector_id == "p1"
        assert canon.reprojection_error == 0.7
        legacy2 = LegacyDomainResult.from_canonical(canon)
        assert legacy2.projectors[0].projector_id == "p1"

    def test_to_canonical_requires_camera_pose(self) -> None:
        from projectionai.domain.calibration import (
            CalibrationResult as LegacyDomainResult,
        )
        from projectionai.domain.geometry import Pose

        legacy = LegacyDomainResult(
            projectors=(
                ProjectorCalibration(
                    projector_id="p1",
                    pose=Pose(),
                    resolution_width=800,
                    resolution_height=600,
                    fov_degrees=60,
                ),
            ),
            reprojection_error=0.7,
            confidence=0.9,
            metadata={"sequence_id": "seq-legacy"},
        )
        with pytest.raises(ValueError, match="camera pose unknown"):
            legacy.to_canonical()
        # Known camera pose composes correctly: camera at world origin, projector at (1,0,0) world -> projector->camera = projector->world
        cam_pose = np.eye(4)
        cam_pose[0, 3] = 5.0  # camera at (5,0,0) world
        proj_pose = np.eye(4)
        proj_pose[0, 3] = 1.0  # projector at (1,0,0) world
        from projectionai.domain.geometry import Vec3

        legacy2 = LegacyDomainResult(
            projectors=(
                ProjectorCalibration(
                    projector_id="p1",
                    pose=Pose(position=Vec3(1, 0, 0)),
                    resolution_width=800,
                    resolution_height=600,
                    fov_degrees=60,
                ),
            ),
            reprojection_error=0.7,
            confidence=0.9,
            metadata={"sequence_id": "seq-legacy", "camera_pose": cam_pose.tolist()},
        )
        canon2 = legacy2.to_canonical()
        # projector->camera = inv(camera->world) @ projector->world = inv(T_cam) @ T_proj
        # With cam at (5,0,0) and proj at (1,0,0): expected projector->camera translation = -4 on X
        assert canon2.projector_pose[0, 3] == pytest.approx(-4.0, abs=1e-9)

    def test_legacy_types_conversion(self) -> None:
        from projectionai.calibration.types import (
            CalibrationData,
            calibration_result_to_canonical,
            canonical_to_legacy_result,
        )
        from projectionai.calibration.types import (
            CalibrationMethod as LegacyMethod,
        )
        from projectionai.calibration.types import CalibrationResult as LegacyResult

        data = CalibrationData(
            projector_pose={
                "proj-1": {
                    "pose": np.eye(4).tolist(),
                    "projector_matrix": np.eye(3).tolist(),
                    "width": 640,
                    "height": 480,
                }
            },
            confidence=0.8,
            reprojection_error=0.5,
            num_samples=20,
            method=LegacyMethod.GRAY_CODE,
            custom={"sequence_id": "seq-x", "coverage": 0.6},
        )
        legacy = LegacyResult(success=True, data=data, quality_score=0.8)
        canon = calibration_result_to_canonical(legacy)
        assert canon.coverage == 0.6
        legacy2 = canonical_to_legacy_result(canon)
        assert legacy2.success is True
        assert legacy2.data is not None

    def test_canonical_to_warp_mesh(self) -> None:
        from projectionai.services.calibration import calibration_to_warp_mesh

        canon = CalibrationResult(
            calibration_id="c1",
            sequence_id="s1",
            method=CalibrationMethod.GRAY_CODE,
            projector_id="proj-1",
            camera_id="cam-0",
            surface_id="",
            projector_intrinsics=np.array(
                [[1000, 0, 320], [0, 1000, 240], [0, 0, 1]], dtype=np.float64
            ),
            projector_pose=np.eye(4, dtype=np.float64),
            projector_resolution=(640, 480),
            reprojection_error=0.5,
            coverage=0.5,
            num_correspondences=10,
            confidence=0.9,
        )
        # Place projector looking at origin from z=2
        canon = CalibrationResult(
            calibration_id=canon.calibration_id,
            sequence_id=canon.sequence_id,
            method=canon.method,
            projector_id=canon.projector_id,
            camera_id=canon.camera_id,
            surface_id=canon.surface_id,
            projector_intrinsics=canon.projector_intrinsics,
            projector_pose=np.array(
                [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -2], [0, 0, 0, 1]],
                dtype=np.float64,
            ),
            projector_resolution=canon.projector_resolution,
            reprojection_error=canon.reprojection_error,
            coverage=canon.coverage,
            num_correspondences=canon.num_correspondences,
            confidence=canon.confidence,
        )
        mesh = calibration_to_warp_mesh(
            canon, surface_width_m=0.5, surface_height_m=0.3
        )
        assert mesh.has_content
        assert not mesh.validate()

    def test_importer_canonical(self) -> None:
        from projectionai.calibration.importer import RawJsonImporter

        canon = CalibrationResult(
            calibration_id="c2",
            sequence_id="s2",
            method=CalibrationMethod.GRAY_CODE,
            projector_id="proj-1",
            camera_id="cam-0",
            surface_id="",
            projector_intrinsics=np.eye(3),
            projector_pose=np.eye(4),
            projector_resolution=(640, 480),
            reprojection_error=0.2,
            coverage=0.7,
            num_correspondences=5,
            confidence=0.9,
        )
        imp = RawJsonImporter()
        legacy = imp.import_data(canon.to_dict())
        assert legacy.success is True
