# ADR-010: Typed Background Job System with Priority Queue

## Status

Accepted

## Context

Long-running work — AI content generation, vision processing, calibration — must not block the UI thread. We needed a way to run background work with progress reporting, cancellation, and failure isolation, while keeping the domain free of threading concerns.

## Decision

Introduce a **typed job system** centered on an abstract `Job`:

- `src/projectionai/domain/job.py` defines `JobStatus` (`queued`, `running`, `completed`, `failed`, `cancelled`), `JobPriority`, `JobLogEntry`, and the `Job` ABC that implementations subclass to define their work.
- `JobManager` (`src/projectionai/managers/job_manager.py`) owns a background thread pool with a priority queue, running jobs off the UI thread.
- Progress and lifecycle are surfaced via typed events: `JobQueued`, `JobStarted`, `JobProgress`, `JobCompleted`, `JobFailed`, `JobCancelled` — the UI listens to these instead of polling.
- Jobs support cooperative cancellation so long operations can be aborted cleanly.

## Consequences

**Positive**

- UI stays responsive during long operations.
- Typed status/progress events make job state observable to any listener (status bar, job panel).
- `Job` ABC keeps domain code ignorant of threading primitives — tests drive jobs directly.

**Negative**

- Cooperative cancellation requires each `Job` to check cancellation points; a misbehaving job can't be force-killed.
- The thread pool adds complexity over a naive `threading.Thread` per job, justified by priority handling and capacity control.

## Compliance

Implemented in `src/projectionai/domain/job.py` (types + `Job` ABC) and `src/projectionai/managers/job_manager.py` (thread pool, priority queue, event emission). Tested in `tests/unit/test_job_manager.py`.
