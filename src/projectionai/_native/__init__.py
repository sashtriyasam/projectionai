"""Native C++ extension loader with graceful fallback.

If the compiled C++ extension is available, it is imported.  If it is absent
(e.g. on a fresh checkout without running the build step), the module exposes
``AVAILABLE = False`` so that higher-level code can fall back to the pure-Python
implementation without crashing.

Usage::

    from projectionai._native import AVAILABLE, native_warp
    if AVAILABLE:
        output = native_warp(...)
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

AVAILABLE: bool = False
native_warp: Any = None  # Set to the C++ warp() function if available

_MODULE_NAME = "projectionai._warp_engine_native"

try:
    _mod = importlib.import_module(_MODULE_NAME)
    native_warp = _mod.warp
    AVAILABLE = True
except ImportError:
    # Extension not compiled yet — that's fine.
    AVAILABLE = False
    native_warp = None
except Exception:
    # Catch-all so the package never fails to import.
    AVAILABLE = False
    native_warp = None
