# REPORT.md — Phase 7.15 Hardware Validation & Physical Calibration Closure

**Date**: 2026-08-30
**Status**: IN_PROGRESS — HARDWARE_PENDING (all gates)
**Author**: Sisyphus (orchestrator)

---

## Executive Summary

**HARDWARE AVAILABLE = NO**

Physical rig (camera + projector/display + surface) is not available on this
machine. All 7 hardware validation gates (H-01..H-07) remain HARDWARE_PENDING.
No physical evidence was collected. No gates were marked PASS.

Phase 7.15 cannot proceed beyond this point until the physical rig is connected.

---

## 1. Hardware Inventory

### 1.1 Display Devices

| Device                  | Resolution     | Status              |
| ----------------------- | -------------- | ------------------- |
| `\\.\DISPLAY1` (laptop) | 1536×864       | Primary — available |
| LG TV SSCR2             | 1280×720 @60Hz | **NOT CONNECTED**   |

**Finding**: Only 1 display detected (laptop panel). No secondary display
(projector/TV) is connected. The LG TV SSCR2 expected by the calibration
pipeline is not available.

### 1.2 Camera Devices

| Device                             | Backend | Resolution | Status                              |
| ---------------------------------- | ------- | ---------- | ----------------------------------- |
| Windows Virtual Camera Device (×3) | DSHOW   | 640×480    | Software mirrors — **NOT PHYSICAL** |

**Finding**: Only Windows Virtual Camera Device entries detected. These are
software loopback/mirror devices (OBS, Teams, etc.), not physical USB cameras.
No physical camera is connected.

### 1.3 Physical Rig

| Component                              | Required | Available   |
| -------------------------------------- | -------- | ----------- |
| Physical camera (USB/machine vision)   | Yes      | **NO**      |
| Camera aimed at projection surface     | Yes      | **NO**      |
| LG TV / projector as secondary display | Yes      | **NO**      |
| Matte projection surface               | Yes      | **UNKNOWN** |
| Controlled room geometry               | Yes      | **UNKNOWN** |

---

## 2. Validation Gate Status

| Gate | Name                             | Status           | Evidence                            |
| ---- | -------------------------------- | ---------------- | ----------------------------------- |
| H-01 | Optical closure WHITE-BLACK >5%  | HARDWARE_PENDING | No camera, no projector             |
| H-02 | Real vsync/frameSwapped timing   | HARDWARE_PENDING | No projector/display                |
| H-03 | Settle-time production choice    | HARDWARE_PENDING | No camera, no projector             |
| H-04 | Camera backend BUFFERSIZE policy | HARDWARE_PENDING | No physical camera                  |
| H-05 | Real sentinel coverage           | HARDWARE_PENDING | No camera, no projector             |
| H-06 | Real 2-plane calibration ≥15°    | HARDWARE_PENDING | No camera, no projector, no surface |
| H-07 | 3× repeatability                 | HARDWARE_PENDING | No camera, no projector, no surface |

**All gates remain HARDWARE_PENDING. No gate was marked PASS, FAIL, or
CONDITIONAL. No evidence was fabricated.**

---

## 3. What Would Unblock This Phase

To execute Phase 7.15, the following physical hardware must be connected:

1. **Physical USB camera** — machine vision or webcam with adjustable exposure/gain
2. **LG TV SSCR2** (or equivalent) — connected as secondary display via HDMI
3. **Camera tripod/mount** — aimed at the TV screen from a fixed position
4. **Matte projection surface** — the TV screen itself or a separate surface

Once connected:

- Step 1 (Rig Preflight): Verify camera sees TV display at 30–70% fill
- Step 2 (Display Identity): Confirm display index, name, geometry
- Steps 3–10: Execute H-01 through H-07 with measured evidence
- Steps 11–15: Run real end-to-end calibration, arm, live, watchdog
- Steps 16–20: Preserve evidence, update workbook

---

## 4. Software Quality (Baseline)

No source changes were made. Baseline checks confirm no regressions:

| Check                                   | Result                                                     |
| --------------------------------------- | ---------------------------------------------------------- |
| `ruff check src/projectionai/`          | ✅ All checks passed                                       |
| `ruff format --check src/projectionai/` | ✅ 241 files already formatted                             |
| `mypy --strict src/projectionai/`       | ⚠️ 1 pre-existing error (persistence.py:333 no-any-return) |

---

## 5. Workbook Updates

| File                    | Change                                             |
| ----------------------- | -------------------------------------------------- |
| `01_MASTER_PLAN.csv`    | 7.14 → DONE; 7.15 → IN_PROGRESS                    |
| `16_STATUS_HISTORY.csv` | 3 entries appended (7.14 DONE, 7.15 START)         |
| `12_CHANGELOG.csv`      | CH-012 (7.14 DONE), CH-013 (7.15 HARDWARE_PENDING) |
| `14_PHASE_DETAIL.csv`   | Phase 7 updated to include 7.14 report             |

---

## 6. Evidence Directory

No physical evidence was collected. When hardware becomes available, evidence
should be stored in:

```
.planning/phases/7.15-hardware-validation/evidence/
├── H-01/          # raw frames, differential images, timing
├── H-02/          # vsync measurements, frame timing
├── H-03/          # settle-time sweep results
├── H-04/          # buffer policy A/B results
├── H-05/          # sentinel coverage measurements
├── H-06/          # 2-plane calibration outputs
├── H-07/          # 3× repeatability results
└── calibration/   # final calibration artifacts
```

---

## 7. Conclusion

**Phase 7.15 cannot execute.** The physical rig (camera + projector/display)
is not available on this machine. All 7 hardware gates remain HARDWARE_PENDING.

**No evidence was fabricated. No gates were marked PASS without measured data.**

The phase remains IN_PROGRESS / HARDWARE_PENDING. When the physical rig is
connected, execute Steps 1–17 to collect evidence for H-01 through H-07.

---

## 8. Next Steps (When Hardware Available)

1. Connect physical USB camera
2. Connect LG TV SSCR2 as secondary display
3. Mount camera on tripod, aim at TV screen
4. Re-run Phase 7.15 from Step 1
5. Collect measured evidence for each gate
6. Write updated REPORT.md with actual measurements
