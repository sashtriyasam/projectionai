/**
 * @file test_warp_engine.cpp
 * @brief Standalone C++ unit tests for the warp engine.
 *
 * Compile: cl /std:c++20 /EHsc /I include src\warp_engine.cpp tests\test_warp_engine.cpp /Fe:warp_engine_test.exe
 * Run:     warp_engine_test.exe
 */

#include "projectionai/warp_engine.h"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <stdexcept>

// ---- Helpers ----

static void fill_solid(unsigned char* buf, int h, int w, unsigned char r, unsigned char g, unsigned char b) {
    for (int i = 0; i < h * w; ++i) {
        buf[i * 4 + 0] = r;
        buf[i * 4 + 1] = g;
        buf[i * 4 + 2] = b;
        buf[i * 4 + 3] = 255;
    }
}

static int tests_run = 0;
static int tests_passed = 0;

typedef void (*TestFunc)();
struct TestEntry { const char* name; TestFunc fn; };
static TestEntry g_tests[64];
static int g_test_count = 0;

#define TEST(name)                                         \
    static void test_##name();                             \
    struct Register_##name {                               \
        Register_##name() {                                \
            g_tests[g_test_count++] = { #name, test_##name }; \
        }                                                  \
    } reg_##name;                                          \
    static void test_##name()

#define ASSERT_EQ(a, b) do { if ((a) != (b)) { \
    throw std::runtime_error("assertion failed: " #a " != " #b); } } while(0)
#define ASSERT_TRUE(x) do { if (!(x)) { \
    throw std::runtime_error("assertion failed: " #x); } } while(0)

// ---- Tests ----

TEST(null_inputs_returns_nullptr) {
    unsigned char out[16] = {};
    double proj[4] = {0, 0, 1, 1};
    double con[4]  = {0, 0, 1, 1};
    int idx[3]     = {0, 1, 2};

    // null source
    auto* r = projectionai::warp_engine(nullptr, 1, 1, proj, 2, con, idx, 1, 1, 1, nullptr, nullptr, nullptr, 0, 0);
    ASSERT_EQ(r, nullptr);
    (void)r;
}

TEST(empty_mesh_returns_nullptr) {
    unsigned char src[16] = {};
    double proj[4] = {0, 0, 1, 1};
    double con[4]  = {0, 0, 1, 1};
    int idx[3]     = {0, 1, 2};

    auto* r = projectionai::warp_engine(src, 1, 1, proj, 0, con, idx, 0, 1, 1, nullptr, nullptr, nullptr, 0, 0);
    ASSERT_EQ(r, nullptr);
    projectionai::warp_engine_free(r);
}

TEST(single_triangle_full_coverage) {
    // 2x2 source, single triangle covering the entire 4x4 output
    unsigned char src[16];
    fill_solid(src, 2, 2, 255, 128, 0);  // orange

    // Projector UVs: full output quad
    double proj[8] = {0, 0, 1, 0, 0, 1, 1, 1};
    // Content UVs: full source quad
    double con[8]  = {0, 0, 1, 0, 0, 1, 1, 1};
    // Two triangles: (0,1,2) and (1,3,2)
    int idx[6]     = {0, 1, 2, 1, 3, 2};

    auto* r = projectionai::warp_engine(
        src, 2, 2,
        proj, 4, con, idx, 2,
        4, 4,
        nullptr, nullptr, nullptr, 0, 0);

    ASSERT_TRUE(r != nullptr);

    // Sample several points: all should be the source colour (orange)
    for (int row = 0; row < 4; ++row) {
        for (int col = 0; col < 4; ++col) {
            int off = (row * 4 + col) * 4;
            ASSERT_TRUE(std::abs(static_cast<int>(r[off + 0]) - 255) <= 2);
            ASSERT_TRUE(std::abs(static_cast<int>(r[off + 1]) - 128) <= 2);
            ASSERT_TRUE(std::abs(static_cast<int>(r[off + 2]) - 0) <= 2);
        }
    }

    projectionai::warp_engine_free(r);
}

TEST(identity_warp_preserves_source) {
    // 10x10 source, output same size, identity UV mapping
    const int N = 10;
    unsigned char src[N * N * 4];
    fill_solid(src, N, N, 100, 200, 50);

    double proj[8] = {0, 0, 1, 0, 0, 1, 1, 1};
    double con[8]  = {0, 0, 1, 0, 0, 1, 1, 1};
    int idx[6]     = {0, 1, 2, 1, 3, 2};

    auto* r = projectionai::warp_engine(
        src, N, N,
        proj, 4, con, idx, 2,
        N, N,
        nullptr, nullptr, nullptr, 0, 0);

    ASSERT_TRUE(r != nullptr);

    // A few spot checks
    for (int i = 0; i < N * N * 4; i += 4) {
        ASSERT_TRUE(std::abs(static_cast<int>(r[i + 0]) - 100) <= 2);
        ASSERT_TRUE(std::abs(static_cast<int>(r[i + 1]) - 200) <= 2);
        ASSERT_TRUE(std::abs(static_cast<int>(r[i + 2]) - 50) <= 2);
        ASSERT_EQ(r[i + 3], 255);
    }

    projectionai::warp_engine_free(r);
}

TEST(blend_reduces_edge_intensity) {
    const int N = 4;
    unsigned char src[N * N * 4];
    fill_solid(src, N, N, 255, 255, 255);

    double proj[8] = {0, 0, 1, 0, 0, 1, 1, 1};
    double con[8]  = {0, 0, 1, 0, 0, 1, 1, 1};
    int idx[6]     = {0, 1, 2, 1, 3, 2};

    projectionai::BlendParams blend;
    blend.left = 0.5f;  // 50% left-edge ramp

    auto* r = projectionai::warp_engine(
        src, N, N, proj, 4, con, idx, 2,
        N, N,
        &blend, nullptr, nullptr, 0, 0);

    ASSERT_TRUE(r != nullptr);

    // Left edge (col=0) should be darker than center (col=2)
    int left_val  = r[0];   // row=0, col=0, R channel
    int right_val = r[8];   // row=0, col=2, R channel (offset 2*4=8)

    ASSERT_TRUE(left_val < right_val);
    ASSERT_TRUE(left_val < 50);   // Should be dimmed significantly

    projectionai::warp_engine_free(r);
}

TEST(crop_blacks_outside_region) {
    const int N = 4;
    unsigned char src[N * N * 4];
    fill_solid(src, N, N, 200, 200, 200);

    double proj[8] = {0, 0, 1, 0, 0, 1, 1, 1};
    double con[8]  = {0, 0, 1, 0, 0, 1, 1, 1};
    int idx[6]     = {0, 1, 2, 1, 3, 2};

    projectionai::CropParams crop;
    crop.x = 0.25f; crop.y = 0.25f;
    crop.width = 0.5f; crop.height = 0.5f;

    auto* r = projectionai::warp_engine(
        src, N, N, proj, 4, con, idx, 2,
        N, N,
        nullptr, &crop, nullptr, 0, 0);

    ASSERT_TRUE(r != nullptr);

    // Corner (0,0) should be black (outside crop)
    ASSERT_TRUE(r[0] == 0 && r[1] == 0 && r[2] == 0);

    // Center (2,2) should be bright (inside crop)
    int center_off = (2 * N + 2) * 4;
    ASSERT_TRUE(r[center_off] > 100);

    projectionai::warp_engine_free(r);
}

int main() {
    printf("Running C++ warp engine tests...\n\n");

    for (int i = 0; i < g_test_count; ++i) {
        tests_run++;
        printf("  %-40s ", g_tests[i].name);
        try {
            g_tests[i].fn();
            tests_passed++;
            printf("PASS\n");
        } catch (const std::exception& e) {
            printf("FAIL: %s\n", e.what());
        }
    }

    printf("\n  Tests run:    %d\n", tests_run);
    printf("  Tests passed: %d\n", tests_passed);
    printf("  Tests failed: %d\n", tests_run - tests_passed);

    return (tests_run == tests_passed) ? 0 : 1;
}
