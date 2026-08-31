# Phase 7.5 — PLAN — Pattern Presentation Integration

## Objective

Build a production-grade pattern presentation layer that takes the canonical `CalibrationSequence` from Phase 6 and presents each pattern on the selected projector/display deterministically, with proper frame boundaries, safety, and cancellation.

## Implementation Strategy

**Qt-free domain + Qt integration layer.** Core orchestration in `PatternPresentationSession` is pure async Python. Qt integration (fullscreen, GL context, display routing) lives in `PatternPresentationTarget` (Qt-agnostic protocol + `QTPatternPresentationTarget` implementation).

## Task Breakdown

### T1: `PatternPresentationSession` (Core Orchestrator)

**File:** `src/projectionai/services/pattern_presentation.py`

```python
class PresentationMode(StrEnum):
    FULL_SEQUENCE = "full_sequence"
    SINGLE_PATTERN = "single_pattern"
    BLACK = "black"
    WHITE = "white"
    HIDE = "hide"

@dataclass(frozen=True)
class PresentationConfig:
    mode: PresentationMode = PresentationMode.FULL_SEQUENCE
    pattern_index: int | None = None  # for SINGLE_PATTERN
    settle_ms: float = 20.0
    presentation_timeout: float = 2.0

@dataclass(frozen=True)
class PatternPresentationState:
    pattern_index: int | None
    total_patterns: int
    mode: PresentationMode
    timestamp_ns: int | None
    is_complete: bool

class PatternPresentationSession:
    """Qt-free orchestrator for pattern sequence presentation."""

    def __init__(
        self,
        target: PatternPresentationTarget,
        config: PresentationConfig | None = None,
    ) -> None: ...

    async def start(self) -> None: ...
    async def show(self, sequence: CalibrationSequence) -> None: ...
    async def show_single(self, pattern: CalibrationPattern) -> None: ...
    async def hide(self) -> None: ...
    async def stop(self) -> None: ...

    @property
    def state(self) -> PatternPresentationState: ...

    async def wait_for_presentation(self) -> int: ...
```

### T2: `PatternPresentationTarget` (Display Routing)

**File:** `src/projectionai/services/pattern_presentation.py` (same file)

```python
class PatternPresentationTarget(Protocol):
    """Display target for pattern presentation."""

    async def enter_fullscreen(self) -> None: ...
    async def show_pattern(self, pattern: CalibrationPattern) -> int: ...
    async def hide(self) -> None: ...
    async def exit_fullscreen(self) -> None: ...
    @property
    def resolution(self) -> tuple[int, int]: ...
```

### T3: `QTPatternPresentationTarget` (Qt Implementation)

**File:** `src/projectionai/infrastructure/display/qt.py` (extend existing)

```python
class QTPatternPresentationTarget:
    """Qt-based display target using QtPatternProjector."""

    def __init__(self, projector: QtPatternProjector) -> None:
        self._projector = projector
        self._window: _ProjectionWindow | None = None

    async def enter_fullscreen(self) -> None: ...
    async def show_pattern(self, pattern: CalibrationPattern) -> int: ...
    async def hide(self) -> None: ...
    async def exit_fullscreen(self) -> None: ...
    @property
    def resolution(self) -> tuple[int, int]: ...
```

### T4: Integration with Existing Safety

- `PatternPresentationSession.stop()` calls `target.hide()` then `target.exit_fullscreen()`
- No parallel safety state machine — safety is delegated to `OutputManager` at the application layer
- Cancellation via `asyncio.CancelledError` propagates to session stop

### T5: Tests (15+ required)

**File:** `tests/unit/services/test_pattern_presentation.py`

Tests needed:

1. Session creates with default config
2. Session enters fullscreen and presents pattern sequence
3. Session presents single pattern
4. Session hides display
5. Session stops cleanly
6. Session state tracks pattern index correctly
7. Session state tracks completion
8. Session timeout on presentation
9. Session cancellation propagates
10. Target protocol compliance
11. QT target creates projection window
12. QT target enters fullscreen
13. QT target shows pattern and returns timestamp
14. QT target hides display
15. QT target exits fullscreen
16. Integration with CalibrationSequence (8 patterns)
17. Pattern resolution matches target resolution
18. Black/white mode presentation
19. Config validation

## Constraints

- PatternPresentationSession must NOT create parallel safety state machine
- Do not change any hardware-pending gate
- Do not rewrite Phase 6 calibration algorithms
- Do not duplicate ProductionWorkflow state
- No xfail, no skip
- Stop at review — DO NOT START 7.6

## Files to Create/Modify

| File                                                | Action                                   |
| --------------------------------------------------- | ---------------------------------------- |
| `src/projectionai/services/pattern_presentation.py` | CREATE — Core session + target protocol  |
| `src/projectionai/infrastructure/display/qt.py`     | MODIFY — Add QTPatternPresentationTarget |
| `tests/unit/services/test_pattern_presentation.py`  | CREATE — 15+ tests                       |

## Dependencies

- `CalibrationSequence`, `CalibrationPattern` (Phase 6.2)
- `QtPatternProjector` (existing)
- `asyncio` (standard library)
- `dataclasses` (standard library)

## Validation Criteria

1. 15+ tests passing
2. ruff check clean
3. ruff format clean
4. mypy strict clean
5. No new pre-existing errors introduced
6. PatternPresentationSession is Qt-free
7. No parallel safety state machine
8. All hardware gates unchanged
