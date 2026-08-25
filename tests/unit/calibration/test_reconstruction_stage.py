"""ReconstructionStage pipeline tests."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from projectionai.calibration.pipeline import StageContext, StageError
from projectionai.calibration.reconstruction_stage import ReconstructionStage
from projectionai.domain.calibration_session import ReconstructionResult
from projectionai.services.reconstruction import BackendMode

from .reconstruction_synth import SynthCase, make_synthetic_case


def _ctx(case: str = "identity") -> tuple[StageContext, SynthCase]:
    c = make_synthetic_case(case, n_points=5000)
    ctx = StageContext()
    ctx.data["correspondence_set"] = c["correspondences"]
    ctx.data["calibrated_camera"] = c["camera"]
    ctx.data["surface_plane"] = c["surface"]
    return ctx, c


@pytest.mark.asyncio
async def test_reconstructs_from_context() -> None:
    ctx, c = _ctx("rotated")
    stage = ReconstructionStage(mode=BackendMode.REFERENCE)
    out = await stage.execute(ctx)
    result: Any = out.data.get("reconstruction")
    assert isinstance(result, ReconstructionResult)
    assert result.sequence_id == c["correspondences"].sequence_id
    assert len(result.points_camera) >= 4
    assert np.all(np.isfinite(result.points_camera))


@pytest.mark.asyncio
async def test_missing_correspondence_set() -> None:
    ctx = StageContext()
    ctx.data["calibrated_camera"] = None
    ctx.data["surface_plane"] = None
    stage = ReconstructionStage(mode=BackendMode.REFERENCE)
    with pytest.raises(StageError, match="correspondence_set"):
        await stage.execute(ctx)


@pytest.mark.asyncio
async def test_missing_camera() -> None:
    ctx, _ = _ctx()
    ctx.data["calibrated_camera"] = None
    stage = ReconstructionStage(mode=BackendMode.REFERENCE)
    with pytest.raises(StageError, match="calibrated_camera"):
        await stage.execute(ctx)


@pytest.mark.asyncio
async def test_missing_surface() -> None:
    ctx, _ = _ctx()
    ctx.data["surface_plane"] = None
    stage = ReconstructionStage(mode=BackendMode.REFERENCE)
    with pytest.raises(StageError, match="surface_plane"):
        await stage.execute(ctx)


@pytest.mark.asyncio
async def test_native_backend_stage() -> None:
    from projectionai.services.reconstruction import ReconstructionBackendFactory

    if not ReconstructionBackendFactory.is_native_available():
        pytest.skip("native extension not built")
    ctx, c = _ctx("translated")
    stage = ReconstructionStage(mode=BackendMode.NATIVE)
    out = await stage.execute(ctx)
    result: Any = out.data.get("reconstruction")
    assert isinstance(result, ReconstructionResult)
    assert stage.backend.name == "native"
