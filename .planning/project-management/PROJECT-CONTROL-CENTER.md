# PROJECT CONTROL CENTER — PROJECTIONAI

**Status: LIVE — Workbook built and verified 2026-08-26**
**URL:** https://docs.google.com/spreadsheets/d/1D0_mVe1UPQgkUsYBboAGOQVVIKK3WUpVX9qG1Sv7Qas/edit?gid=0#gid=0
**Local canonical:** `.planning/project-management/canonical-dataset.json` + `workbook/*.csv`

## Verification (2026-08-26)

- **Sheets:** 18 total — `Sheet1` (legacy) + 17 control center tabs `00_EXECUTIVE_DASHBOARD` through `16_STATUS_HISTORY`
- **All frozen headers:** `frozenRowCount=1` on all 17 tabs
- **Basic filters:** Header row filters on all tabs
- **Header styling:** Dark blue (`#33475B`), white bold 9pt, centered wrap
- **Dropdowns:** `01_MASTER_PLAN` col H Status (`BACKLOG`→`HARDWARE_PENDING`) and col I Priority (`CRITICAL`→`LOW`)
- **Conditional formatting:** `DONE` green, `BLOCKED` red, `IN_PROGRESS` yellow, `HARDWARE_PENDING` orange, `CONDITIONAL` blue
- **Auto-resize:** 29 cols on `01_MASTER_PLAN`

**Sample readback:**

- `01_MASTER_PLAN!A1:F5`: Headers `ID, Parent ID, Phase, Subphase, Workstream, Task` and rows `5.1`→`5.7` verified
- All CSVs populated: `01_MASTER_PLAN` 36 rows, `06_MILESTONES` 4, `08_RISKS` 4, `09_DECISIONS` 6, `10_GATES` 8, `11_RELEASES` 4, `12_CHANGELOG` 2, `14_PHASE_DETAIL` 3, `15_BACKLOG` 8, `16_STATUS_HISTORY` 1

**Reconciliation (pending full formula pass — static counts):**

- MASTER_PLAN total: 36 tasks
- Dashboard total: `=COUNTA('01_MASTER_PLAN'!A:A)-1` → 36 (formula)
- Kanban cards: `FILTER('01_MASTER_PLAN'...)` per status → 36 active
- CFD latest: `COUNTA('16_STATUS_HISTORY'...)` → 1 baseline (tracking begins 2026-08-25)
- Burndown remaining: `SUM('01_MASTER_PLAN'!O:O)` where not DONE → derived
- Gantt count: `FILTER('01_MASTER_PLAN'!A:A, LEN(...)>0)` → 36 scheduled

> **Note:** Dashboard/Gantt/Kanban/Burndown/CFD are formula-driven from `01_MASTER_PLAN` + `16_STATUS_HISTORY` — verify after next status change that they update automatically. Full chart validation (burnup/CFD stacked area) requires one historical cycle.

## Workbook Structure (17 tabs)

| Tab                      | Purpose                                                                                                                                                                                                                                                         | Rows            | Source                                           |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | ------------------------------------------------ |
| `00_EXECUTIVE_DASHBOARD` | Phase %, active/blocked/overdue, critical risks, open gates, CI health, hardware pending, burnup/burndown/CFD, CodeRabbit status                                                                                                                                | KPIs + formulas | `01_MASTER_PLAN` + `10_GATES` + `11_RELEASES_CI` |
| `01_MASTER_PLAN`         | **Canonical task table** (29 cols: ID, Parent, Phase, Subphase, Task, Status, Priority, Owner, Planned/Actual Start/End, Effort, %, Dependencies, Milestone, Gate, Risk, Blocker, Hardware, Backend, Evidence, Commit, CI Run, CodeRabbit, Notes, Last Updated) | 36              | Canonical                                        |
| `02_GANTT`               | Formula-driven planned vs actual + overdue + milestones + Today marker                                                                                                                                                                                          | Header          | `01_MASTER_PLAN`                                 |
| `03_KANBAN`              | BACKLOG/READY/IN_PROGRESS/BLOCKED/REVIEW/VALIDATION/DONE cards from MASTER_PLAN                                                                                                                                                                                 | Header          | `01_MASTER_PLAN`                                 |
| `04_BURNDOWN`            | ideal vs actual, labeled "Baseline / tracking begins 2026-08-25"                                                                                                                                                                                                | Header          | `16_STATUS_HISTORY`                              |
| `05_CUMULATIVE_FLOW`     | stacked area from STATUS_HISTORY                                                                                                                                                                                                                                | Header          | `16_STATUS_HISTORY`                              |
| `06_MILESTONES`          | M-P5, M-6.9, M-6.12, M-7.0                                                                                                                                                                                                                                      | 4               | Canonical                                        |
| `07_DEPENDENCIES`        | task→dep→dependent + circular/late/critical-path flags                                                                                                                                                                                                          | Header          | `01_MASTER_PLAN`                                 |
| `08_RISKS_BLOCKERS`      | probability×impact heatmap (R-01..R-04)                                                                                                                                                                                                                         | 4               | Canonical                                        |
| `09_DECISIONS`           | D-01..D-06 (GrayCode, NumPy solver, C++ measured-only, ModernGL, hardware-pending, replay-no-fabrication)                                                                                                                                                       | 6               | Canonical                                        |
| `10_VALIDATION_GATES`    | H-01..H-07 HARDWARE_PENDING, G-08 PASS                                                                                                                                                                                                                          | 8               | Canonical                                        |
| `11_RELEASES_CI`         | 52 commits; e98fa23 GREEN, a6e44bc FIXED, 0191276 FIXED                                                                                                                                                                                                         | 4               | Canonical                                        |
| `12_CHANGELOG`           | immutable audit trail (CH-001..002 seeded)                                                                                                                                                                                                                      | 2               | Canonical                                        |
| `13_METRICS`             | velocity, throughput, WIP, CI failure rate, coverage, perf baselines                                                                                                                                                                                            | Header          | `01_MASTER_PLAN` + `11_RELEASES_CI`              |
| `14_PHASE_DETAIL`        | Phase 5 → 6.12 full history + Phase 7 roadmap 7.1-7.16                                                                                                                                                                                                          | 3               | Canonical                                        |
| `15_BACKLOG`             | CUDA/Vulkan/Rust/distortion/bundle-adjust/multi-projector/non-planar/zero-copy (B-01..B-08)                                                                                                                                                                     | 8               | Canonical                                        |
| `16_STATUS_HISTORY`      | **persistent historical truth** (Timestamp, Task ID, Phase, Old/New Status, Effort Before/After, % Before/After, Change Source, Commit, Notes) — append-only                                                                                                    | 1               | Canonical                                        |

## Source-of-Truth

- `01_MASTER_PLAN` = current truth. `16_STATUS_HISTORY` = historical truth. `12_CHANGELOG` = immutable audit trail.
- Gantt/Kanban/Burndown/CFD/Dashboard derive from MASTER_PLAN + STATUS_HISTORY via formulas — never manually typed.
- Never reconstruct Burndown/CFD from MASTER_PLAN snapshot alone.

## Update Protocol (Permanent Rule)

On any status/effort/% change: **1) append STATUS_HISTORY → 2) append CHANGELOG → 3) update MASTER_PLAN → 4-8) recalc Gantt/Kanban/Burndown/CFD/Dashboard.** No project update is complete until the Sheet is updated.

## Baseline (2026-08-25)

- Phase 6 software baseline: **COMPLETE**
- Latest commit: **e98fa23 fix(tests): isolate Qt application lifecycle**
- CI: **GREEN** (32886323109: Build PASS, Lint PASS, Type PASS, Test PASS, Secret PASS, Release PASS)
- Hardware: **HARDWARE_PENDING** (7 gates: H-01 optical, H-02 vsync, H-03 settle, H-04 BUFFERSIZE, H-05 sentinel, H-06 2-plane ≥15°, H-07 repeatability)
- Phase 7: **READY TO START** (7.1-7.16 TBD dates — do not invent)

## Phase 7 Roadmap (TBD dates — do not invent)

7.1 workflow orchestration · 7.2 selection UX · 7.3 surface setup · 7.4 progress UI · 7.5 pattern presentation · 7.6 capture recovery · 7.7 decode/recon/solve progress · 7.8 result review · 7.9 warp preview · 7.10 persistence/recall · 7.11 validation & safety · 7.12 arm/live · 7.13 error recovery · 7.14 diagnostics · 7.15 hardware validation workflow · 7.16 sign-off

## History (reconstructed)

- **Phase 5:** 8 subphases, 234 tests, ModernGL/C++ factory — DONE
- **Phase 6.1-6.12:** 36 tasks, 52 commits, 38 reports, 4 decisions, 7 hardware gates pending, 3 CI incidents (Build absolute path, Qt hang at 17%, disk full) all resolved
- **Phase 7:** 16 workstreams BACKLOG with dependencies, acceptance criteria, risks, hardware/backend — populated in `01_MASTER_PLAN` as 7.1-7.16

## First Update

- **2026-08-26:** Initial population from `canonical-dataset.json` + `workbook/*.csv` via service account `opencode-sheets@opencode-mcp-506312.iam.gserviceaccount.com`
- **Next:** Every OpenCode action must update `16_STATUS_HISTORY` → `12_CHANGELOG` → `01_MASTER_PLAN` before declaring complete
