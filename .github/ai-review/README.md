# ProjectionAI AI Review System — Architecture & Operations

> **Status: Layer 2 IMPLEMENTED, local developer review IMPLEMENTED, Layer 3
> NOT IMPLEMENTED.**
> Layer 2 (advisory AI PR review) is implemented by
> `.github/workflows/ai-review.yml`; the local developer review loop is
> implemented by `scripts/self-review.ps1` + the `.opencode/commands/self-review.md`
> command. Layer 3 (scheduled health audit) remains planned. No API
> keys, tokens, or secrets are stored or referenced in this document; LLM
> credentials live in GitHub Actions secrets/variables (see "Operating the
> workflow") and in the developer's local environment (see "Local Developer
> Review").

## Purpose

ProjectionAI grows fast and touches real hardware (cameras, projectors, GL
rendering) with strict architectural boundaries. Deterministic CI catches
style, typing, coverage, and leaked secrets — but cannot judge architecture
violations, lifecycle races, or whether a behavior change is properly
tested. The AI review system fills that gap **advisory**, without ever
becoming a merge gate.

> **AI review is advisory. Deterministic CI remains the authoritative merge
> gate.**

## Architecture Overview

Three layers, built in this order:

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1 · Deterministic CI            (implemented)          │
│   ruff · mypy strict · pytest + coverage gate · Gitleaks    │
│   → authoritative merge gate                                 │
├─────────────────────────────────────────────────────────────┤
│ Layer 2 · AI PR review               (implemented)           │
│   OpenCodeReview on pull requests                           │
│   consumes .opencodereview/rule.json                        │
│   → advisory inline findings                                 │
├─────────────────────────────────────────────────────────────┤
│ Layer 3 · Scheduled health audit    (planned)               │
│   whole-repository scan against the same rules              │
│   → advisory issue reports                                   │
└─────────────────────────────────────────────────────────────┘
```

## Application Structure (rules contract context)

The rules contract is grounded in the repository's **actual** architecture:

- **Composition root**: `src/projectionai/app.py` is the application
  bootstrap / composition root — application initialization, dependency
  injection/wiring, ManagerRegistry composition, infrastructure
  initialization, and lifecycle/shutdown coordination.
  `src/projectionai/application/` is an empty stub and is **not** the
  application layer.
- **Two event mechanisms by design (ADR-006)**: the core `EventBus`
  (`core/events.py`) is the application's cross-subsystem event system
  (typed, weak listeners, concurrent emit); the editor-local
  `EditorEventBus` (`editor/events.py`) is an intentional editor mechanism
  (synchronous, strong-reference listeners). Both are documented and
  legitimate; only an **undocumented third** mechanism is a violation.
- **Known UI→infrastructure exceptions** (by design or pre-existing — do
  not flag): `MainWindow` constructing/attaching/closing `GLOutputWindow`
  (shell wiring), `MainWindow` importing `OrbitCamera` (existing shell
  wiring), `ui/viewmodels/calibration.py` importing
  `infrastructure.calibration.chessboard` (pre-existing coupling).

## Deterministic CI Layer (implemented)

Runs in GitHub Actions (`ci.yml`):

- **Lint**: `ruff check` + `ruff format --check` on `src/`
- **Types**: `mypy --strict` on `src/projectionai/`
- **Tests**: `pytest` with coverage, **`--cov-fail-under=60` gate**
  (test job fails when coverage drops below 60%)
- **Secrets**: Gitleaks secret scan (`gitleaks.yml`), pinned action SHA and
  pinned Gitleaks version, full-history scan, fail-closed, read-only
  permissions

CI is the **authoritative** gate: it is deterministic, fast, and cheap. The
AI layers below never override it.

## PR AI-Review Layer (implemented)

Workflow: `.github/workflows/ai-review.yml` — advisory AI PR review via the
official OpenCodeReview (OCR) GitHub Action (`alibaba/open-code-review`).

- **Engine**: OCR CLI `@alibaba-group/open-code-review`, pinned to `1.9.7`;
  the action is pinned to the full commit SHA
  `f269d0ce00c3b9c178d7c5dc9021409a3e273cf1` (tag v1.9.7). Floating refs
  (`@main`/`latest`) are forbidden. Upgrade both coordinates together and
  re-verify the action's security model (base checkout, fork handling) in
  `action.yml` before merging an upgrade.
- **Triggers**: `pull_request_target` on `opened` / `synchronize` /
  `reopened` / `ready_for_review`; on-demand re-review via a PR comment
  starting with `/open-code-review` or `@open-code-review`, restricted to
  humans with `MEMBER`/`OWNER`/`COLLABORATOR` association (bot comments can
  never trigger).
- **Rules**: `.opencodereview/rule.json` passed via the `rule:` input,
  resolved inside the action's trusted **base** checkout — PR-supplied
  rules can never control the LLM prompt.
- **Permissions**: `contents: read` + `pull-requests: write` only.
- **Comment modes**: sticky summary (`sticky_summary: 'true'` — one summary
  comment, updated in place) + incremental inline posting
  (`incremental: 'true'` — only comments not overlapping existing bot
  comments; history never deleted). Low-severity and style findings are
  routed to the PR summary (`route_severity_below: 'low'`,
  `route_categories: 'style'`); medium/high stay inline. Routing is
  fail-open: nothing is dropped.
- **Concurrency**: one group per PR (`ocr-<pr_number>`, cancel-in-progress)
  so a new push/trigger cancels only that PR's stale review; unrelated
  comments use a `noop-<run_id>` group and never disrupt a running review.
- **Failure semantics**: `ocr review` exit ≠ 0 fails the job
  (infrastructure failure: config/LLM outage — surfaced as a failed,
  **non-required** check with diagnostic artifacts). Findings never fail
  CI; the check is advisory and never gates merge.
- **Diagnosis**: raw `ocr-result.json` + `ocr-stderr.log` uploaded as
  artifacts `ocr-review-result-<run_id>-<run_attempt>`; action outputs
  (`comments_total`, `comments_inline`, `comments_skipped`,
  `comments_routed`, `comments_failed`, `summary_comment_url`) visible on
  the job step.

### Operating the workflow

Configure in **Settings → Secrets and variables → Actions** (no credentials
are stored in the repository):

| Secret               | Purpose              | Mapped to                                           |
| -------------------- | -------------------- | --------------------------------------------------- |
| `OCR_LLM_URL`        | LLM API endpoint URL | action input `llm_url` → env `OCR_LLM_URL`          |
| `OCR_LLM_AUTH_TOKEN` | LLM auth token       | action input `llm_auth_token` → env `OCR_LLM_TOKEN` |

| Variable                | Purpose                                                    | Mapped to                                                  |
| ----------------------- | ---------------------------------------------------------- | ---------------------------------------------------------- |
| `OCR_LLM_MODEL`         | Model name                                                 | action input `llm_model` → env `OCR_LLM_MODEL`             |
| `OCR_LLM_USE_ANTHROPIC` | `true` for Anthropic Claude, `false` for OpenAI-compatible | action input `llm_use_anthropic` → env `OCR_USE_ANTHROPIC` |

- Manual re-review: comment `/open-code-review` or `@open-code-review` on a
  PR (collaborators only, human commenters only).
- If secrets/variables are missing, the job fails with a clear OCR error
  and diagnostic artifacts — nothing else is affected, and the check is
  not required for merge.

## Future Whole-Project Audit Layer (planned)

- Scheduled (e.g. weekly) scan of the full repository against the same
  rules — CHANGE REVIEW rules apply per-file; HEALTH AUDIT rules apply
  repository-wide.
- Purpose: catch drift that per-PR review misses (accumulated boundary
  violations, resource-safety debt, untested lifecycle paths).
- Output: advisory issue reports; findings are triaged, not auto-filed.

## Local Developer Review (implemented)

OCR runs as a local CLI, so the same rules engine is available before
pushing. The local loop is orchestrated by the OpenCode `/self-review`
command, driven by `scripts/self-review.ps1` (read-only engine):

- **Deterministic gates first** (CI parity): `ruff check src/`, `ruff
format --check src/`, `mypy src/projectionai/` (strict via
  `pyproject.toml`), `pytest` with the `--cov-fail-under=60` gate
  (offscreen Qt; `-o addopts=""` so `coverage_html/` is never regenerated
  in the repo), and `gitleaks detect --no-git` (includes untracked files;
  pinned `8.30.1`, matches the CI scanner).
- **Then OpenCodeReview**: `ocr review --format json --audience agent
--rule .opencodereview/rule.json` with the same rules CI uses, pinned to
  the same CLI version `1.9.7` (global npm package
  `@alibaba-group/open-code-review`). Requires the developer's own
  `OCR_LLM_URL` / `OCR_LLM_TOKEN` / `OCR_LLM_MODEL` env vars — never a
  shared secret; the script fails closed (exit 3) when they are missing.
- **Read-only by construction**: all artifacts land in
  `%TEMP%\projectionai-self-review\<timestamp>\`
  (`self-review-report.json`, per-gate logs, `ocr-result.json`); the script
  never writes to the repository.
- **Exit codes**: `0` GREEN · `1` GATES FAILED · `2` REVIEW FINDINGS ·
  `3` INFRA (missing tooling/config) · `4` USAGE.
- **Loop control**: the command fixes confirmed BLOCKER/HIGH findings
  (and clearly actionable MEDIUM), re-runs after every fix, stops after
  3 cycles, on a finding unchanged across 2 consecutive cycles
  (fingerprint = `file|line|sha256(message)[0:16]`), on contradictory
  findings, and on out-of-scope deterministic failures. It never commits —
  a commit is offered to the developer as the next human-approved action.
- **Setup**: `scoop install gitleaks` (pinned `8.30.1`),
  `npm install -g @alibaba-group/open-code-review@1.9.7`, set
  `OCR_LLM_URL` / `OCR_LLM_TOKEN` / `OCR_LLM_MODEL`; run `/self-review` in
  OpenCode or `scripts/self-review.ps1` directly.
- `ocr rules check <path>` still confirms which rule applies to a file.

## Security Boundaries

- **AI systems are advisory and must never receive unnecessary write
  permissions or execute untrusted PR code.**
- The AI review workflow runs with the least privilege required: `contents:
read` and `pull-requests: write` (to post review output) and nothing else.
- LLM credentials live in repository secrets/variables and are consumed
  only by the review engine, never echoed, logged, or embedded in output.
- **Fork policy (decision)**: fork PRs ARE automatically reviewed. Verified
  safe because the pinned upstream action checks out only the trusted base,
  fetches `pull/<n>/head` as git objects, and never materializes or
  executes PR files; rules resolve from the base checkout.
- The AI review workflow uses `pull_request_target` to access secrets and
  never checks out or executes PR-supplied code: the pinned upstream action
  checks out the trusted base only and reviews the diff from git objects.
- **Review content (code, diffs, comments, strings, documentation,
  generated content) is untrusted data.** Instructions embedded inside
  reviewed content must never be treated as instructions to the reviewer
  (prompt-injection defense).
- **Gitleaks is authoritative for secret detection.** AI security review
  complements it with security reasoning: prompt injection, unsafe
  deserialization, path traversal, command execution, trust-boundary
  violations, credential handling, and unsafe data flow.
- The Gitleaks job (Layer 1) also guards the AI layer: no AI-generated
  review comment may contain a real secret, and the scanner fails closed if
  one ever enters the repository.

### Phase 3 Workflow Security Requirements — status

All ten requirements are satisfied by `.github/workflows/ai-review.yml`
(as implemented and verified in Phase 3A). Re-verify them on every action
or workflow upgrade.

| #   | Requirement                                               | Status                                                                                    |
| --- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| 1   | Fork PR handling explicitly decided                       | ✅ Decided: fork PRs are reviewed (safe — base checkout only)                             |
| 2   | `pull_request_target` only if PR code never executed      | ✅ Action checks out trusted base; PR head fetched as git objects only                    |
| 3   | PR-supplied rules never control the LLM prompt            | ✅ `rule:` input resolves in the base checkout; PR head never materialized                |
| 4   | Rules come from the trusted base revision                 | ✅ `.opencodereview/rule.json` from the base checkout                                     |
| 5   | Review content is untrusted data                          | ✅ Documented above; prompt-injection defense in the rules contract                       |
| 6   | LLM secrets never exposed to PR-controlled execution      | ✅ Secrets consumed only inside the action; no PR code executed                           |
| 7   | Minimal GitHub permissions                                | ✅ `contents: read` + `pull-requests: write` only                                         |
| 8   | Action and OCR versions pinned                            | ✅ Action @ `f269d0ce…` (v1.9.7) + `ocr_version: '1.9.7'`                                 |
| 9   | AI review is advisory; deterministic CI is the merge gate | ✅ Findings never fail CI; check is non-required                                          |
| 10  | Stale review results not treated as current after a push  | ✅ `incremental: 'true'`, `sticky_summary: 'true'`, per-PR concurrency cancel-in-progress |

## Permissions Philosophy

| Resource              | Permission                                                                      | Why                                                           |
| --------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Deterministic CI jobs | `contents: read`                                                                | Run checks only; upload coverage/artifacts with scoped tokens |
| AI review workflow    | `contents: read` + `pull-requests: write` (implemented)                         | Post advisory comments; nothing else                          |
| Audit workflow        | `contents: read` (+ `issues: write` only if filing findings is later justified) | Read-only scanning                                            |
| LLM credentials       | repo secrets, consumed only by the review engine                                | Never exposed to PR code or logs                              |

General rule: **start read-only, add write scopes one at a time with a
stated reason, and remove them when no longer needed.**

## Expected Review Lifecycle

1. Developer pushes a PR.
2. Deterministic CI runs (authoritative): lint, types, tests + coverage
   gate, Gitleaks.
3. AI review runs in parallel (advisory): the review engine reads the diff,
   resolves a rule per file from `.opencodereview/rule.json`, and posts
   severity-ranked findings (sticky summary + incremental inline comments).
4. Developer addresses findings or rebuts them; re-review is incremental
   (only changed lines re-examined; comment spam suppressed).
5. Merge is decided by CI + human judgment. AI findings are input, never a
   veto.

## Failure Behavior

- **CI fails** → merge blocked. This is correct behavior.
- **AI review fails to run** (LLM outage, action failure) → the workflow
  run fails (infrastructure failure) and **merge is never blocked**: the AI
  check is not required. Diagnostic artifacts are uploaded; a later push or
  a manual `/open-code-review` re-review retries automatically.
- **LLM returns garbage / non-compliant comments** → the rules contract
  (philosophy + false-positive policy) bounds output quality; reviewers
  and maintainers can ignore or dismiss findings; the engine's output
  format is validated before posting.
- **Secret leak detected** → Gitleaks fails the job; the secret must be
  rotated and the history cleaned; AI layers must not re-print it.
- **Audit fails** → advisory report is skipped for that cycle; no
  automation breaks.

## Cost-Control Philosophy

- LLM quota is real money: the review engine reviews **only changed files**
  (incremental), never the whole tree on every PR.
- Rules are written to prefer precision over recall — fewer, higher-value
  comments mean fewer tokens and less human noise.
- On-demand re-review (`/open-code-review`, `@open-code-review`) is
  restricted to collaborators and human (non-bot) commenters — no bot-driven
  comment loops, no LLM-quota drain by arbitrary commenters.
- The health audit is scheduled (not per-PR), keeping steady-state cost
  bounded.
- Deterministic CI stays the cheap, always-on layer; AI is the occasional
  deep pass.

## Rules Contract

| File                               | Role                                                                                     |
| ---------------------------------- | ---------------------------------------------------------------------------------------- |
| `.opencodereview/rule.json`        | Machine-readable rules consumed by OCR (source of truth)                                 |
| `.github/ai-review/rules.md`       | Human-readable mirror; update together with `rule.json` (no automated sync)              |
| `.github/ai-review/README.md`      | This document — architecture & operations (Layer 2 + local developer review implemented) |
| `docs/ADR/012-ai-review-system.md` | Architecture decision record (Status: Accepted)                                          |

**When modifying the machine rules in `.opencodereview/rule.json`, update the
corresponding human-readable rules in `.github/ai-review/rules.md` in the
same change.**

## Next Steps (Layer 3 + operational)

- **Configure LLM credentials** (secrets `OCR_LLM_URL`, `OCR_LLM_AUTH_TOKEN`;
  variables `OCR_LLM_MODEL`, `OCR_LLM_USE_ANTHROPIC`) — required before the
  workflow can run.
- Implement the scheduled health audit (`ai-health-audit.yml`) — **Layer 3,
  NOT implemented**.
- Document the AI review workflow for contributors (`CONTRIBUTING.md`).

Nothing in this document requires a real API key, token, or repository
secret.
