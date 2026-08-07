"""Host environment snapshot for hardware validation runs.

Collects the runtime facts logged with every validation report: OpenCV
version, Python/platform, CPU info, and total physical memory. Uses only
the standard library (``platform``, ``os``, ``ctypes``) plus ``cv2`` —
no new dependencies (``psutil`` is intentionally avoided).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import cv2


@dataclass(frozen=True)
class EnvironmentInfo:
    """Read-only snapshot of the host environment.

    Attributes:
        opencv_version: Installed OpenCV version (``cv2.__version__``).
        python_version: Python version (``platform.python_version()``).
        platform: Operating system identifier (``sys.platform``).
        machine: Machine type (``platform.machine()``).
        processor: CPU name (may be empty on some platforms).
        cpu_count: Number of logical CPUs.
        memory_bytes: Total physical memory in bytes (0 if undetectable).
        started_at: ISO-8601 UTC timestamp of the snapshot.
        duration_seconds: Elapsed run duration, filled by the caller.
    """

    opencv_version: str
    python_version: str
    platform: str
    machine: str
    processor: str
    cpu_count: int
    memory_bytes: int
    started_at: str
    duration_seconds: float = 0.0


def collect_environment() -> EnvironmentInfo:
    """Collect a snapshot of the current host environment."""
    return EnvironmentInfo(
        opencv_version=cv2.__version__,
        python_version=platform.python_version(),
        platform=sys.platform,
        machine=platform.machine(),
        processor=platform.processor(),
        cpu_count=os.cpu_count() or 0,
        memory_bytes=_total_memory_bytes(),
        started_at=datetime.now(UTC).isoformat(),
    )


def _total_memory_bytes() -> int:
    """Total physical memory in bytes; 0 when undetectable."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return 0
    if sys.platform == "darwin":
        return _macos_memory_bytes()
    if sys.platform == "win32":
        return _windows_memory_bytes()
    return 0


def _macos_memory_bytes() -> int:
    """Read physical memory via the ``hw.memsize`` sysctl (returns bytes).

    Uses ``ctypes`` to call ``sysctlbyname`` (no external dependencies).
    Returns 0 when the library or symbol is unavailable.
    """
    try:
        libc = ctypes.CDLL("libc.dylib")
    except OSError:
        return 0

    try:
        # sysctlbyname(name, oldp, oldlenp, newp, newlen) — ``hw.memsize``
        # is an 8-byte unsigned integer, so a c_ulonglong buffer suffices.
        libc.sysctlbyname.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_ulonglong),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        libc.sysctlbyname.restype = ctypes.c_int
        memory = ctypes.c_ulonglong(0)
        size = ctypes.c_size_t(ctypes.sizeof(memory))
        result = libc.sysctlbyname(
            b"hw.memsize", ctypes.byref(memory), ctypes.byref(size), None, 0
        )
        if result != 0:
            return 0
        return int(memory.value)
    except (OSError, AttributeError):
        return 0


def _windows_memory_bytes() -> int:
    """Read physically installed memory via ``GetPhysicallyInstalledSystemMemory``.

    The API reports installed RAM in kilobytes (Vista+); multiply by 1024
    to get bytes. Returns 0 when the call fails or the DLL is unavailable.
    """
    try:
        # ``ctypes.WinDLL`` exists only on Windows; go through ``Any`` so the
        # module type-checks and imports on every platform.
        kernel32 = cast(Any, ctypes).WinDLL("kernel32")
    except (OSError, AttributeError):
        return 0

    total_kb = ctypes.c_ulonglong(0)
    try:
        # Declare the API signature up front so ctypes converts the
        # by-reference output correctly (BOOL return, ULONGLONG* arg).
        get_memory = kernel32.GetPhysicallyInstalledSystemMemory
        get_memory.restype = ctypes.wintypes.BOOL
        get_memory.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
        result = get_memory(ctypes.byref(total_kb))
    except (OSError, AttributeError):
        return 0
    if not result:
        return 0
    return int(total_kb.value) * 1024
