from __future__ import annotations

import hashlib
import threading
import time
import weakref
from collections import OrderedDict

import numpy as np

from projectionai.domain.calibration_session import (
    CalibrationMethod,
    CalibrationPattern,
    CalibrationSequence,
    PatternAxis,
)
from projectionai.infrastructure.projector_calibration.patterns import (
    GrayCodePatternGenerator,
)
from projectionai.services.projector_calibration import (
    PatternAxis as LegacyAxis,
)
from projectionai.services.projector_calibration import (
    PatternSequence as LegacySequence,
)
from projectionai.services.projector_calibration import (
    PatternSpec as LegacySpec,
)
from projectionai.services.projector_calibration import (
    StructuredLightPattern as LegacyPattern,
)

_instances: weakref.WeakSet[PatternEngine] = weakref.WeakSet()


def _deterministic_sequence_id(
    width: int, height: int, invert: bool, method: str
) -> str:
    raw = f"{method}:{width}x{height}:invert={invert}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def graycode_to_canonical(
    legacy: LegacySequence, sequence_id: str | None = None
) -> CalibrationSequence:
    if sequence_id is not None:
        sid = sequence_id
    else:
        inverted = bool(legacy.patterns and legacy.patterns[0].spec.bit_value == 0)
        sid = _deterministic_sequence_id(
            legacy.width, legacy.height, inverted, "gray_code"
        )
    patterns: list[CalibrationPattern] = []
    for lp in legacy.patterns:
        axis = (
            PatternAxis.COLUMN if lp.spec.axis == LegacyAxis.COLUMN else PatternAxis.ROW
        )
        arr = np.array(lp.image, order="C", copy=True)
        arr.flags.writeable = False
        patterns.append(
            CalibrationPattern(
                pattern_id=lp.spec.pattern_id,
                sequence_id=sid,
                axis=axis,
                bit_index=lp.spec.bit_index,
                bit_value=lp.spec.bit_value,
                image=arr,
                width=legacy.width,
                height=legacy.height,
            )
        )
    return CalibrationSequence(
        sequence_id=sid,
        method=CalibrationMethod.GRAY_CODE,
        patterns=tuple(patterns),
        width=legacy.width,
        height=legacy.height,
        bits_x=legacy.bits_x,
        bits_y=legacy.bits_y,
        created_at=time.time(),
    )


def canonical_to_legacy(canonical: CalibrationSequence) -> LegacySequence:
    legacy_patterns: list[LegacyPattern] = []
    for cp in canonical.patterns:
        axis = LegacyAxis.COLUMN if cp.axis == PatternAxis.COLUMN else LegacyAxis.ROW
        legacy_patterns.append(
            LegacyPattern(
                spec=LegacySpec(
                    pattern_id=cp.pattern_id,
                    axis=axis,
                    bit_index=cp.bit_index,
                    bit_value=cp.bit_value,
                ),
                image=np.array(cp.image, copy=True),
            )
        )
    return LegacySequence(
        patterns=tuple(legacy_patterns),
        width=canonical.width,
        height=canonical.height,
        bits_x=canonical.bits_x,
        bits_y=canonical.bits_y,
    )


class PatternEngine:
    def __init__(self, invert: bool = False) -> None:
        self._invert = invert
        self._generator = GrayCodePatternGenerator(invert=invert)
        self._cache: OrderedDict[tuple[int, int, bool, str], CalibrationSequence] = (
            OrderedDict()
        )
        self._lock = threading.Lock()
        self._max_cache = 32
        _instances.add(self)

    @property
    def invert(self) -> bool:
        return self._invert

    def generate(
        self,
        width: int,
        height: int,
        method: CalibrationMethod = CalibrationMethod.GRAY_CODE,
    ) -> CalibrationSequence:
        if method != CalibrationMethod.GRAY_CODE:
            raise ValueError(
                f"Unsupported method {method!r} — only GRAY_CODE in Phase 6.3"
            )
        key = (width, height, self._invert, method.value)
        with self._lock:
            if key in self._cache:
                seq = self._cache.pop(key)
                self._cache[key] = seq
                return seq
            legacy = self._generator.build_sequence(width, height)
            sid = _deterministic_sequence_id(width, height, self._invert, method.value)
            canonical = graycode_to_canonical(legacy, sequence_id=sid)
            self._cache[key] = canonical
            if len(self._cache) > self._max_cache:
                self._cache.popitem(last=False)
            return canonical

    def generate_legacy(self, width: int, height: int) -> LegacySequence:
        return self._generator.build_sequence(width, height)

    @classmethod
    def clear_all_caches(cls) -> None:
        for inst in list(_instances):
            with inst._lock:
                inst._cache.clear()

    @classmethod
    def total_cache_size(cls) -> int:
        return sum(len(inst._cache) for inst in list(_instances))

    # Back-compat descriptors: PatternEngine.clear_cache() -> clear all, engine.clear_cache() -> clear self
    # and same for cache_size (class -> total, instance -> own). Achieved via __get__ descriptors below
    # installed post-class definition.

    @staticmethod
    def bits_for(size: int) -> int:
        return GrayCodePatternGenerator.bits_for(size)


class _ClearCacheDescriptor:
    def __get__(self, instance: PatternEngine | None, owner: type[PatternEngine]):  # type: ignore
        if instance is None:

            def _cls_clear() -> None:
                for inst in list(_instances):
                    with inst._lock:
                        inst._cache.clear()

            return _cls_clear
        else:

            def _inst_clear() -> None:
                with instance._lock:
                    instance._cache.clear()

            return _inst_clear


class _CacheSizeDescriptor:
    def __get__(self, instance: PatternEngine | None, owner: type[PatternEngine]):  # type: ignore
        if instance is None:

            def _cls_size() -> int:
                return sum(len(inst._cache) for inst in list(_instances))

            return _cls_size
        else:

            def _inst_size() -> int:
                with instance._lock:
                    return len(instance._cache)

            return _inst_size


# Install back-compat descriptors: PatternEngine.clear_cache() -> clear all, engine.clear_cache() -> clear self
PatternEngine.clear_cache = _ClearCacheDescriptor()  # type: ignore[attr-defined]
PatternEngine.cache_size = _CacheSizeDescriptor()  # type: ignore[attr-defined]


def get_pattern_engine(invert: bool = False) -> PatternEngine:
    return PatternEngine(invert=invert)
