"""Calibration pipeline — ordered stages with typed interfaces.

The pipeline defines the structure of a calibration workflow without
containing any algorithm logic. Each stage is a typed interface that
future algorithm implementations will satisfy.

Design:
- Pipeline is a ordered list of ``CalibrationStage`` instances.
- Each stage has typed ``Input`` / ``Output`` dataclasses.
- Stages communicate by writing to a shared context dict.
- The pipeline executor runs stages sequentially, passing context
  between them.
- Algorithm implementations subclass ``CalibrationStage`` and
  implement ``execute()``.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypedDict

from projectionai.calibration.types import CalibrationStageType

_logger = logging.getLogger(__name__)


class PipelineData(TypedDict, total=False):
    frames: Any
    detections: Any
    camera_calibration: Any
    projector_frames: Any
    pattern_sequence: Any
    projector_resolution: Any
    calibrated_camera: Any
    surface_plane: Any
    projector_calibration: Any
    projector_correspondences: Any
    correspondence_map: Any
    correspondence_set: Any
    correspondences: Any
    reconstruction: Any
    reconstructions: Any
    calibration_result: Any
    calibration_solve_config: Any


@dataclass
class StageContext:
    """Shared context passed between pipeline stages."""

    data: PipelineData = field(default_factory=dict)  # type: ignore[assignment]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value  # type: ignore

    def require(self, key: str) -> Any:
        if key not in self.data:
            raise KeyError(f"StageContext missing required key: {key!r}")
        return self.data[key]  # type: ignore


class CalibrationStage(ABC):
    """Abstract base class for a single pipeline stage.

    Subclass this and implement ``execute()`` to create a calibration
    algorithm stage. Stages are composable: the output of one stage
    feeds the input of the next via ``StageContext``.
    """

    def __init__(self, stage_type: CalibrationStageType) -> None:
        self._stage_type: CalibrationStageType = stage_type
        self._enabled: bool = True
        self._name: str = stage_type.value

    # -- Public properties ----------------------------------------------------

    @property
    def stage_type(self) -> CalibrationStageType:
        """Type identifier for this stage."""
        return self._stage_type

    @property
    def name(self) -> str:
        """Human-readable stage name."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def enabled(self) -> bool:
        """Whether this stage executes during pipeline runs."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    # -- Execution ------------------------------------------------------------

    @abstractmethod
    async def execute(self, ctx: StageContext) -> StageContext:
        """Execute this pipeline stage.

        Args:
            ctx: The current pipeline context. Read inputs from
                ``ctx.data`` and write outputs back to it.

        Returns:
            The updated context with outputs populated.

        Raises:
            StageError: If the stage fails irrecoverably.
        """
        ...

    async def __call__(self, ctx: StageContext) -> StageContext:
        """Convenience: call the stage directly."""
        if not self._enabled:
            return ctx
        return await self.execute(ctx)


class StageError(RuntimeError):
    """Raised by a pipeline stage on irrecoverable failure."""


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class CalibrationPipeline:
    """Ordered sequence of calibration stages.

    Manages stage registration, ordering, and sequential execution.
    Each stage receives the accumulated context from all previous stages.

    Usage::

        pipeline = CalibrationPipeline()
        pipeline.add_stage(InputAcquisitionStage())
        pipeline.add_stage(FeatureDetectionStage())
        await pipeline.run(ctx)
    """

    def __init__(self) -> None:
        self._stages: list[CalibrationStage] = []
        self._stage_map: dict[str, CalibrationStage] = {}

    # -- Stage management -----------------------------------------------------

    def add_stage(
        self, stage: CalibrationStage, *, index: int | None = None
    ) -> CalibrationStage:
        """Add a stage to the pipeline.

        Args:
            stage: The stage instance to add.
            index: Insert position (``None`` = append).

        Returns:
            The stage for chaining.
        """
        if stage.name in self._stage_map:
            msg = f"Stage '{stage.name}' already exists"
            raise ValueError(msg)

        if index is not None:
            self._stages.insert(index, stage)
        else:
            self._stages.append(stage)
        self._stage_map[stage.name] = stage
        return stage

    def remove_stage(self, name: str) -> None:
        """Remove a stage by name."""
        stage = self._stage_map.pop(name, None)
        if stage is not None:
            self._stages.remove(stage)

    def get_stage(self, name: str) -> CalibrationStage | None:
        """Get a stage by name."""
        return self._stage_map.get(name)

    def get_stage_at(self, index: int) -> CalibrationStage | None:
        """Get a stage by position."""
        if 0 <= index < len(self._stages):
            return self._stages[index]
        return None

    def move_stage(self, name: str, new_index: int) -> None:
        """Move a stage to a new position."""
        stage = self._stage_map.get(name)
        if stage is None:
            return
        self._stages.remove(stage)
        self._stages.insert(new_index, stage)

    @property
    def stages(self) -> list[CalibrationStage]:
        """All registered stages in execution order."""
        return list(self._stages)

    @property
    def enabled_stages(self) -> list[CalibrationStage]:
        """Only enabled stages."""
        return [s for s in self._stages if s.enabled]

    @property
    def stage_count(self) -> int:
        """Number of registered stages."""
        return len(self._stages)

    # -- Execution ------------------------------------------------------------

    async def run(self, ctx: StageContext | None = None) -> StageContext:
        """Execute all enabled stages in order.

        Args:
            ctx: Initial context. Creates a fresh one if ``None``.

        Returns:
            The accumulated context after all stages complete.
        """
        ctx = ctx or StageContext()
        _logger.info("Pipeline run started (%d stages)", len(self._stages))

        for stage in self._stages:
            if not stage.enabled:
                _logger.debug("Skipping disabled stage: %s", stage.name)
                continue

            _logger.info("Running stage: %s", stage.name)
            start = time.monotonic()

            try:
                ctx = await stage.execute(ctx)
            except StageError as exc:
                _logger.error("Stage %s failed: %s", stage.name, exc)
                ctx.errors.append(f"{stage.name}: {exc}")
                break
            except Exception as exc:
                _logger.exception("Stage %s raised unexpected error", stage.name)
                ctx.errors.append(f"{stage.name}: unexpected error — {exc}")
                break

            elapsed = (time.monotonic() - start) * 1000.0
            ctx.timings[stage.name] = elapsed
            _logger.info("Stage %s completed in %.1f ms", stage.name, elapsed)

        _logger.info(
            "Pipeline run finished (%d errors, %d warnings)",
            len(ctx.errors),
            len(ctx.warnings),
        )
        return ctx

    def clear(self) -> None:
        """Remove all stages."""
        self._stages.clear()
        self._stage_map.clear()
