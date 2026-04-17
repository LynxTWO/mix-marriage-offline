# AGENTS.md - MMO Anti-Dark-Code Guide

## 1. Purpose and scope

`AGENTS.md` defines how AI-assisted work happens in this repo.
`CLAUDE.md` and `GEMINI.md` are compatibility companions and must stay aligned
with this file.

The goal is simple:

- keep code explainable
- keep reviews grounded in evidence
- keep risky work behind approval gates
- keep future changes safer because the repo tells the truth about itself

This repo is an existing multi-surface system. Keep guidance tied to the real
MMO surfaces: `src/mmo/`, `schemas/`, `ontology/`, `src/mmo/data/`,
`plugins/`, `src/mmo/data/plugins/`, `examples/plugin_authoring/`, `gui/`,
and `gui/desktop-tauri/`.

## 2. Product principles and standing promises

Preserve these verified MMO promises unless the user explicitly asks to change
them:

- Offline-first. No network is required for core functionality.
- Deterministic outputs. The same inputs and settings should produce the same
  results within documented tolerances.
- Explainable artifacts and evidence. Issues and actions should say what,
  why, where, confidence, and evidence when the contract calls for it.
- Bounded authority. Auto-apply only low-risk actions inside declared limits.
  Escalate high-impact moves.
- Ontology-first contracts. Canonical IDs for roles, issues, actions, params,
  units, evidence, layouts, and downmix policies stay owned by the ontology.
- Layout safety. Renders must respect translation gates and downmix similarity
  checks.

Do not weaken these promises with comments, docs, code, release copy, or UI
text unless the user explicitly asks for that policy change.

## 3. What dark code means in this repo

Dark code is production behavior whose purpose, boundaries, failure modes, data
handling, or ownership stay hard to explain after a careful repo read.

In MMO, dark code includes:

- hidden audio mutation, render fallback behavior, or QA decisions that are not
  obvious from code, schemas, receipts, fixtures, and docs
- hidden filesystem side effects such as silent deletes, bundle rewrites,
  packaged-data rewires, cache writes, or workspace writes
- plugin authority, gate behavior, or approval semantics that are not obvious
  from manifests, receipts, or docs
- schema, ontology, status, or artifact meanings redefined in scattered call
  sites
- missing ownership, failure-mode notes, rollback notes, or sensitivity notes
  for stems, session data, media tags, receipts, and machine paths
- critical paths that cannot be explained from the repo alone
- legacy or mixed-surface areas that still work but have weak explanations

## 4. Repo profile

- Repo type: offline Python application with a packaged Tauri desktop app and a
  local web dev shell.
- Main languages and frameworks: Python, JSON Schema, YAML ontology, Node/Vite,
  and Rust/Tauri.
- Runtime model: `mmo` CLI, frozen CLI sidecar, packaged desktop app, local GUI
  RPC subprocess, and artifact-first project or workspace directories.
- Highest-risk systems: render, export, QA, compare, plugin authority and
  marketplace installs, packaged-data resolution, project or session
  persistence, and sidecar packaging.
- Sensitive data classes: stems, session audio, render outputs, compare
  artifacts, receipts, manifests, QA reports, media tags, machine paths, and
  private corpus outputs under `corpus/` or `private/`.
- Main docs and ownership locations: `docs/README.md`,
  `docs/02-architecture.md`, `docs/semantic_contracts.md`,
  `PROJECT_WHEN_COMPLETE.md`, and `docs/unknowns/`.
- Ownership note: no `CODEOWNERS` file is present today.

## 5. Working modes

### Pass 0: Read-only inventory

- Inspection and analysis only.
- No file changes.
- Use this pass to identify ownership, contracts, side effects, risks, legacy
  edges, and missing evidence.

### Pass 1: Docs and comments only

- Comments, manifests, maps, runbooks, ADR-style notes, README updates, and
  other explanatory docs only.
- No logic changes.
- No control-flow changes.
- No import changes.
- No dependency bumps.
- No config changes.
- No schema changes.
- No ontology changes.
- No formatting sweeps outside touched comment or doc lines.

Treat behavior-sensitive comments as code. Do not alter shebangs, encoding
markers, pragma comments, linter directives, type-affecting docblocks, SQL
hints, magic comments, or engine-metadata comments in a docs-only pass.

### Pass 2: Behavior-preserving cleanup

- Allowed only after the touched area has baseline docs or comments.
- Requires tests, fixtures, or equivalent evidence that behavior is unchanged.
- No feature work in the same PR or commit.
- Keep the cleanup narrow enough that a reviewer can explain why it is safe.

### Pass 3: Feature or security work

- Only when the user asked for it.
- Only after the needed map, unknowns, and approval gates are in place.
- Docs, tests, risk notes, and rollback notes stay attached to the change.
- Do not start protected-area edits until required approval is explicit.

## 6. Coverage and slice rules

MMO is a large, mixed, multi-surface repo. Do not claim broad coverage from one
small pass.

- Use a coverage ledger for prompt-pack work and other wide repo passes.
- Work in risk-ranked slices instead of pretending the repo can be explained in
  one sweep.
- The long-term target is full critical-path coverage over time, not instant
  blanket coverage.
- Record exclusions, blind spots, blocked areas, and legacy surfaces that still
  need work.
- Do not claim "fully covered" unless the ledger supports that claim.

Use these existing ledger surfaces:

- `docs/unknowns/critical-paths.md` for critical-path review history
- `docs/unknowns/architecture-pass.md` for architecture inventory unknowns

## 7. Rules for new code

Every non-trivial change must:

- say what changed and why in plain language
- tie tests or fixture evidence to the intended behavior
- add a security and privacy note when relevant
- add an observability note when relevant
- add a rollback or failure-handling note when relevant
- update docs when a subsystem changes
- update a service or module manifest when the repo uses one

Repo-specific rules:

- Keep PRs and commits small and single-purpose when possible.
- Preserve cross-platform install safety on Linux, Windows, and macOS.
- Do not assume repo-root runtime paths. Use `mmo.resources`, packaged data,
  and install-safe entrypoints.
- Prefer one shared resolver or contract implementation per concept. Do not add
  parallel CLI-only, desktop-only, or render-only logic unless the split is
  intentional and documented.
- Stable IDs only. Never rename or repurpose published ontology IDs, schema
  enums, or `ISSUE.*` IDs silently. Add new IDs instead.
- Register new `ISSUE.*` IDs in `ontology/issues.yaml` before they appear in
  code, tests, docs, or UI fixtures.
- Keep backend status meanings owned by `src/mmo/core/statuses.py`, schema enums
  in `schemas/statuses.schema.json`, and display mappings in shared backend or
  desktop layers.
- Do not infer success from artifact existence. Emit explicit status, warning,
  and failure reasons where validity matters.

Environment preflight is mandatory:

- confirm active branch and working directory
- confirm interpreter or virtualenv
- confirm whether the shell uses `python`, `python3`, or only repo runners
- confirm whether `pytest` and required extras are installed
- confirm the exact verification command and whether repo runners are needed to
  set `PYTHONPATH=src` and repo-local temp roots

Verification anchors:

- `python tools/validate_contracts.py`
- `python tools/validate_policies.py`
- `python tools/run_policy_fixtures.py`
- `tools/run_pytest.sh -q`
- `tools/run_pytest.ps1 -q`
- `tools/run_pytest.cmd -q`

The repo pytest runners are the safe default because they set `PYTHONPATH=src`
and keep temp artifacts repo-local.

A test command that did not run in the correct environment does not count as
validation.

## 8. Unknowns and evidence

Do not guess.

If you cannot confidently explain a file, module, side effect, or contract:

- stop before changing behavior
- record the unknown in `docs/unknowns/`
- include the blocked decision, not only the confusion

Use a concise table or bullet structure with:

- area or file
- concern
- why it matters
- evidence found so far
- likely owner if known
- next best check
- risk level

Do not create shadow explanations in comments to cover uncertainty. If the
behavior already exists, improve visibility, tests, receipts, or docs instead
of duplicating enforcement.

## 9. Sensitive areas that need explicit human approval

Require approval before any change touching:

- auth, access control, secrets, crypto, or any new credential flow
- authority profiles, safety gates, approval semantics, or auto-apply behavior
- plugin manifests, loaders, execution boundaries, or marketplace install flows
- render, downmix, export, QA, compare, or fallback stages that can alter audio
  outputs or acceptance decisions
- FFmpeg or ffprobe discovery, invocation, metadata handling, or export policy
- delete, cleanup, retention, sync, bundle, mirror, unlink, or packaged-data
  resolution behavior
- schema or ontology removals, ID repurposing, migration semantics, or status
  meaning changes
- lockfiles, watch-folder state, queueing, concurrency, threading, or anything
  that can corrupt project state or outputs
- Tauri sidecar packaging, bundled binary discovery, packaged desktop smoke
  behavior, GUI RPC flows, local servers, or external callbacks with side
  effects
- compliance-sensitive data handling, including any future health, finance,
  education, child, legal, location, biometric, or other regulated data

If you find an active leak, unsafe gap, or policy hole inside a protected area,
document it first and stop for approval before editing.

## 10. Data that must never appear in repo text

Never commit, paste, or echo:

- passwords
- access tokens
- API keys and secrets
- cookies or session identifiers
- encryption keys, signing keys, or key material
- decrypted payloads
- connection strings
- signed URLs
- private callback URLs
- full request or response bodies with sensitive data
- raw personal data beyond the minimum safe example
- real user, customer, artist, or collaborator data copied from production
- embedded media tags copied from private stems unless scrubbed
- absolute personal filesystem paths from developer or user machines
- workspace receipts, manifests, reports, QA artifacts, or event logs copied
  from real private sessions unless redacted and explicitly safe to publish
- private corpus outputs under `corpus/` or `private/`
- plugin assets, binaries, or samples that are not licensed for redistribution

MMO is not a health or finance product, but it does handle high-value creative
data. Treat stems, render artifacts, receipts, media tags, and local machine
paths as sensitive by default.

## 11. Comment, doc, commit, and PR writing rules

Shared writing rules for comments, docs, commit messages, ADR-style notes,
runbooks, unknowns files, and PR close-out text:

- Use short sentences.
- Use plain words.
- Name the subject, risk, and safeguard directly.
- Use active voice when it reads cleaner.
- Use ASCII punctuation and straight quotes only.
- Comments explain why, not what.

Do not use comments or prose to hide uncertainty, undocumented policy, or
folklore.

Avoid or reject:

- stiff corporate tone
- legal boilerplate tone
- stock transition adverbs used as filler
- stock wrap-up lines
- mirror-contrast slogans built around a negated first clause
- padded triplet cadence when two or four items fit better
- vague openings that hide the subject
- apology filler
- hype

Avoid vague openings such as:

- "This ensures"
- "This allows"
- "This enables"

Avoid filler such as:

- `robust`
- `seamless`
- `utilize`
- `leverage`
- `facilitate`
- `comprehensive`
- `streamline`
- `cutting-edge`
- `scalable solution`
- `in order to`
- `it's important to note`
- `it should be noted`
- `essentially`
- `basically`
- `actually`
- `simply`
- `just`

## 12. Documentation minimums

When a subsystem changes, update at least one practical source of truth:

- service or module manifest
- architecture note
- runbook update
- ADR-style note
- README section
- contract or schema note
- ops note for deploy, rollback, or support when relevant

Preferred MMO doc targets:

- `docs/README.md` for doc-map changes
- numbered docs such as `docs/02-architecture.md`
- `docs/manual/` for user-visible workflow or UI changes
- `docs/semantic_contracts.md` for ownership and mirroring clarifications
- schema or ontology notes alongside `schemas/` and `ontology/`
- `PROJECT_WHEN_COMPLETE.md`, `CHANGELOG.md`, and `GEMINI.md` when progress,
  release notes, or operator guidance must stay aligned with repo reality
- `docs/ontology_migrations/` when ontology removals or migrations are involved

Keep this useful. Do not build a doc graveyard.

## 13. PR close-out format

End every PR with a short note that covers:

- what changed in plain English
- unknowns found
- security or privacy impact
- observability impact
- docs touched
- approval gates crossed or still pending
- follow-up work, if any

MMO PRs should also include:

- a one-line imperative title
- 3-6 bullets describing what changed and why
- a short list of files touched
- the exact validation commands run
- blockers if full validation did not execute in the correct environment

## 14. Repo-specific appendix

Critical systems:

- `src/mmo/core/` for artifact contracts, planning, QA, compare, project
  persistence, and statuses
- `src/mmo/dsp/` for decode, transcode, export, channel layout, and audio
  processing boundaries
- `src/mmo/plugins/`, `plugins/`, and `src/mmo/data/plugins/` for bounded
  extension behavior
- `src/mmo/cli.py` and `src/mmo/cli_commands/` for install-safe CLI surfaces
- `gui/desktop-tauri/` and `gui/desktop-tauri/src-tauri/` for desktop workflow,
  sidecar packaging, and platform bundles

Sensitive data classes:

- private stems and session audio
- render outputs and compare artifacts
- workspace receipts, manifests, QA reports, and event logs
- media tags and embedded metadata
- local filesystem paths and machine-specific environment details
- private corpus scans and suggestion outputs under `corpus/` or `private/`

Highest-risk directories, packages, or runtime units:

- `src/mmo/core/`
- `src/mmo/dsp/`
- `src/mmo/plugins/`
- `schemas/`
- `ontology/`
- `tools/`
- `gui/desktop-tauri/`
- `examples/plugin_authoring/`
- `src/mmo/data/plugins/`

Preferred locations:

- Unknowns: `docs/unknowns/`
- Architecture docs: `docs/README.md`, `docs/02-architecture.md`,
  `docs/architecture/system-map.md`, and `docs/semantic_contracts.md`
- Runbooks and operator docs: `docs/manual/` and the docs index
- ADR-style notes: this repo does not have a dedicated ADR directory today, so
  keep ADR-style notes under `docs/` and link them from `docs/README.md`

Steering files kept in sync in this repo:

- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
