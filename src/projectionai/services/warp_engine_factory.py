"""WarpEngineFactory — single backend-selection mechanism for ProjectionWarpEngine.

Provides a unified interface for selecting between CpuWarpEngine and
CppWarpEngine based on availability, configuration, and fallback rules.

Selection rules:
1. Prefer CppWarpEngine when native extension is available.
2. Fall back to CpuWarpEngine when native is unavailable.
3. Allow explicit CPU selection for tests/debugging.
4. Allow native selection to be tested explicitly.
5. A broken native initialization must degrade safely to CPU with
   an observable/logged reason.
"""

from __future__ import annotations

import importlib
import logging
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from projectionai.services.warp_engine_cpu import ProjectionWarpEngine

logger = logging.getLogger(__name__)


class EngineMode(StrEnum):
    """Engine selection mode."""

    AUTO = "auto"  # Prefer native, fallback to CPU
    CPU = "cpu"  # Force CPU engine
    NATIVE = "native"  # Force native engine (raises if unavailable)


class WarpEngineFactory:
    """Factory for creating ProjectionWarpEngine instances.

    Usage:
        # Auto-select (prefer native, fallback to CPU)
        engine = WarpEngineFactory.create()

        # Force CPU
        engine = WarpEngineFactory.create(mode=EngineMode.CPU)

        # Force native (raises RuntimeError if unavailable)
        engine = WarpEngineFactory.create(mode=EngineMode.NATIVE)
    """

    @staticmethod
    def create(
        mode: EngineMode = EngineMode.AUTO,
    ) -> ProjectionWarpEngine:
        """Create a ProjectionWarpEngine instance.

        Parameters
        ----------
        mode : EngineMode
            Selection mode:
            - AUTO: Prefer native, fallback to CPU
            - CPU: Force CPU engine
            - NATIVE: Force native engine (raises if unavailable)

        Returns
        -------
        ProjectionWarpEngine
            Either CpuWarpEngine or CppWarpEngine.

        Raises
        ------
        RuntimeError
            If mode=NATIVE and native extension is not available.
        """
        if mode == EngineMode.CPU:
            logger.debug("WarpEngineFactory: CPU mode selected")
            return _create_cpu_engine()

        if mode == EngineMode.NATIVE:
            logger.debug("WarpEngineFactory: NATIVE mode selected")
            return _create_native_engine(required=True)

        # AUTO mode: prefer native, fallback to CPU
        logger.debug("WarpEngineFactory: AUTO mode — attempting native")
        return _create_native_engine(required=False)

    @staticmethod
    def is_native_available() -> bool:
        """Check if the native extension is available.

        Returns
        -------
        bool
            True if native extension is compiled and importable.
        """
        try:
            native_mod = importlib.import_module("projectionai._native")
            return bool(getattr(native_mod, "AVAILABLE", False))
        except Exception:
            return False


def _create_cpu_engine() -> ProjectionWarpEngine:
    """Create a CpuWarpEngine instance."""
    from projectionai.services.warp_engine_cpu import CpuWarpEngine

    return CpuWarpEngine()


def _create_native_engine(required: bool = False) -> ProjectionWarpEngine:
    """Create a CppWarpEngine instance.

    Parameters
    ----------
    required : bool
        If True, raise RuntimeError if native is unavailable.
        If False, fallback to CPU engine.

    Returns
    -------
    ProjectionWarpEngine
        Either CppWarpEngine or CpuWarpEngine.

    Raises
    ------
    RuntimeError
        If required=True and native is unavailable.
    """
    try:
        from projectionai.services.warp_engine_cpp import CppWarpEngine

        engine = CppWarpEngine()
        logger.info("WarpEngineFactory: CppWarpEngine initialized successfully")
        return engine
    except RuntimeError as e:
        if required:
            logger.error("WarpEngineFactory: Native engine required but failed: %s", e)
            raise
        else:
            logger.warning(
                "WarpEngineFactory: Native engine unavailable (%s), falling back to CPU",
                e,
            )
            return _create_cpu_engine()
    except Exception as e:
        if required:
            logger.error("WarpEngineFactory: Native engine required but error: %s", e)
            raise
        else:
            logger.warning(
                "WarpEngineFactory: Native engine error (%s), falling back to CPU",
                e,
            )
            return _create_cpu_engine()
