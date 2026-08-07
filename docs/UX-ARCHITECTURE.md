# ProjectionAI — UX Architecture

> **Status:** Design spec · **Scope:** Complete desktop application UX · **Tech context:** PySide6 (Qt), single main window, ModernGL viewports, plugin-based panels
> **Design lineage:** OBS Studio (speed, dockability, studio mode) · Premiere Pro (timeline) · Blender (transforms, workspaces, history) · Resolume Arena (live performance, blackout) · TouchDesigner (mapping, control) · DaVinci Resolve (color)
>
> Every major decision in this document is followed by a **Why** note. Section 14 collects the rationale.

---

## 1. Product Vision & Design Principles

ProjectionAI is a **live-performance instrument** that happens to be a full editor. The user's relationship to the app oscillates between two modes:

- **Composer** — building scenes, calibrating, generating content (safe, undoable, no output risk)
- **Performer** — running a show (fast, tactile, zero-latency, output-safe)

Everything in this document serves one master principle:

> **Nothing reaches the projector unless the user explicitly arms it.**
> The Live output is a fortress. The editor is a sandbox.

### Principles

| #   | Principle                 | Meaning                                                                                                               |
| --- | ------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| P1  | **Live-first safety**     | Preview and Live are physically separate windows. No edit path can touch the output.                                  |
| P2  | **OBS-speed**             | Every panel one click away. No modal dialogs in the hot path. Right-click everything.                                 |
| P3  | **Nothing hidden**        | Status bar always shows output state, FPS, latency, resolution. You always know what the machine is doing.            |
| P4  | **Viewport is king**      | The center of the app is the two viewports. Chrome yields to them.                                                    |
| P5  | **Contextual power**      | One Inspector that becomes the right tool for whatever is selected.                                                   |
| P6  | **Undo everything**       | Every mutation — including AI actions — is a command on the undo stack. History is visible and branchable.            |
| P7  | **Show-ready**            | Timeline is a score, not a graph. BPM sync, blackout, MIDI/OSC. The show can be run entirely from the keyboard.       |
| P8  | **Muscle-memory bridges** | Keyboard profiles map to the user's origin app (Blender/Unity/Premiere/Resolume) instead of inventing a new language. |

**Why:** Projection mapping sits at the intersection of three disciplines — media editing (Premiere), 3D manipulation (Blender), and live performance (Resolume). Users arrive with years of muscle memory in at least one of these. We do not copy any single app; we borrow the strongest pattern from each, in the region where it matters most, and we standardize on the one behavior no pro app can live without: _you can always see and control the output state_.

---

## 2. Window Layout — The Anatomy

### 2.1 Master layout (default "Projection" workspace)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  MENU BAR   File  Edit  View  Scene  Tools  Window  Help                 │
├──────────────────────────────────────────────────────────────────────────┤
│  TOOLBAR   [V][G][R][S][W] | ⟲⟳ | [Scene ▾] | ● ARM | ⏻ Blackout | ✨ AI │
├──────────────┬───────────────────────────────────────────┬───────────────┤
│  LEFT DOCK   │              CENTER                       │  RIGHT DOCK   │
│ ┌──────────┐ │  ┌─────────────────────────────────────┐  │ ┌───────────┐ │
│ │ Scenes   │ │  │  PREVIEW — Editing viewport         │  │ │ Inspector │ │
│ │ + Graph  │ │  │  [view nav | gizmos | overlays]     │  │ ├───────────┤ │
│ │ Assets   │ │  └─────────────────────────────────────┘  │ │ Scene     │ │
│ │Projectors│ │  ┌─────────────────────────────────────┐  │ │ Graph     │ │
│ │ Cameras  │ │  │  LIVE — Program output              │  │ └───────────┘ │
│ │ Calib.   │ │  │  [● LIVE | Proj1 | 1920×1080@60     │  │               │
│ │ Jobs     │ │  │   | 12.4ms | 60 FPS]               │  │               │
│ │ History  │ │  └─────────────────────────────────────┘  │               │
├──────────────┴───────────────────────────────────────────┴───────────────┤
│  TIMELINE — Tracks, transport, timecode, markers, keyframes  │ Props │ AI │
│  (split horizontally; Timeline Properties & AI Assistant share tabs)     │
├──────────────────────────────────────────────────────────────────────────┤
│  STATUS BAR  [hint: "Press G to move selection"] │ Scene · Cam1 · Proj1  │
│              │ 3 disp · 1 proj | ● OK | ● Live | 60 FPS | 12.4ms | 1920×1080 │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Center: the dual viewport

The center is **two fixed companion windows**, not tabs.

|              | **PREVIEW (left)**                            | **LIVE (right)**                                                              |
| ------------ | --------------------------------------------- | ----------------------------------------------------------------------------- |
| Role         | Editing viewport — the sandbox                | Program output — exactly what the projector shows                             |
| Content      | Camera, meshes, warp, calibration, AI effects | Rendered output identical to projector signal                                 |
| Interactions | Full manipulation (select/move/warp/camera)   | Read-only. Click = inspect. No edits.                                         |
| Header       | Scene name, view mode, grid/overlay toggles   | ● LIVE indicator, projector selector, FPS, output res, output status, latency |
| Failure mode | Freezes, glitches — safe                      | Must never glitch; watchdog protected                                         |

**Why left/right, not tabs (OBS uses tabs in Studio Mode):** projection mapping is a _comparison_ discipline. During calibration you must see the edit state and the true output simultaneously. Tabs hide one of them. Side-by-side is the reason OBS Studio Mode exists; we make it permanent. Left = input side, right = output side — the same left-to-right signal flow as a mixing console, which is the mental model of most projection artists.

**Live window header (always visible, never hideable):**

```
● LIVE   │ Projector: Proj 1 ▾   │ 1920×1080 @ 60   │ 12.4 ms latency   │ Output: STABLE
```

- **● LIVE dot:** red = outputting, gray = idle/not armed, amber = warning (dropped frames), flashing red = error/watchdog.
- **Projector selector:** instant switch of which projector the Live window maps to (in multi-projector setups, Live window shows _one_ projector at a time, or a grid — see Multi Projector workspace).
- **Latency:** measured preview-to-output delay. Critical for interactive shows.
- **Output status:** `STABLE` / `WARNING (3 dropped)` / `BLACKOUT` / `CALIBRATION PATTERN`.

### 2.3 Second-monitor behavior

- **F11:** Live window expands to a borderless fullscreen window on the projector's display (remembered per display).
- The projector output and the Live window are the _same render_ — the Live window is the app's view of the program; the projector is the program. No third render path.

**Why:** OBS's pattern of "preview in-app + fullscreen on monitor" is proven and eliminates a whole class of "why does the projector show something different" bugs. One program output, two views of it.

### 2.4 Status bar — always-on hardware & output telemetry

The status bar is the machine room: it must always answer "is the show healthy?"

| Segment                | Content                                                                                       | Source                                             |
| ---------------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Hint (left)            | Contextual shortcut hint, e.g. "Press G to move selection"                                    | Focused view                                       |
| Hardware (left-center) | `3 disp · 1 proj` — live display/projector counts                                             | `HardwareManager.snapshot()` via `StatusViewModel` |
| Health dot             | `● OK` (green) / `● WARN` (amber) — any validation issue, renderer not ready, or display lost | `HardwareStatus.healthy`                           |
| Output                 | `● Live \| 60 FPS \| 12.4ms \| 1920×1080` — output state, FPS, latency, resolution            | Output session + renderer telemetry                |

The hardware segment is driven by `StatusViewModel(hardware_provider=...)` — a
polled `HardwareStatus` snapshot (`display_count`, `projector_count`,
`healthy`), decoupled from the event bus so the status bar never blocks the
output path. Health is amber when `HardwareStatus.healthy` is false
(issue_count > 0) and green otherwise.

---

## 3. Docking & Panel System

### 3.1 Rules (QWidget-based, matching Qt QDockWidget semantics)

| Rule | Behavior                                                                                                                                                                             |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| R1   | Every panel can be: **docked** (left/right/top/bottom), **tabbed** (stack with another panel), **floating** (dragged out), **auto-hidden** (collapses to an edge strip, OBS-style).  |
| R2   | Panels drag by title bar; dropping on an edge docks, dropping on a panel stacks it as a tab, dropping on a _tab strip_ reorders.                                                     |
| R3   | Double-click title bar ⇄ float/unfloat.                                                                                                                                              |
| R4   | Every panel has a title bar menu (▾): `Float · Auto-hide · Close · Move to workspace… · Reset size`.                                                                                 |
| R5   | Layout is saved **per workspace**, not globally. Switching workspace switches the whole layout.                                                                                      |
| R6   | **Layout Lock** (Window → Lock Layout, or `Ctrl+Alt+L`): pins all docks; accidental drags are impossible. Auto-enabled when entering _Live Show_ workspace and while output is LIVE. |
| R7   | Panel state persists in project settings (`.projectai`) + app settings (window geometry). Crash-restores last workspace.                                                             |
| R8   | Plugins can register panels through the existing plugin system — the dock system is a public extension point.                                                                        |

### 3.2 Left dock — collapsible section stack

One dock, stacked sections (like a collapsible outliner), each drag-reorderable and splittable into its own dock:

1. **Scenes** (top-level compositions)
2. **Scene Graph** (hierarchy of objects inside the active scene — Blender/Unreal outliner)
3. **Assets** (media + generated content)
4. **Projectors** (outputs)
5. **Cameras** (inputs)
6. **Calibration Sessions**
7. **Jobs** (AI/scan/export queue)
8. **History** (undo)

Each section header shows a count badge and a one-click context action (e.g., Scenes: `+`).

### 3.3 Right dock

1. **Inspector** (contextual — the star panel, see §4.1)
2. **Console** (logs — hidden by default, appears on first error)

The **AI Assistant** is not a right-dock panel — it lives in the bottom dock,
tabified with Timeline Properties (see §3.4, §11).

### 3.4 Bottom dock

**Timeline** (§8) spread across the full width, split against a tab stack of
**Timeline Properties** and **AI Assistant** (§11), plus optional **Curve
Editor** and **Control Mapping** panels that slide in when their workspace
requires them.

---

## 4. Panel Reference

### 4.1 Inspector (right, contextual)

The Inspector is a single panel that re-skills itself based on selection. Selection of **nothing** → _Scene_ properties (resolution, color space, render settings).

| Selection           | Inspector shows                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Projector           | Output device, resolution/refresh, color profile, edge blending, bezel/lens correction, blackout settings, latency stats |
| Camera              | Source (device/file), resolution, FPS, lens/perspective, live feed thumbnail, record settings                            |
| Mesh                | Geometry info, transform, material slot, warp density, subdivision, surface type (planar/curved)                         |
| Material            | Texture, color, emissive, opacity, blend mode, projection mapping UVs, LUT                                               |
| Calibration session | Steps status, RMS error, pattern settings, per-point table, save/export                                                  |
| Timeline clip       | Source, in/out, speed, opacity, transitions, keyframe lane summary                                                       |
| AI Effect           | Effect type, model, prompt used, seed, strength, parameter sliders                                                       |
| Multiple selection  | Multi-edit table (edit a property on all selected at once — key for multi-projector parity)                              |

**Core interactions:**

- Groups are collapsible sections; values have **reset (↺)** and **copy/paste value** (`Ctrl+C`/`Ctrl+V` on the field) — copying parameters between projectors is a first-class workflow.
- Every value field can be **keyframed** (diamond button → adds keyframe at playhead, Premiere/After Effects habit).
- Numeric fields: drag to scrub, `Ctrl+drag` fine, double-click type, `Esc` cancel. Shift-click = typed input.
- Breadcrumb at top: `Scene > Crown Mesh > Material > Emissive` — always know _where_ you are.

**Why:** Blender and Unity/Unreal both converge on a single contextual properties panel; it is the "nothing hidden, one click away" principle made physical. A dedicated per-object window for 7 object types would drown the screen.

### 4.2 Scenes + Scene Graph (left)

- **Scenes** = top-level compositions. `+` creates; double-click renames; drag to reorder; right-click: duplicate, delete, properties. One scene is _active_ (played/edited), one can be _live_ — see "Edit during live show" (§9.5).
- **Scene Graph** = object hierarchy: cameras, meshes, lights, AI effect nodes, masks. Drag to reparent, visibility 👁 toggle, lock 🔒 toggle, search filter. Selecting in graph ⇄ selects in viewport (bidirectional).

**Why:** OBS's Sources list is too flat for 3D scenes; Blender's Outliner is too heavy for media people. A two-level structure (scenes → objects) with search is the minimal structure that satisfies both.

### 4.3 Assets (left)

Media browser for everything a projection is built from:

- Tabs: **Generated** (AI output history), **Images**, **Videos**, **Meshes**, **Materials**, **Prompts** (saved prompt library), **Templates**.
- Thumbnail grid with size slider; list view for power users.
- Drop onto viewport = instant add to scene (auto-warp if a surface is targeted); drop onto timeline = clip.
- Import via `Ctrl+I` or drag from OS. Watched folders (auto-import new files).
- AI-generated images land here first (Jobs → Assets), never directly on the timeline — user decides placement.

**Why:** Premiere's Project panel is the strongest mental model for "stuff I can use"; adding AI-specific tabs keeps generated content first-class without inventing a new paradigm.

### 4.4 Projectors (left)

- List of detected outputs: name, display, resolution/refresh, state (idle/live/blackout), edge-blend group.
- Master controls: **Arm All / Arm Selected**, **Blackout All** (safe — see §9.4), output test pattern.
- Per-projector: output device, color profile, latency, independent settings.

### 4.5 Cameras (left)

- Capture devices + file inputs; live thumbnail; resolution/FPS; record to disk; camera calibration status (for 3D geometry estimation).
- A camera can be a _surface scanner_ (geometry estimation) or a _projection camera_ (rendering viewpoint). Type is labeled on the row.

### 4.6 Calibration Sessions (left)

- List of sessions with status: `DRAFT → VALIDATED → DEPLOYED`.
- **Deployed** sessions are attached to a projector+scene pair and drive the warp.
- Right-click: new session (wizard), duplicate, validate, export calibration pack, delete.

### 4.7 Jobs (left)

- Async operation queue: AI generation, object scan, export, calibration compute.
- Each job: name, progress bar, cancel/retry, open result. Completion → toast + asset appears in Assets.
- Jobs run in background; the UI never blocks. (The existing job system maps 1:1.)

**Why:** AI generation takes seconds-to-minutes. A visible queue with progress turns waiting into planning. This is the same role Resolume's render queue plays, generalized.

### 4.8 History (left)

- Undo stack rendered as a list with **branching** (like Blender's History): when you undo and take a new action, the old branch is preserved and explorable.
- Actions labeled in human terms: _"Move CrownMesh (2.4, 0, 0)"_, _"AI: Add divine particles (Seed 4821)"_.
- Drag to scrub history; Ctrl+Z/Ctrl+Shift+Z operate the active branch.

**Why:** AI actions are non-deterministic — if a generation "can't be undone" users won't trust it. Making every AI action an undoable, _visibly listed_ command is the trust mechanism. Branching matters because artists experiment.

### 4.9 Console (bottom, hidden by default)

Structured logs (info/warn/error), filterable, opens automatically on first error with the error highlighted. Every entry has "copy" and "open docs" actions.

---

## 5. Top Menu & Toolbar

### 5.1 Menu bar

| Menu       | Items                                                                                                                                                                                                          |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **File**   | New Project… · Open Project… · Recent ▸ · Save `Ctrl+S` · Save As… · Import Assets `Ctrl+I` · Export ▸ (Video / Image Sequence / Single Frame / Calibration Pack) · Collect & Pack… · Project Settings… · Quit |
| **Edit**   | Undo `Ctrl+Z` · Redo `Ctrl+Shift+Z` · Cut/Copy/Paste `Ctrl+X/C/V` · Duplicate `Ctrl+D` · Delete `Del` · Select All `Ctrl+A` · Deselect `Esc` · **Command Palette… `Ctrl+Shift+F`**                             |
| **View**   | Workspaces ▸ · Panels ▸ (toggle every panel) · Toggle Grid · Toggle Gizmos · Toggle Overlays · Lock Layout `Ctrl+Alt+L` · Fullscreen `F11` · Output Window (second monitor)                                    |
| **Scene**  | New Scene `Ctrl+Shift+N` · Duplicate Scene · Delete Scene · Scene Properties…                                                                                                                                  |
| **Tools**  | Calibrate Wizard… · Scan Object… · Generate with AI `Ctrl+J` · Warp Wizard… · Live ▸ (Arm `F9` · Send to Live `Enter` · Blackout `B`) · Control Mapping…                                                       |
| **Window** | Workspaces list · Reset Workspace to Default · Save Layout As… · Panels ▸ · Lock Layout                                                                                                                        |
| **Help**   | Shortcuts Reference `F1` · Documentation · Calibration Guides · Check for Updates · Diagnostics… · About                                                                                                       |

**Command Palette (`Ctrl+Shift+F`):** fuzzy search across _every_ menu item, tool, workspace, and panel toggle. Typing "blackout", "calibr", "warp" finds the action instantly. **(Why: Unreal/Unity/VSCode proved the palette is the fastest path to "everything one click away" — it scales beyond menu depth.)**

### 5.2 Toolbar (single row, icon + label, tooltip always shows shortcut)

```
[V Select][G Move][R Rotate][S Scale][W Warp]  │  ⟲ Undo ⟳ Redo  │  Scene: [Temple ▾]
│  ● ARM LIVE   ⏻ Blackout   ⇄ Send Preview→Live  │  ✨ AI Generate  ◈ Scan  ⌬ Calibrate
│  ⊞ Snap   ▦ Grid   ⧉ Gizmo space
```

- **Tool mode buttons** are contextual: in viewport context they act on objects; in _Warp_ mode they act on warp points; in _Mesh_ mode on vertices. One toolbar, three modes (see §7.3).
- **● ARM LIVE** is the largest element — red, distinct. Its state is always visible.
- **⇄ Send Preview→Live** (`Enter`) — the OBS "Transition" equivalent; pushes current preview state to program.
- Tooltips show the shortcut: `Move (G) — drag to translate, X/Y/Z to constrain`.

**Why:** OBS's toolbar is minimal because its mode-set is small. Projection mapping needs tool modes (Blender), so the toolbar splits into _mode_ + _actions_. The ARM button is deliberately oversized: in a live venue, finding it by glance must take zero seconds.

---

## 6. Keyboard Shortcuts

### 6.1 Design: keymap profiles

Shortcuts are **contextual** (viewport vs timeline vs inspector) and shipped as **profiles** matching origin apps:

| Profile                  | Basis                               | Audience   |
| ------------------------ | ----------------------------------- | ---------- |
| `ProjectionAI (default)` | This spec                           | New users  |
| `Blender`                | G/R/S transforms, Tab modes         | 3D artists |
| `Unity/Unreal`           | Q/W/E/R transforms                  | Game devs  |
| `Premiere`               | I/O marks, JKL, B/C tools           | Editors    |
| `Resolume`               | Space trigger, B blackout, D freeze | VJs        |

Any key can be remapped (Settings → Keyboard). Profiles only re-map the _conflicting_ keys (transforms, marking); universal keys (Ctrl+S/Z/C/V, Space, arrows) never change.

**Why:** The audience is explicitly multi-origin. Forcing Blender users off G/R/S costs real hours of muscle memory; profiles cost us one settings screen. Universal keys stay universal because they're the same across every app we're borrowing from.

### 6.2 Core shortcut table (default profile)

#### Global / app

| Action              | Shortcut                  |
| ------------------- | ------------------------- |
| Save / Save As      | `Ctrl+S` / `Ctrl+Shift+S` |
| Undo / Redo         | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Duplicate / Delete  | `Ctrl+D` / `Del`          |
| Command Palette     | `Ctrl+Shift+F`            |
| Import assets       | `Ctrl+I`                  |
| AI Generate         | `Ctrl+J`                  |
| Lock layout         | `Ctrl+Alt+L`              |
| Fullscreen (Live)   | `F11`                     |
| Shortcuts reference | `F1`                      |
| New Scene           | `Ctrl+Shift+N`            |

#### Output & performance (the safety cluster — never remap these by default)

| Action                             | Shortcut   | Why                                                         |
| ---------------------------------- | ---------- | ----------------------------------------------------------- |
| **Arm Live / Send to Live**        | `F9`       | Far from accidental keys; one press, big consequence        |
| **Send Preview → Live**            | `Enter`    | OBS "Transition" muscle memory; deliberate key              |
| **Swap Preview ↔ Live**            | `Ctrl+Tab` | OBS Studio Mode swap                                        |
| **Blackout**                       | `B`        | Resolume's blackout; must be instant, one key, no confirm   |
| **Emergency output safe (freeze)** | `D`        | Resolume's freeze — hold to pause output, release to resume |

#### Workspaces & panels

| Action                  | Shortcut            |
| ----------------------- | ------------------- |
| Workspace 1–7           | `Ctrl+1` … `Ctrl+7` |
| Toggle left dock        | `Ctrl+Shift+L`      |
| Toggle right dock       | `Ctrl+Shift+R`      |
| Toggle timeline         | `Ctrl+Shift+T`      |
| Toggle AI Assistant     | `Ctrl+Shift+A`      |
| Toggle Inspector        | `Ctrl+Shift+I`      |
| Reset current workspace | `Ctrl+Shift+0`      |

#### Viewport (context: object/warp/mesh mode)

| Action                                     | Shortcut                                        |
| ------------------------------------------ | ----------------------------------------------- |
| Select tool                                | `V`                                             |
| Move (grab)                                | `G` (+`X/Y/Z` axis, `Shift` plane, type number) |
| Rotate                                     | `R`                                             |
| Scale                                      | `S`                                             |
| Warp tool                                  | `W`                                             |
| Frame selection                            | `F` (numpad `.`)                                |
| Orbit / Pan / Zoom                         | `MMB drag` / `Shift+MMB` / `Wheel`              |
| Cycle viewport mode (Object → Warp → Mesh) | `Tab`                                           |
| Focus camera to view                       | `Ctrl+Alt+Numpad 0`                             |

#### Timeline (context: timeline focused)

| Action                            | Shortcut                                    |
| --------------------------------- | ------------------------------------------- |
| Play / Pause                      | `Space`                                     |
| Stop and return to playhead start | `Shift+Space`                               |
| Shuttle: reverse / play / forward | `J` / `K` / `L` (repeat presses ramp speed) |
| Frame step                        | `←` / `→`                                   |
| Step 10 frames / 1 second         | `Shift+←/→` / `Ctrl+←/→`                    |
| Jump to start / end               | `Home` / `End`                              |
| Set In / Out point                | `I` / `O`                                   |
| Clear In/Out                      | `Ctrl+Shift+I/O` (timeline context)         |
| Add marker                        | `M`                                         |
| Razor (split clip)                | `B`                                         |
| Selection tool                    | `V` (timeline context)                      |
| Snap toggle                       | `Ctrl+Shift+S` (timeline context)           |
| Nudge selected clip ±1 frame      | `Alt+←/→`                                   |
| Loop playhead region              | `Ctrl+L` (toggle — see note)                |

> **Note:** `L` conflicts between shuttle-ramp and loop. Default: **loop toggle = `Ctrl+L`**; `L` remains shuttle-forward-ramp. Documented in the reference, remappable in Premiere profile where `L` expects different semantics. _(Why: Premiere users hammer L for fast-forward; Resolume users hammer L for loop. Profiles resolve this cleanly.)_

**Why this cluster:** transport must be operable **without looking** — JKL/I/O/M/B are Premiere's proven blind-touch cluster. During a show the operator's eyes are on the stage, not the keyboard.

---

## 7. Mouse & Input Interactions

### 7.1 Viewport (Preview window)

| Gesture                 | Action                                                                         |
| ----------------------- | ------------------------------------------------------------------------------ |
| `LMB` click             | Select (click-through object priority: gizmo > object > empty space deselects) |
| `LMB` drag on object    | Move (in Move tool) or marquee-select (in Select tool)                         |
| `RMB`                   | Context menu (Blender + OBS both: right-click is the power menu)               |
| `MMB` drag              | Orbit camera                                                                   |
| `Shift+MMB` drag        | Pan camera                                                                     |
| `Wheel`                 | Zoom (cursor-anchored)                                                         |
| `Shift+Wheel`           | Dolly (camera move, not zoom — for calibration precision)                      |
| `Alt+LMB` drag          | Alternative orbit (Unity habit) — enabled in Unity profile                     |
| `Ctrl+LMB` drag gizmo   | Snapped transform                                                              |
| Double-click object     | Focus + open its Inspector section                                             |
| `H`                     | Hide selection · `Alt+H` unhide (Blender habit)                                |
| Drag asset onto surface | Instant add + auto-warp to that surface (drop highlight shows target)          |

**Viewport overlays (all toggleable):** grid, axis gizmo, selection outlines, warp-point handles, projection frustum preview, surface labels, safe-area guides, checkerboard for alpha. Overlay buttons live at the viewport top-right corner (OBS-style small icons, `O` toggles all).

### 7.2 Live window

| Gesture     | Action                                                                                          |
| ----------- | ----------------------------------------------------------------------------------------------- |
| `LMB` click | Pick/identify — highlights the source object in Preview/Scene Graph (inspection only)           |
| `RMB`       | Context menu: _Send Preview → Live_, _Select projector_, _Blackout_, _Fullscreen_, _Copy frame_ |
| `Wheel`     | Zoom inspect view (never affects projector)                                                     |
| Drag        | Nothing. The Live window does not accept edits.                                                 |

**Why read-only:** the one unforgivable bug in this product is an accidental edit reaching the projector. Read-only is not a limitation; it is the trust contract.

### 7.3 Tool modes in the viewport

Three modes, one toolbar:

1. **Object mode (`Tab` → Object):** whole objects: move/rotate/scale. Gizmo: translate/rotate/scale handles + center dot.
2. **Warp mode (`W` or `Tab`):** per-corner/per-point control — the heart of projection mapping. Points snap to mesh/surface; `G` moves a point; `Ctrl` snaps; proportional editing (`O` toggle, Blender) pushes neighboring points smoothly. Warp grid density from Inspector.
3. **Mesh mode (`Tab`):** raw geometry editing (vertex-level) for advanced users — the escape hatch for anything warp points can't do.

**Why:** Resolume users know only warp handles; Blender users need full mesh editing; both must coexist without a "mode explosion". Three modes with one keyboard cycle (`Tab`) is the smallest set that covers both.

---

## 8. Timeline & Playback Design

The timeline is the **show's score** — in editing it composes animation, in Live Show workspace it _runs_ the performance.

### 8.1 Track architecture

Track types (each lane typed; types can be added/removed/reordered freely):

| Track                | Renders? | Purpose                                                                       |
| -------------------- | -------- | ----------------------------------------------------------------------------- |
| **Projection Layer** | ✅       | Content clips (media/AI content) mapped to surfaces                           |
| **Animation Layer**  | ✅       | Procedural/parameter animation clips (position, rotation, warp morph)         |
| **AI Effects**       | ✅       | Effect clips (particles, style transfer, depth warps) with strength envelopes |
| **Masks**            | ✅       | Mask clips (shape/edge/motion masks) applied to layers                        |
| **Lighting**         | ✅       | Light/ambient/projector-brightness clips (DMX/Art-Net integration)            |
| **Audio**            | ✅       | Audio waveform clips (drives BPM sync, reaction)                              |
| **Transitions**      | overlay  | Crossfade/dip/wipe between adjacent clips (Premiere model)                    |
| **Keyframes**        | overlay  | Dedicated keyframe lanes per animated property (per clip, expandable)         |
| **Speed Ramps**      | overlay  | Speed envelope per clip (Premiere rate-stretch + variable speed)              |
| **Notes**            | ❌       | Non-rendering annotation clips ("Cue 3: fade crown"), colored, searchable     |
| **Markers**          | ❌       | Global time markers (Premiere `M`), including BPM grid markers                |

Design rules:

- **Non-rendering tracks (Notes/Markers) are always available**, visually distinct (dimmed, dashed), and can be collapsed to a single strip.
- Clips are color-coded by type with a consistent legend; color = type, not preference.
- **Timeline header** shows timecode ruler with BPM grid overlay toggle, snap toggle, zoom controls.
- **Timecode** displayed SMPTE `HH:MM:SS:FF` (frame-rate aware: 24/25/30/60) plus a big transport readout with **-frames** pre-roll counter for shows.

### 8.2 Transport

```
⏮ ◀◀ ◀ ■ ▶ ▶▶ ⏭   |  ⏱ 00:12:34:12   |  Loop [In-Out ▾]  |  BPM 120.0 ▾  |  🎚 Master 100%
```

- Play/stop/pause, JKL shuttle, frame stepping, loop with in/out points, **BPM sync** (Resolume): clips can be snapped to the BPM grid, tempo-driven effects, tap-tempo `T`.
- **Scrubbing:** wheel scrubs (cursor-anchored); `Alt`+drag = scrub without moving playhead (audition); audio scrubbing toggle.
- **Hardware:** jog/shuttle wheels and MIDI transport supported via Control Mapping.

### 8.3 Keyframes & curves

- Diamond keyframes on the clip's lane; expand a clip to reveal its **property lanes** (After Effects style): position, rotation, scale, opacity, warp morph, effect strength.
- Right-click keyframe: linear/ease-in/ease-out/bezier/smooth; **Curve Editor** panel (bottom) for bezier refinement.
- Copy/paste keyframes across clips/projectors (`Ctrl+C/V` with keyframe selected) — the multi-projector parity workhorse.

### 8.4 Timeline ↔ everything

- Selecting a clip → Inspector shows clip properties → Scene Graph highlights its objects.
- Dragging a surface/scene object onto a track auto-creates the right clip type.
- Markers can be _named cues_ and are listed in a **Cue List** panel in Live Show workspace (double-click = jump + trigger).

**Why:** Premiere's timeline won because track types are explicit and predictable; After Effects won for animation because property lanes and curves are explicit. We merge them: typed tracks (Premiere) with expandable property lanes (AE) — and we add the one thing Premiere lacks for live use: **BPM as a first-class timebase**, because projection shows are scored to music.

---

## 9. User Flows — Navigation

### 9.1 Create a project

1. Launch → **Start screen** (OBS-free, Premiere-style): _New Project_ · _Open Recent_ · _Templates_ · _Sample Content_.
2. New Project dialog: name, default scene, **canvas resolution + FPS** (auto-suggested from detected projector), color space (sRGB/DCI-P3), workspace preset.
3. Projector auto-detect lists outputs; user assigns the primary projector.
4. App opens in **Projection** workspace with one empty scene and a default camera.

**Why:** no empty-desktop anxiety (OBS's biggest onboarding hole), but no wizard overload either — 5 fields, sensible defaults, skip-able. Templates (Single Surface / Multi Surface / Stage Show / Empty) get first-timers to a projected image in minutes.

### 9.2 Calibrate (the critical flow)

1. **Tools → Calibrate Wizard** (or Calibration panel → New Session).
2. Choose projector (defaults to primary) → wizard shows the 4 steps as a progress strip.
3. **Pattern**: app switches that projector's output to a calibration pattern (checkerboard/feature grid) — output state = `CALIBRATION PATTERN`, clearly flagged in Live header.
4. **Capture**: select camera → live feed appears in Preview → auto-detect pattern corners (existing CV pipeline) → green overlay confirms.
5. **Refine**: manual drag of warp points if auto-detect is imperfect (Warp mode). Live window shows the _projected_ pattern so the user sees exactly what the projector does.
6. **Validate**: re-projection of a test pattern (grid + text) → RMS error score → `VALIDATED`.
7. Session is saved, marked **DEPLOYED** to projector+scene; content now warps automatically.
8. Re-calibrate anytime; previous sessions remain selectable (venue changes).

**Why:** calibration is the moment of highest trust-building. Patterns are **never** content — the output state machine guarantees a pattern can't be mistaken for the show, and vice-versa. Validation with a numeric error score gives non-experts confidence and experts the precision they demand.

### 9.3 Preview (composing)

- Everything in Preview is a sandbox: full undo, free camera, overlays.
- Add content: drag from Assets onto a surface (auto-warp) or drop on timeline; type a prompt in AI Assistant → generated result lands in Assets → drag in.
- Preview shows exactly the render the projector _would_ show — same pipeline, no "preview approximation".

**Why:** the #1 trust killer in mapping apps is preview ≠ output. One render pipeline, two windows. (This is the ModernGL architecture's promise, and the UI enforces it by construction.)

### 9.4 Go live

1. Press **● ARM LIVE (`F9`)** → output state `ARMED` (Live header: `● ARMED — press Enter to send`). Projector still dark.
2. Press **Enter (Send Preview → Live)** → output goes live. First arm in a session shows a one-time confirmation: _"Output will be visible on the projector. Remember: B = blackout."_
3. Live header: `● LIVE · 60 FPS · 12.4ms · STABLE`.
4. From now on: **B** blackout, **D** freeze, **Ctrl+Tab** swap preview↔live, timeline runs the show.

**Why two steps:** OBS's single "Start Streaming" is fine for streaming; projection shows are physical and public. The two-step arm (F9 → Enter) prevents the two real accidents: _projecting by accident_ and _projecting the wrong state_. The one-time confirmation teaches the blackout key at the exact moment it matters.

### 9.5 Edit during a live show

Two modes, both explicit in the Live header:

- **Staged (default):** edits affect Preview only. **Enter** pushes Preview → Live (whole-state or per-selection via right-click "Send selection to Live").
- **Armed / Direct:** toggle in Live header (`F9` toggles arm state). Edits go live immediately — for real-time tweaks ("make it warmer", moving a warp point mid-show).

Rules:

- Scene switching is instant and never interrupts output (crossfade option per scene).
- Blackout/freeze are always available regardless of mode.
- Timeline playback continues; editing during playback is allowed (Premiere habit).
- Any AI action during a show lands in Preview first — a live show never gets a surprise generation.

**Why:** this is the Resolume lesson — performers must be able to improvise _and_ to stage changes safely. The mode toggle is one key away, and the default is the safe one.

### 9.6 Save

- `Ctrl+S` → `.projectai` project directory (JSON manifest + scenes + assets + thumbnails; versioned, diff-friendly).
- **Autosave** (every 5 min + on major actions) with **crash recovery** (restore dialog with timeline of autosaves).
- **Save As + Collect & Pack** (Premiere's Project Manager): copies referenced assets into the project folder — mandatory before venue moves.
- Calibration packs export standalone (`.pjcal`) — share calibration between machines/venues.

### 9.7 Export

| Export           | Produces                                                                                                   |
| ---------------- | ---------------------------------------------------------------------------------------------------------- |
| Video            | MP4 (H.264) / ProRes / DNxHD via FFmpeg — rendered from the _Live_ pipeline (what-you-saw-is-what-you-get) |
| Image sequence   | PNG/TIFF/EXR frames                                                                                        |
| Single frame     | Current live frame, high-res capture                                                                       |
| Calibration pack | `.pjcal` for reuse                                                                                         |
| Live output      | The projector signal itself (already a "video output" — NDI/Spout/Syphon out for integration, §13)         |

Export runs as a **Job** (visible progress, cancellable), defaulting to project frame rate and output resolution.

---

## 10. Workspace System

Workspaces are saved layouts = (dock arrangement + visible panels + tool state + viewport mode). Switching is instant; each remembers its own state.

| Workspace                | Center emphasis                        | Panels emphasized                                             | Hidden for focus                    |
| ------------------------ | -------------------------------------- | ------------------------------------------------------------- | ----------------------------------- |
| **Projection** (default) | Preview + Live                         | Scenes, Assets, Inspector, Timeline                           | —                                   |
| **Calibration**          | Preview (camera view) + Live (pattern) | Calibration steps, Projectors, Inspector                      | Timeline, AI                        |
| **AI Creation**          | Preview                                | AI Assistant (large), Assets, Jobs, Inspector, Prompt library | Live (collapsed to strip), Timeline |
| **Animation**            | Preview                                | Timeline (tall), Curve Editor, Inspector                      | Live (collapsed), AI                |
| **Live Show**            | Live (large), Preview (small strip)    | Cue List, Projectors, Master transport                        | All editing panels; Layout locked   |
| **Multi Projector**      | Live grid (N projectors)               | Projectors matrix, Edge Blend, Inspector                      | AI, Timeline (collapsed)            |
| **Minimal**              | Preview + Live                         | none (toolbar only)                                           | Everything                          |

- `Ctrl+1…7` switches workspaces; **Window → Save Layout As…** persists custom ones; **Reset Workspace** restores defaults.
- Workspaces can be reordered; custom workspaces appear alongside presets.
- **Live Show** workspace auto-locks layout (R6) and hides destructive/editing panels — the app becomes an instrument, not a browser.

**Why:** Blender's workspace tabs proved that "layout as a tool" beats "layout as a preference". Each phase of the projection lifecycle (build → calibrate → compose → animate → run) wants a different physical instrument; forcing one layout forces compromise in every phase.

---

## 11. AI Assistant UX (bottom dock — tabified with Timeline Properties)

### 11.1 Anatomy

```
┌──────────────────────────────────────────────┐
│ ✨ AI Assistant                        [▾][×]│
│ Context:  Scene: Temple · Cam: Cam1 ·        │
│           Proj: Proj1 · Sel: Crown Mesh      │
│           ⏱ 00:12:34:12 · Frame 18,720       │
├──────────────────────────────────────────────┤
│ [Suggestions:]  Animate only the crown ·     │
│   Add divine particles · Make projection     │
│   warmer · Morph warp to curve B ·           │
├──────────────────────────────────────────────┤
│ (chat history — streaming responses,         │
│  action cards at the end of each reply)      │
├──────────────────────────────────────────────┤
│ [Scope: ●Selection ▾]  [Prompt input…]  [▶]  │
└──────────────────────────────────────────────┘
```

- **Context bar** (always visible): what the AI _knows_ — scene, camera, projector, current selection, timeline position, frame. Each chip is clickable to change what's in scope.
- **Scope selector:** `Selection` / `Scene` / `Whole Show` — the AI acts on the scope, never on the Live output.
- **Suggestion chips** — contextual, generated from current selection ("Animate only the crown" when a crown mesh is selected).
- **Action cards** — AI responses end in explicit action cards, not vague text: `Apply to selection`, `Create clip on timeline`, `Add keyframes`, `Regenerate (Seed 4821)`, `Save prompt to library`.

### 11.2 Trust rules (hard)

1. AI actions are **commands** — they hit the undo stack like any tool. (History panel shows them.)
2. AI **never touches Live output**. Results land in Preview or Assets. User decides to send.
3. Every generation records its **seed + prompt + model** — visible in the clip's Inspector, reproducible.
4. Generations are async **Jobs**; the chat shows progress inline ("Generating… ⏳") and the result can be dropped into the scene/timeline with one click.
5. Failure is graceful: "I couldn't do that — here's what I need" + fallback suggestion.

**Why:** an AI copilot in a live-performance tool is only trustworthy if it cannot surprise you on stage. The context bar solves the "vague prompt" problem (the AI demonstrably knows what you're pointing at), and the command/undo integration solves the "AI did something I can't revert" problem. Example prompts from the spec — _"Animate only the crown"_ (scope=selection), _"Add divine particles"_ (creates an AI Effect clip on the timeline), _"Make projection warmer"_ (touches color/lighting params in Inspector) — all resolve through this machinery.

---

## 12. Visual Language (brief)

| Token       | Value                                                                | Why                                                                                               |
| ----------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Theme       | Dark, near-black chrome (`#16181D` surfaces, `#0F1114` wells)        | Projection work happens in dark rooms; bright UIs destroy dark adaptation (OBS/Resolume are dark) |
| Accent      | Amber `#FF9E00` (selection/active)                                   | Light is the product — amber reads as "illumination"; distinct from status colors                 |
| Status      | Live/record `#FF3B30` · warn `#FFC107` · ok `#30D158`                | Traffic-light semantics, red reserved for output/record only                                      |
| Type        | UI: Inter/Noto Sans; timecode & numbers: JetBrains Mono              | Monospace numerals don't jitter during playback — a live-readability requirement                  |
| Density     | Compact by default, 3 density settings                               | Premiere/Resolume density is the professional baseline; accessibility needs larger option         |
| Iconography | Line icons, 16px toolbar / 14px panel                                | OBS-style restraint; tooltips carry the labels                                                    |
| Motion      | 100–150ms ease on panel open/close only. Never on viewport or output | Zero motion in the live path; the output must feel like hardware                                  |

Dark adaptation is a real venue requirement: the app must not blind the operator between cues.

---

## 13. Professional Recommendations

1. **Output watchdog:** if a Live frame stalls >250 ms, output falls back to black + on-screen alert; a `SAFE` pattern (projector test card) optional. Auto-recover on next successful frame. _(Non-negotiable for paid shows.)_
2. **Dual-GPU / dedicated output path:** Live render on a separate device when available; the UI never contends with the projector.
3. **Color management end-to-end** (DaVinci model): working color space, per-projector ICC profiles, output LUTs, preview scopes (histogram/vectorscope toggle in Live header) for "make it warmer" workflows.
4. **Control Mapping panel** (Resolume/TouchDesigner parity): map _any_ parameter to MIDI/OSC/Art-Net/DMX — transport, blackout, clip triggers, warp morphs, AI strength. Ship with a default mapping template for common controllers (APC40/Mini). Stage integration is how this app gets hired.
5. **NDI/Spout/Syphon output** for feeding OBS/screens/projector servers; NDI input for remote cameras.
6. **Multi-projector parity tools:** copy-paste parameters across projectors, edge-blend assistant (overlap detection + gamma ramp), alignment grid overlay.
7. **Cue list + show rehearsal mode:** name cues, dry-run with fake timecode, countdown pre-roll per cue, and a **show script export** (PDF/CSV) for the operator's paper backup.
8. **Plugin panels** via the existing plugin system — docks are a public extension point (R8). A panel plugin API means the app grows where the community needs it (e.g., a tracker-integration panel).
9. **Crash hygiene:** autosave + recovery (§9.6); diagnostics exporter for support; logging that excludes content data.
10. **Onboarding:** template projects, sample content pack, interactive calibration guide overlay, and a "Shortcuts Reference" (`F1`) that is _searchable_ and shows the active profile's bindings.
11. **Performance telemetry in status bar:** GPU/CPU meters, dropped-frame counter with history sparkline (OBS habit) — performance problems become visible before they become disasters.
12. **Accessibility:** full keyboard navigation, visible focus, contrast-safe status colors (not red/green alone — shapes + text too), 200% UI scale, screen-reader labels on all tools.

---

## 14. Design Rationale — Why Every Major Decision

| Decision                                                  | Why                                                                                                                                                                  |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Dual fixed center windows (Preview/Live)**              | Mapping is a comparison discipline; tabs hide state; left→right = input→output console logic. Read-only Live = trust contract.                                       |
| **Output state machine (Idle → Armed → Live → Blackout)** | Physical, public, expensive-to-mess-up output. Two-step arm prevents the two classic accidents. Pattern ≠ content, enforced by state.                                |
| **Contextual single Inspector**                           | "Nothing hidden, one click away" with the smallest physical footprint (Blender/Unity consensus). Keyframing + copy-paste live in every field.                        |
| **Typed timeline + property lanes + BPM**                 | Premiere's predictability + After Effects' animatability + Resolume's musicality. The timeline is the show's score, so Notes/Markers are first-class, non-rendering. |
| **Keymap profiles**                                       | Audience is multi-origin; muscle memory is the most expensive asset users bring. Universal keys stay universal.                                                      |
| **Command palette**                                       | The guarantee that "everything one click away" survives feature growth.                                                                                              |
| **Workspace-as-instrument**                               | Different phases want different physical layouts; Blender proved presets + instant switching is the right unit. Live Show locks itself down.                         |
| **AI as undoable commands with visible context**          | Trust in a live tool = no surprises + always reversible + demonstrably aware of your selection. AI never touches Live.                                               |
| **Jobs queue for async work**                             | AI/scan/export take time; a visible queue turns waiting into planning; UI never blocks.                                                                              |
| **Status bar as always-on telemetry**                     | OBS's discipline: you always know output state, FPS, latency. In a venue, ignorance is a catastrophe.                                                                |
| **Read-only Live window**                                 | The one unforgivable bug is accidental live edits; removing the _ability_ removes the bug class.                                                                     |
| **Patterns go through the Live path**                     | Calibration must test the real projector chain; flagging it as `CALIBRATION PATTERN` prevents confusion.                                                             |
| **Branching, labeled history**                            | AI actions are non-deterministic; visible, branchable history is the trust + safety net for experimentation.                                                         |

---

## Appendix A — Panel visibility matrix (default workspaces)

| Panel                | Projection | Calibration | AI Creation | Animation | Live Show       | Multi Proj | Minimal |
| -------------------- | ---------- | ----------- | ----------- | --------- | --------------- | ---------- | ------- |
| Scenes + Scene Graph | ✅         | ✅          | ✅          | ✅        | —               | ✅         | —       |
| Assets               | ✅         | —           | ✅          | ✅        | —               | —          | —       |
| Projectors           | ✅         | ✅          | —           | —         | ✅              | ✅         | —       |
| Cameras              | ✅         | ✅          | —           | —         | —               | —          | —       |
| Calibration          | ✅         | ✅ (steps)  | —           | —         | —               | —          | —       |
| Jobs                 | ✅         | —           | ✅          | —         | —               | —          | —       |
| History              | ✅         | ✅          | ✅          | ✅        | —               | —          | —       |
| Inspector            | ✅         | ✅          | ✅          | ✅        | —               | ✅         | —       |
| AI Assistant         | ✅         | —           | ✅ (large)  | —         | —               | —          | —       |
| Timeline             | ✅         | —           | —           | ✅ (tall) | ✅ (show strip) | —          | —       |
| Curve Editor         | —          | —           | —           | ✅        | —               | —          | —       |
| Cue List             | —          | —           | —           | —         | ✅              | —          | —       |
| Console              | hidden     | hidden      | hidden      | hidden    | hidden          | hidden     | hidden  |
