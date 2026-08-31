# README Audit

**Date**: 2026-08-31
**Baseline commit**: `96c92b6`

---

## Current README Structure

1. Title + one-liner + vision statement
2. Badges (5)
3. Screenshot (1 — `main-window.png`)
4. Features list (9 items)
5. Quick Start (bash block)
6. Development (bash blocks + testing + project structure + architecture diagram + coding standards)
7. Project Status (brief)
8. Contributing + Security
9. License

---

## KEEP

| Element                | Why                                       |
| ---------------------- | ----------------------------------------- |
| CI badge               | Useful signal — CI is green               |
| Python badge           | Accurate                                  |
| mypy badge             | Accurate — strict mode enforced           |
| MIT license badge      | Accurate                                  |
| Quick Start section    | Commands are verified and correct         |
| Development section    | Commands are accurate                     |
| Architecture diagram   | Clear and accurate                        |
| Project structure tree | Accurate and useful                       |
| Testing section        | Markers, timeout, headless Qt all correct |
| Coding standards       | Accurate and concise                      |
| Contributing link      | Correct                                   |
| Security link          | Correct                                   |
| License link           | Correct                                   |

## IMPROVE

| Element                          | Issue                                                                                           | Fix                                   |
| -------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------- |
| Hero                             | "AI-powered projection mapping platform" is accurate but generic                                | Tighten to specific value proposition |
| Vision statement                 | "ChatGPT for Projection Mapping" — accurate framing but needs explicit "long-term vision" label | Keep but clearly frame as aspiration  |
| Ruff badge                       | Links to ruff docs, not project-specific                                                        | Fine — keep                           |
| Screenshot                       | Single screenshot, garbled text (Chinese locale), empty viewport, very wide, low content        | Replace with proper screenshots       |
| Features                         | Good list but reads as feature catalogue, not user value                                        | Rewrite as what the user can do       |
| "ChatGPT for Projection Mapping" | Needs clearer framing as long-term vision                                                       | Move to vision subsection             |
| Project Status                   | Buries hardware blocker                                                                         | Make status more visually prominent   |
| Hardware validation              | Wording is accurate but could be clearer                                                        | Restructure into dedicated section    |
| Architecture                     | Good but buried in Development                                                                  | Elevate to its own section            |
| No workflow diagram              | User doesn't know the operational flow                                                          | Add core workflow section             |
| Safety model                     | Not explained                                                                                   | Add safety section (ARM != LIVE)      |

## REMOVE

| Element                                                                         | Why                                 |
| ------------------------------------------------------------------------------- | ----------------------------------- |
| "The long-term vision: become the 'ChatGPT for Projection Mapping.'" in opening | Move to dedicated vision subsection |

## MISSING

| Element                     | Why needed                                       |
| --------------------------- | ------------------------------------------------ |
| Core workflow diagram       | Shows the operational path clearly               |
| Safety / validation model   | Explains ARM != LIVE, watchdog, validation gates |
| Visual gallery              | Single screenshot insufficient                   |
| Current status dashboard    | Quick-read status section                        |
| Hardware requirements       | Clear hardware vs software-only distinction      |
| Repository structure (root) | User-facing files listed                         |
| Roadmap summary             | Link to ROADMAP.md with concise summary          |

---

## Screenshot Audit

**File**: `screenshots/main-window.png`
**Size**: 15,438 bytes (~15 KB)
**Dimensions**: ~1920x800 (very wide)
**Date**: 2026-08-23

### Issues

1. **Garbled text**: Chinese locale rendering — all UI labels show as □□□□ (tofu characters)
2. **Empty viewport**: 3D viewport is completely dark/empty — no scene loaded
3. **Very low content**: Most of the window is empty dark space
4. **Resolution**: Acceptable but content doesn't justify the width
5. **Not current**: Screenshot is 8 days old — may not reflect latest UI changes

### Verdict

**DO NOT REUSE.** This screenshot makes the application look broken and empty. It cannot serve as a hero image. Need to capture a new screenshot with:

- English locale (or proper font rendering)
- A loaded scene or calibration state
- Tighter crop
- More visual content in the viewport

---

## Link Verification

| Link                          | Target              | Exists      | Notes               |
| ----------------------------- | ------------------- | ----------- | ------------------- |
| `docs/Architecture.md`        | Architecture doc    | YES         | 428 lines, detailed |
| `docs/ADR/`                   | ADR directory       | YES         | 12 ADRs (001-012)   |
| `docs/UX-ARCHITECTURE.md`     | UX architecture     | YES         | 686 lines, detailed |
| `docs/HARDWARE-VALIDATION.md` | Hardware validation | YES         | 127 lines           |
| `docs/OUTPUT.md`              | Output contracts    | YES         | 119 lines           |
| `ROADMAP.md`                  | Roadmap             | YES         | 161 lines           |
| `CHANGELOG.md`                | Changelog           | YES         | 64 lines            |
| `CONTRIBUTING.md`             | Contributing        | YES         | 67 lines            |
| `SECURITY.md`                 | Security policy     | YES         | 35 lines            |
| `CODE_OF_CONDUCT.md`          | Code of conduct     | YES         | 68 lines            |
| `LICENSE`                     | License file        | Assumed YES | Not verified        |
| `screenshots/main-window.png` | Screenshot          | YES         | Exists but bad      |

**All links verified. No broken links found.**
