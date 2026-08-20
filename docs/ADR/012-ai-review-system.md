# ADR-012: Automated AI Code Review and Repository Health Auditing

## Status

Accepted

## Context

ProjectionAI is a real-time desktop application driving physical cameras,
projectors, GL rendering, and background task lifecycle. The codebase enforces
strict architectural boundaries (Clean Architecture: UI → managers/services →
domain; pure domain layer; single hardware authorities) and deterministic CI
(Ruff, mypy strict, coverage gate, Gitleaks secret scanning). The composition
root is `src/projectionai/app.py` (application initialization, dependency
injection/wiring, ManagerRegistry composition, infrastructure initialization,
lifecycle/shutdown coordination); `src/projectionai/application/` is an empty
stub. The codebase intentionally contains two documented event mechanisms
(ADR-006): the core `EventBus` (`core/events.py`) and the editor-local
`EditorEventBus` (`editor/events.py`). As the project
grows, deterministic checks alone cannot catch the failure modes that matter
most here: architecture-boundary violations, camera/output lifecycle races,
resource leaks, and behavior changes without meaningful test coverage.

The project needs an automated architectural review layer that:

- understands the repository's real structure and invariants (documented in
  `.opencodereview/rule.json` and `.github/ai-review/rules.md`),
- reviews pull requests incrementally without spamming comments,
- can also audit the whole repository on a schedule,
- costs little, fails softly, and never becomes a merge gate.

## Decision

Use **OpenCodeReview (OCR)** as the initial AI-review engine because it
supports:

- **path-scoped rules** — per-directory rule resolution matching ProjectionAI's
  layered architecture (`.opencodereview/rule.json`),
- **incremental PR review** — review only changed code and affected
  dependencies (CHANGE REVIEW mode),
- **local review** — the same engine runs as a CLI for developers before
  pushing,
- **whole-tree audit** — repository-wide scans (HEALTH AUDIT mode) against the
  same rule contract.

Rules live in `.opencodereview/rule.json` (machine-readable, consumed by OCR)
with a human mirror in `.github/ai-review/rules.md`. The rules encode twelve
repository invariants (single hardware authority, UI/hardware boundary,
camera lifecycle safety, camera identity, event architecture, manager
lifecycle, output/projector safety, domain boundary, service boundaries,
renderer boundary, resource safety, tests prove behavior) plus Python
engineering, security, and severity/false-positive guidance.

**Compatibility with ADR-006 (dual event mechanisms).** ProjectionAI
intentionally contains two event mechanisms:

1. the core `EventBus` (`core/events.py`) — the application's
   cross-subsystem event system;
2. the editor-local `EditorEventBus` (`editor/events.py`) — synchronous,
   strong-reference listeners serving the editor subsystem's separate
   lifecycle.

ADR-012 does not prohibit the documented `EditorEventBus`. Its event
invariant is specifically: **do not introduce an undocumented third
event/notification mechanism, or bypass the established bus appropriate to
the subsystem.** This is compatible with ADR-006 because ADR-006 documents
both buses as intentional design; the review rules treat documented
architectural mechanisms as legitimate and flag only undocumented or
unjustified additions.

**This tool choice is not irreversible.** PR-Agent remains a documented
alternative/secondary reviewer if OCR does not meet quality requirements;
the rule contract is engine-agnostic enough to be replayed through another
engine.

### Architecture

Three layers, built in order:

1. **Layer 1 — Deterministic CI** (implemented): Ruff, mypy strict, pytest
   with `--cov-fail-under=60` coverage gate, Gitleaks secret scan. This is
   the authoritative merge gate.
2. **Layer 2 — AI PR review** (implemented): OCR reviews pull requests using
   `.opencodereview/rule.json`, posting advisory findings.
3. **Layer 3 — Scheduled repository health audit** (planned): periodic
   whole-repository scans against the same rules.

### Security

AI systems are advisory and must never receive unnecessary write permissions
or execute untrusted PR code. Review workflows run read-only against the
diff; LLM credentials live in repository secrets and are consumed only by
the review engine; any `pull_request_target` usage (if required for secrets)
must never check out or execute PR-supplied code.

### Migration

**Rules first, automation second.** The rules contract (this phase) precedes
any workflow implementation, so the review behavior is specified and
reviewable before any automation consumes it.

## Consequences

**Positive**

- Architecture violations, lifecycle races, and resource leaks get caught
  close to the change that introduces them.
- Rules are explicit and versioned — the reviewer's behavior is auditable
  and testable, not a black box.
- Cost is bounded: incremental PR review + scheduled audits, precision over
  recall.
- Advisory by design: a failed or absent AI review never blocks a merge,
  while deterministic CI remains authoritative.

**Negative**

- LLM reviews are probabilistic: false positives and missed findings are
  possible — hence the false-positive policy and human judgment at merge
  time.
- LLM token costs and a new failure surface (LLM outage, action failure)
  that must fail soft.
- Two rule files (`rule.json` + `rules.md`) must be kept in sync by hand —
  no automated synchronization exists.

## Compliance

The rules contract lives in `.opencodereview/rule.json` (machine-readable,
consumed by OCR), mirrored in `.github/ai-review/rules.md`; the planned
system is documented in `.github/ai-review/README.md`. An independent audit
of the rules contract (Phase 2.5) and a correction pass (Phase 2.6)
refined the rules: the dual-bus carve-out for `EditorEventBus` (ADR-006),
the UI shell-wiring exceptions (`GLOutputWindow`, `OrbitCamera`,
`chessboard`), `app.py` as the composition root, deterministic-tool
ownership of lint/type/secret gates, and the change-review vs
health-audit scope distinction. These corrections are reflected in
`rule.json`, `rules.md`, and this record. Workflow
implementation (Layer 2/Layer 3), LLM credential configuration, and
contributor documentation are tracked as follow-up phases and will be
recorded here when implemented.
