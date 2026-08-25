"""Build configuration for the C++ native extensions.

Uses setuptools + pybind11.setup_helpers to build the C++ extension modules
``projectionai._warp_engine_native`` and ``projectionai._reconstruction_native``
in-place.
"""

from __future__ import annotations

from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

# Use relative paths (pip rejects absolute paths in editable installs)
ext_modules = [
    Pybind11Extension(
        "projectionai._warp_engine_native",
        sources=[
            "native/src/warp_engine.cpp",
            "native/src/binding.cpp",
        ],
        include_dirs=["native/include"],
        language="c++",
        cxx_std=20,
        define_macros=[("NDEBUG", "1")],
    ),
    Pybind11Extension(
        "projectionai._reconstruction_native",
        sources=[
            "native/src/reconstruction.cpp",
            "native/src/reconstruction_binding.cpp",
        ],
        include_dirs=["native/include"],
        language="c++",
        cxx_std=20,
        define_macros=[("NDEBUG", "1")],
    ),
]

setup(
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
)
