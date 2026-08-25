cmake_minimum_required(VERSION 3.20)
project(projectionai_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Warp engine library (static, for testing)
add_library(warp_engine STATIC
    src/warp_engine.cpp
)
target_include_directories(warp_engine PUBLIC include)

# Reconstruction kernels library (static, for testing)
add_library(reconstruction STATIC
    src/reconstruction.cpp
)
target_include_directories(reconstruction PUBLIC include)

# Test executable (standalone, no pybind11 dependency)
add_executable(warp_engine_test
    tests/test_warp_engine.cpp
    src/warp_engine.cpp
)
target_include_directories(warp_engine_test PRIVATE include)
