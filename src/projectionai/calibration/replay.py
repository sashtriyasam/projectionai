"""Deterministic calibration replay — hardware-free, Qt-free, GL-free.

The replay artifact is a directory:

  artifact/
    manifest.json      # sequence, camera, surface, config, frame checksums
    frames/
      000.npy          # grayscale uint8 capture for pattern 0
      001.npy
      ...

Manifest is JSON with sorted keys (deterministic) and SHA-256 per frame.
Import validates checksums, ordering, sequence/pattern IDs, resolution,
and numeric sanity (NaN/Inf) and fails loudly — no silent repair.

The replay engine runs the same pipeline as live calibration without
importing Qt, QOpenGLWidget, ModernGL, or camera drivers.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.calibration_session import CalibrationSequence

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReplayError(RuntimeError):
    """Raised when a replay artifact is corrupt or replay fails."""


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayArtifact:
    """Validated, in-memory replay artifact."""

    version: int
    sequence: CalibrationSequence
    frames: tuple[NDArray[np.uint8], ...]
    camera_matrix: NDArray[np.float64]
    distortion_coeffs: NDArray[np.float64]
    image_size: tuple[int, int]
    surface_width_m: float
    surface_height_m: float
    surface_normal: NDArray[np.float64]
    surface_offset: float
    grid_rows: int
    grid_cols: int


_REPLAY_VERSION = 2


# ---------------------------------------------------------------------------
# Checksums
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _frame_checksum(frame: NDArray[np.uint8]) -> str:
    return _sha256(np.ascontiguousarray(frame).tobytes())


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_replay_artifact(
    sequence: Any,
    frames: tuple[NDArray[np.uint8], ...],
    camera_matrix: NDArray[np.float64],
    distortion_coeffs: NDArray[np.float64],
    image_size: tuple[int, int],
    surface_width_m: float,
    surface_height_m: float,
    surface_normal: NDArray[np.float64] | None = None,
    surface_offset: float = -2.0,
    grid_rows: int = 16,
    grid_cols: int = 16,
    path: str | Path | None = None,
) -> Path:
    """Export a deterministic replay artifact."""
    if len(frames) != len(sequence.patterns):
        raise ReplayError(
            f"Frame count {len(frames)} != pattern count {len(sequence.patterns)}"
        )
    if camera_matrix.shape != (3, 3):
        raise ReplayError(f"camera_matrix must be 3x3, got {camera_matrix.shape}")
    if distortion_coeffs.shape not in ((4,), (5,), (8,)):
        raise ReplayError(
            f"distortion_coeffs must have shape (4,), (5,), or (8,), got {distortion_coeffs.shape}"
        )
    if surface_width_m <= 0 or surface_height_m <= 0:
        raise ReplayError(
            f"surface dimensions must be positive, got {surface_width_m}x{surface_height_m}"
        )
    normal = (
        np.asarray([0.0, 0.0, 1.0], dtype=np.float64)
        if surface_normal is None
        else np.asarray(surface_normal, dtype=np.float64)
    )
    if normal.shape != (3,) or not np.all(np.isfinite(normal)):
        raise ReplayError(
            f"surface_normal must be a finite (3,) vector, got {normal.shape}"
        )
    n_norm = float(np.linalg.norm(normal))
    if n_norm == 0.0:
        raise ReplayError("surface_normal must be non-zero")
    normal = normal / n_norm
    if grid_rows <= 0 or grid_cols <= 0:
        raise ReplayError(f"grid must be positive, got {grid_rows}x{grid_cols}")
    if image_size[0] <= 0 or image_size[1] <= 0:
        raise ReplayError(f"image_size must be positive, got {image_size}")
    for i, f in enumerate(frames):
        if f.ndim != 2 or f.dtype != np.uint8:
            raise ReplayError(f"Frame {i} must be 2D uint8, got {f.shape} {f.dtype}")
    if not np.all(np.isfinite(camera_matrix)) or not np.all(
        np.isfinite(distortion_coeffs)
    ):
        raise ReplayError("Camera intrinsics contain NaN/Inf")

    out = Path(path) if path is not None else Path(f"replay_{int(time.time() * 1000)}")
    out.mkdir(parents=True, exist_ok=True)
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    checksums: list[str] = []
    for i, f in enumerate(frames):
        arr = np.ascontiguousarray(f, dtype=np.uint8)
        cs = _frame_checksum(arr)
        checksums.append(cs)
        np.save(frames_dir / f"{i:03d}.npy", arr)

    # Support both domain CalibrationSequence and service PatternSequence
    if hasattr(sequence, "to_dict"):
        seq_dict = sequence.to_dict()
    else:
        seq_dict = {
            "sequence_id": getattr(sequence, "sequence_id", "unknown"),
            "method": str(getattr(sequence, "method", "gray_code")),
            "patterns": [
                {
                    "pattern_id": p.spec.pattern_id,
                    "axis": p.spec.axis.value
                    if hasattr(p.spec.axis, "value")
                    else str(p.spec.axis),
                    "bit_index": p.spec.bit_index,
                    "bit_value": p.spec.bit_value,
                    "image": p.image.tolist()
                    if hasattr(p.image, "tolist")
                    else p.image,
                    "width": getattr(sequence, "width", image_size[0]),
                    "height": getattr(sequence, "height", image_size[1]),
                }
                for p in sequence.patterns
            ],
            "width": int(getattr(sequence, "width", image_size[0])),
            "height": int(getattr(sequence, "height", image_size[1])),
            "bits_x": int(getattr(sequence, "bits_x", 0)),
            "bits_y": int(getattr(sequence, "bits_y", 0)),
        }
    manifest: dict[str, object] = {
        "version": _REPLAY_VERSION,
        "sequence": seq_dict,
        "image_size": [int(image_size[0]), int(image_size[1])],
        "camera_matrix": camera_matrix.tolist(),
        "distortion_coeffs": distortion_coeffs.tolist(),
        "surface_width_m": float(surface_width_m),
        "surface_height_m": float(surface_height_m),
        "surface_normal": normal.tolist(),
        "surface_offset": float(surface_offset),
        "grid_rows": int(grid_rows),
        "grid_cols": int(grid_cols),
        "frame_checksums": checksums,
        "frame_count": len(frames),
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    manifest["manifest_checksum"] = _sha256(manifest_bytes)

    (out / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
    )
    return out


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def import_replay_artifact(path: str | Path) -> ReplayArtifact:
    """Import and validate a replay artifact."""
    root = Path(path)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise ReplayError(f"Missing manifest.json in {root}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReplayError(f"Corrupt manifest.json: {exc}") from exc

    stored = manifest.get("manifest_checksum")
    if stored is None:
        raise ReplayError("Missing manifest_checksum")
    check_copy = dict(manifest)
    del check_copy["manifest_checksum"]
    computed = _sha256(json.dumps(check_copy, sort_keys=True).encode())
    if computed != stored:
        raise ReplayError(
            f"Manifest checksum mismatch: expected {stored}, got {computed}"
        )

    try:
        version = int(manifest["version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayError(f"Invalid or missing manifest version: {exc}") from exc
    if version != _REPLAY_VERSION:
        raise ReplayError(
            f"Unsupported replay artifact version {version}; "
            f"only version {_REPLAY_VERSION} is supported. "
            "Older artifacts must be re-exported."
        )

    try:
        sequence = CalibrationSequence.from_dict(manifest["sequence"])
    except Exception as exc:
        raise ReplayError(f"Invalid sequence: {exc}") from exc

    raw_size = manifest["image_size"]
    image_size: tuple[int, int] = (int(raw_size[0]), int(raw_size[1]))
    if image_size[0] <= 0 or image_size[1] <= 0:
        raise ReplayError(f"Invalid image_size: {image_size}")

    frame_count = int(manifest["frame_count"])
    checksums = list(manifest["frame_checksums"])
    if len(checksums) != frame_count:
        raise ReplayError(
            f"Checksum count {len(checksums)} != frame_count {frame_count}"
        )
    if len(checksums) != len(sequence.patterns):
        raise ReplayError(
            f"Checksum count {len(checksums)} != pattern count {len(sequence.patterns)}"
        )

    frames_dir = root / "frames"
    if not frames_dir.exists():
        raise ReplayError(f"Missing frames/ in {root}")

    frames: list[NDArray[np.uint8]] = []
    for i in range(frame_count):
        p = frames_dir / f"{i:03d}.npy"
        if not p.exists():
            raise ReplayError(f"Missing frame {p}")
        try:
            arr = np.load(p)
        except Exception as exc:
            raise ReplayError(f"Corrupt frame {p}: {exc}") from exc
        if arr.ndim != 2 or arr.dtype != np.uint8:
            raise ReplayError(
                f"Frame {i} must be 2D uint8, got {arr.shape} {arr.dtype}"
            )
        if arr.shape != (image_size[1], image_size[0]):
            raise ReplayError(
                f"Frame {i} shape {arr.shape} != image_size {(image_size[1], image_size[0])}"
            )
        actual = _frame_checksum(arr)
        if actual != checksums[i]:
            raise ReplayError(
                f"Frame {i} checksum mismatch: expected {checksums[i]}, got {actual}"
            )
        frames.append(np.ascontiguousarray(arr))

    pids = [p.pattern_id for p in sequence.patterns]
    if len(pids) != len(set(pids)):
        raise ReplayError(f"Duplicated pattern_id in sequence: {pids}")
    if pids != sorted(pids):
        raise ReplayError(f"Pattern IDs not in order: {pids}")

    seq_id = sequence.sequence_id
    if not seq_id:
        raise ReplayError("Empty sequence_id")

    try:
        K = np.array(manifest["camera_matrix"], dtype=np.float64).reshape(3, 3)  # noqa: N806
        dist = np.array(manifest["distortion_coeffs"], dtype=np.float64)
        if dist.shape not in ((4,), (5,), (8,)):
            raise ValueError(f"expected shape (4,), (5,), or (8,), got {dist.shape}")
    except Exception as exc:
        raise ReplayError(f"Invalid camera intrinsics: {exc}") from exc
    if not np.all(np.isfinite(K)) or not np.all(np.isfinite(dist)):
        raise ReplayError("Camera intrinsics contain NaN/Inf")
    if K[0, 0] <= 0 or K[1, 1] <= 0:
        raise ReplayError(f"Invalid focal length in camera_matrix: {K}")

    surface_w = float(manifest["surface_width_m"])
    surface_h = float(manifest["surface_height_m"])
    if surface_w <= 0 or surface_h <= 0:
        raise ReplayError(f"Invalid surface dimensions: {surface_w}x{surface_h}")

    try:
        surface_normal = np.array(manifest["surface_normal"], dtype=np.float64).reshape(
            3
        )
        surface_offset = float(manifest["surface_offset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayError(f"Invalid surface plane in manifest: {exc}") from exc
    if not np.all(np.isfinite(surface_normal)):
        raise ReplayError("surface_normal contains NaN/Inf")
    n_norm = float(np.linalg.norm(surface_normal))
    if n_norm == 0.0:
        raise ReplayError("surface_normal must be non-zero")
    surface_normal = surface_normal / n_norm

    grid_rows = int(manifest["grid_rows"])
    grid_cols = int(manifest["grid_cols"])

    return ReplayArtifact(
        version=version,
        sequence=sequence,
        frames=tuple(frames),
        camera_matrix=np.ascontiguousarray(K),
        distortion_coeffs=np.ascontiguousarray(dist),
        image_size=image_size,
        surface_width_m=surface_w,
        surface_height_m=surface_h,
        surface_normal=np.ascontiguousarray(surface_normal),
        surface_offset=surface_offset,
        grid_rows=grid_rows,
        grid_cols=grid_cols,
    )


# ---------------------------------------------------------------------------
# Replay engine — no Qt / GL / camera deps
# ---------------------------------------------------------------------------


@dataclass
class ReplayResult:
    """Deterministic result of a replay."""

    correspondence_mask: NDArray[np.bool_]
    projector_x: NDArray[np.float32]
    projector_y: NDArray[np.float32]
    points_camera: NDArray[np.float64]
    projector_pixels: NDArray[np.float64]
    intrinsics: NDArray[np.float64]
    pose: NDArray[np.float64]
    reprojection_rms: float
    coverage: float
    warp_projector_uvs: NDArray[np.float64]
    warp_content_uvs: NDArray[np.float64]
    warp_indices: NDArray[np.int32]
    timings_ms: dict[str, float] = field(default_factory=dict)
    peak_ram_mb: float = 0.0


class CalibrationReplay:
    """Hardware-free deterministic replay: decode → recon → solve → warp."""

    def replay(self, artifact: ReplayArtifact) -> ReplayResult:
        """Execute the full pipeline deterministically."""
        import tracemalloc

        was_tracing = tracemalloc.is_tracing()
        if not was_tracing:
            tracemalloc.start()
        _ = tracemalloc.get_traced_memory()
        timings: dict[str, float] = {}

        # --- Decode ---
        t0 = time.perf_counter()
        from projectionai.infrastructure.projector_calibration.correspondence import (
            CorrespondenceMatcher,
        )
        from projectionai.services.projector_calibration import PatternSequence
        from projectionai.services.projector_calibration import PatternSpec as SvcSpec
        from projectionai.services.projector_calibration import (
            StructuredLightPattern as SvcPattern,
        )

        svc_patterns = tuple(
            SvcPattern(
                spec=SvcSpec(
                    pattern_id=p.pattern_id,
                    axis=p.axis.value,  # type: ignore[arg-type]
                    bit_index=p.bit_index,
                    bit_value=p.bit_value,
                ),
                image=p.image,
            )
            for p in artifact.sequence.patterns
        )
        svc_seq = PatternSequence(
            patterns=svc_patterns,
            width=artifact.sequence.width,
            height=artifact.sequence.height,
            bits_x=artifact.sequence.bits_x,
            bits_y=artifact.sequence.bits_y,
        )
        matcher = CorrespondenceMatcher()
        cmap = matcher.decode(artifact.frames, svc_seq)
        timings["decode_ms"] = (time.perf_counter() - t0) * 1000

        # --- Reconstruction ---
        t0 = time.perf_counter()
        from projectionai.domain.calibration_session import CorrespondenceSet
        from projectionai.services.projector_calibration import (
            CalibratedCamera,
            SurfacePlane,
        )
        from projectionai.services.reconstruction import (
            BackendMode,
            ReconstructionBackendFactory,
        )

        proj_x = cmap.projector_x
        proj_y = cmap.projector_y
        mask = cmap.mask
        if np.any(~np.isfinite(proj_x[mask])) or np.any(~np.isfinite(proj_y[mask])):
            raise ReplayError("CorrespondenceMap contains NaN/Inf in valid region")
        corr = CorrespondenceSet(
            projector_x=proj_x,
            projector_y=proj_y,
            mask=mask,
            image_size=cmap.image_size,
            projector_resolution=(
                artifact.sequence.width,
                artifact.sequence.height,
            ),
            sequence_id=artifact.sequence.sequence_id,
        )
        cam = CalibratedCamera(
            camera_matrix=artifact.camera_matrix,
            distortion_coeffs=artifact.distortion_coeffs,
            image_size=artifact.image_size,
        )
        surface = SurfacePlane(
            normal=artifact.surface_normal, offset=artifact.surface_offset
        )
        backend = ReconstructionBackendFactory.create(BackendMode.REFERENCE)
        recon = backend.reconstruct(corr, cam, surface, max_points=20_000)
        timings["reconstruction_ms"] = (time.perf_counter() - t0) * 1000

        # --- Solve ---
        t0 = time.perf_counter()
        from projectionai.calibration.solver import (
            CalibrationSolveError,
            solve_calibration,
        )

        try:
            calib_result = solve_calibration(
                (recon,),
                projector_resolution=(
                    artifact.sequence.width,
                    artifact.sequence.height,
                ),
                camera_matrix=artifact.camera_matrix,
                distortion_coeffs=artifact.distortion_coeffs,
                image_size=artifact.image_size,
            )
        except CalibrationSolveError as exc:
            raise ReplayError(str(exc)) from exc
        timings["solve_ms"] = (time.perf_counter() - t0) * 1000

        # --- WarpMesh ---
        t0 = time.perf_counter()
        from projectionai.services.calibration import calibration_to_warp_mesh

        mesh = calibration_to_warp_mesh(
            calib_result,
            surface_width_m=artifact.surface_width_m,
            surface_height_m=artifact.surface_height_m,
            grid_rows=artifact.grid_rows,
            grid_cols=artifact.grid_cols,
        )
        timings["warp_ms"] = (time.perf_counter() - t0) * 1000
        timings["total_ms"] = sum(v for k, v in timings.items() if k != "total_ms")
        _, t_peak = tracemalloc.get_traced_memory()
        peak_mb = float(t_peak) / (1024 * 1024)
        if not was_tracing:
            tracemalloc.stop()

        return ReplayResult(
            correspondence_mask=np.ascontiguousarray(cmap.mask),
            projector_x=np.ascontiguousarray(cmap.projector_x),
            projector_y=np.ascontiguousarray(cmap.projector_y),
            points_camera=np.ascontiguousarray(recon.points_camera),
            projector_pixels=np.ascontiguousarray(recon.projector_pixels),
            intrinsics=np.ascontiguousarray(calib_result.projector_intrinsics),
            pose=np.ascontiguousarray(calib_result.projector_pose),
            reprojection_rms=float(calib_result.reprojection_error),
            coverage=float(calib_result.coverage),
            warp_projector_uvs=np.ascontiguousarray(mesh.projector_uvs),
            warp_content_uvs=np.ascontiguousarray(mesh.content_uvs),
            warp_indices=np.ascontiguousarray(mesh.indices),
            timings_ms=dict(timings),
            peak_ram_mb=peak_mb,
        )
