"""Tests for calibration pipeline."""

from __future__ import annotations

import pytest

from projectionai.calibration.pipeline import (
    CalibrationPipeline,
    CalibrationStage,
    StageContext,
    StageError,
)
from projectionai.calibration.types import CalibrationStageType


# -- Helper stages ------------------------------------------------------------


class AddOneStage(CalibrationStage):
    """Simple stage that adds a value to the context."""

    def __init__(self, key: str = "value", name: str = "") -> None:
        super().__init__(CalibrationStageType.INPUT_ACQUISITION)
        self._key = key
        if name:
            self.name = name

    async def execute(self, ctx: StageContext) -> StageContext:
        current = ctx.data.get(self._key, 0)
        ctx.data[self._key] = current + 1
        return ctx


class FailingStage(CalibrationStage):
    """Stage that always fails."""

    def __init__(self) -> None:
        super().__init__(CalibrationStageType.VALIDATION)

    async def execute(self, ctx: StageContext) -> StageContext:
        raise StageError("Intentional failure")


class StageWithMarker(CalibrationStage):
    """Stage that records execution order."""

    def __init__(self, marker: str, type_: CalibrationStageType | None = None) -> None:
        super().__init__(type_ or CalibrationStageType.FEATURE_DETECTION)
        self._marker = marker
        self.name = f"stage_{marker}"

    async def execute(self, ctx: StageContext) -> StageContext:
        order = ctx.data.get("order", [])
        order.append(self._marker)
        ctx.data["order"] = order
        return ctx


# -- Tests --------------------------------------------------------------------


class TestStageContext:
    def test_defaults(self) -> None:
        ctx = StageContext()
        assert ctx.data == {}
        assert ctx.errors == []
        assert ctx.warnings == []
        assert ctx.timings == {}

    def test_data_persistence(self) -> None:
        ctx = StageContext()
        ctx.data["key"] = "value"
        assert ctx.data["key"] == "value"


class TestCalibrationPipeline:
    async def test_empty_pipeline(self) -> None:
        pipeline = CalibrationPipeline()
        ctx = await pipeline.run()
        assert ctx.data == {}

    async def test_single_stage(self) -> None:
        pipeline = CalibrationPipeline()
        pipeline.add_stage(AddOneStage("counter"))
        ctx = await pipeline.run()
        assert ctx.data["counter"] == 1

    async def test_multiple_stages(self) -> None:
        pipeline = CalibrationPipeline()
        s1 = AddOneStage("counter", name="a")
        s2 = AddOneStage("counter", name="b")
        pipeline.add_stage(s1)
        pipeline.add_stage(s2)
        ctx = await pipeline.run()
        assert ctx.data["counter"] == 2

    async def test_stage_order(self) -> None:
        pipeline = CalibrationPipeline()
        pipeline.add_stage(StageWithMarker("A"))
        pipeline.add_stage(StageWithMarker("B"))
        pipeline.add_stage(StageWithMarker("C"))
        ctx = await pipeline.run()
        assert ctx.data["order"] == ["A", "B", "C"]

    async def test_stage_failure_stops_execution(self) -> None:
        pipeline = CalibrationPipeline()
        pipeline.add_stage(StageWithMarker("A"))
        pipeline.add_stage(FailingStage())
        pipeline.add_stage(StageWithMarker("C"))
        ctx = await pipeline.run()
        assert ctx.data.get("order") == ["A"]
        assert len(ctx.errors) == 1
        assert "Intentional failure" in ctx.errors[0]

    async def test_disabled_stage_skipped(self) -> None:
        pipeline = CalibrationPipeline()
        s1 = AddOneStage("counter", name="c1")
        s2 = AddOneStage("counter", name="c2")
        s2.enabled = False
        pipeline.add_stage(s1)
        pipeline.add_stage(s2)
        ctx = await pipeline.run()
        assert ctx.data["counter"] == 1

    async def test_enabled_stages_property(self) -> None:
        pipeline = CalibrationPipeline()
        s1 = AddOneStage(name="e1")
        s2 = AddOneStage(name="e2")
        s2.enabled = False
        pipeline.add_stage(s1)
        pipeline.add_stage(s2)
        assert len(pipeline.enabled_stages) == 1

    async def test_add_stage_duplicate_raises(self) -> None:
        pipeline = CalibrationPipeline()
        stage = AddOneStage()
        stage.name = "dup"
        pipeline.add_stage(stage)
        with pytest.raises(ValueError, match="already exists"):
            pipeline.add_stage(stage)

    async def test_remove_stage(self) -> None:
        pipeline = CalibrationPipeline()
        stage = AddOneStage()
        pipeline.add_stage(stage)
        pipeline.remove_stage(stage.name)
        assert pipeline.stage_count == 0

    async def test_get_stage(self) -> None:
        pipeline = CalibrationPipeline()
        stage = AddOneStage()
        pipeline.add_stage(stage)
        assert pipeline.get_stage(stage.name) is stage

    async def test_get_stage_at(self) -> None:
        pipeline = CalibrationPipeline()
        s1 = AddOneStage(name="s1")
        s2 = AddOneStage(name="s2")
        pipeline.add_stage(s1)
        pipeline.add_stage(s2)
        assert pipeline.get_stage_at(0) is s1
        assert pipeline.get_stage_at(1) is s2
        assert pipeline.get_stage_at(99) is None

    async def test_move_stage(self) -> None:
        pipeline = CalibrationPipeline()
        s1 = StageWithMarker("A")
        s2 = StageWithMarker("B")
        pipeline.add_stage(s1)
        pipeline.add_stage(s2)
        pipeline.move_stage(s2.name, 0)
        ctx = await pipeline.run()
        assert ctx.data["order"] == ["B", "A"]

    async def test_clear(self) -> None:
        pipeline = CalibrationPipeline()
        pipeline.add_stage(AddOneStage())
        pipeline.clear()
        assert pipeline.stage_count == 0

    async def test_stage_can_be_called_directly(self) -> None:
        stage = AddOneStage("val")
        ctx = await stage(StageContext())
        assert ctx.data["val"] == 1

    async def test_disabled_stage_call_returns_context(self) -> None:
        stage = AddOneStage("val")
        stage.name = "val_stage"
        stage.enabled = False
        ctx = await stage(StageContext())
        assert "val" not in ctx.data

    async def test_inherited_stage_type(self) -> None:
        stage = AddOneStage()
        assert stage.stage_type == CalibrationStageType.INPUT_ACQUISITION

    async def test_context_passed_through_stages(self) -> None:
        pipeline = CalibrationPipeline()
        pipeline.add_stage(AddOneStage("counter"))
        ctx = StageContext()
        ctx.data["initial"] = True
        result = await pipeline.run(ctx)
        assert result.data["initial"] is True
        assert result.data["counter"] == 1
