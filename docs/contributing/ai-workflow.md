<!-- markdownlint-disable-file MD013 -->

# MMO AI Workflow

Use this workflow for AI-authored or AI-assisted changes. Keep it short, plain,
and tied to repo evidence.

## Start From Repo Truth

Review the current repo truth before a non-trivial change.

- Read `AGENTS.md` first. `CLAUDE.md` and `GEMINI.md` defer to it.
- Treat mirrored workspace copies such as `.claude/agents/` as convenience
  copies, not authoritative review surfaces.
- Read `docs/architecture/system-map.md` when the change touches runtime shape,
  trust boundaries, packaged data, support tools, release paths, or hidden
  entrypoints.
- Read `docs/architecture/coverage-ledger.md` when the touched area is a risky
  tracked slice or when a summary might sound broader than the evidence.
- Read the relevant `docs/unknowns/*.md` file before claiming a slice is
  understood.
- Read `docs/security/logging-audit.md` and
  `docs/unknowns/logging-audit.md` when the change touches logging,
  telemetry, traces, stderr forwarding, machine-readable JSON, or support
  artifacts.
- Read `docs/review/adversarial-pass.md`,
  `docs/unknowns/adversarial-pass.md`,
  `docs/review/scenario-stress-test.md`, and
  `docs/unknowns/scenario-stress-test.md` when the touched slice already has
  review history there.

## Write A Plain Change Record

Use the PR template for every non-trivial change. Keep each field factual.

- What changed
- Why it changed
- What remains unclear
- Risk changed, if any
- Approval needed, if any
- Docs updated
- Tests or checks run
- Repo evidence reviewed

## Move Docs When Risky Areas Change

Update only the docs that help the next engineer explain the change.

- Update the system map when a runtime unit, hidden entrypoint, trust boundary,
  support path, or control-plane path changes.
- Update the coverage ledger when a meaningful risky tracked slice changes
  status, gains a new blind spot, or needs a new row.
- Update a runbook, review note, release-path note, rollback note, or
  observability note when the change alters a protected or non-obvious path.
- Update the relevant unknowns file before smoothing over uncertainty.

## Keep Unknowns Visible

Do not guess. Add or update an unknown when the repo does not yet prove the
claim you want to make.

Each unknown should say:

- area or file
- concern
- why it matters
- evidence found so far
- likely owner if known
- next best check
- risk level

## Respect Approval Gates

`AGENTS.md` is the authority for protected areas. Human approval is required
before edits that touch:

- auth, access control, secrets, crypto, or credentials
- plugin execution boundaries or marketplace install flows
- render, export, QA, compare, fallback, FFmpeg, or other audio-changing paths
- delete, cleanup, retention, sync, bundle, mirror, or packaged-data behavior
- schema or ontology removals, status meaning changes, or migration semantics
- concurrency, locking, queueing, or state-corruption risks
- Tauri sidecars, packaged desktop smoke, GUI RPC, local servers, or external
  callbacks
- privileged CI or CD automation, release tooling, or support tooling with
  production reach

## Keep Coverage Honest

Do not let one clean path stand in for a whole slice.

- Move the coverage ledger when a risky tracked slice changes in a meaningful
  way.
- Add a new unknown when a change reveals a darker parallel path instead of
  claiming the slice is closed.
- Keep support tooling, release control planes, Pages deploy, and machine-readable
  outputs separate from the main runtime story when they change.
- Keep mirrored workspace copies separate from canonical steering docs when a
  summary, review, or comment pass names authoritative sources.

## Re-check Anti-Dark-Code Comments

If you edit a path that already has anti-dark-code comments, check that the
comments still match the code.

- Update stale comments in the same change.
- Do not leave an old safety note behind after the code moved.

## Logging And Telemetry Drift

The maintenance validator only catches one narrow class of mistakes: same-line
logging calls with obvious sensitive markers such as `password`, `secret`, or
`access_token`.

- It does not prove logging is safe.
- It does not catch stderr forwarding, JSON stdout, trace uploads, or shared
  artifact leaks.
- Use the logging audit and reviewer judgment for those paths.
