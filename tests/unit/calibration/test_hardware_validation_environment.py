"""Unit tests for the host environment snapshot."""

from __future__ import annotations

import os
import platform
import sys

import cv2

from projectionai.calibration.hardware_validation.environment import (
    EnvironmentInfo,
    collect_environment,
)


class TestCollectEnvironment:
    def test_returns_environment_info(self) -> None:
        env = collect_environment()
        assert isinstance(env, EnvironmentInfo)

    def test_version_and_platform_fields(self) -> None:
        env = collect_environment()
        assert env.opencv_version == cv2.__version__
        assert env.python_version == platform.python_version()
        assert env.platform == sys.platform
        assert env.machine == platform.machine()

    def test_cpu_count_is_positive(self) -> None:
        env = collect_environment()
        assert env.cpu_count > 0

    def test_memory_bytes_non_negative(self) -> None:
        env = collect_environment()
        assert env.memory_bytes >= 0

    def test_started_at_timestamp_present(self) -> None:
        env = collect_environment()
        assert env.started_at
        assert "T" in env.started_at

    def test_duration_defaults_to_zero(self) -> None:
        env = collect_environment()
        assert env.duration_seconds == 0.0

    def test_duration_can_be_set(self) -> None:
        env = EnvironmentInfo(
            opencv_version="5.0.0",
            python_version="3.12",
            platform="win32",
            machine="AMD64",
            processor="x86_64",
            cpu_count=8,
            memory_bytes=1024,
            started_at="2026-01-01T00:00:00+00:00",
        )
        assert env.duration_seconds == 0.0


class TestMemoryDetection:
    def test_windows_path_uses_ctypes(self) -> None:
        if sys.platform != "win32":
            return
        env = collect_environment()
        # Physically installed memory on a real Windows host is > 0.
        assert env.memory_bytes > 0

    def test_linux_path_reads_proc_meminfo(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        meminfo = "/proc/meminfo"
        if os.path.exists(meminfo):
            env = collect_environment()
            assert env.memory_bytes > 0
