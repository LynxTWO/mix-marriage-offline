# AGENTS.md — MMO Anti-Dark-Code Guide

<!-- markdownlint-disable-file MD013 -->

## 1. Purpose and scope

`AGENTS.md` is the primary steering file for AI-assisted work in this repo.
`CLAUDE.md` is a compatibility companion and must follow this file.
The goal is to keep Mix Marriage Offline explainable, reviewable, and safe to
change. Every automated contributor should leave behind code and docs that a
careful human can read, test, and reason about without hidden behavior.
This repo is an existing multi-surface system. Keep guidance tied to the real
MMO surfaces: `src/mmo/`, `schemas/`, `ontology/`, `src/mmo/data/`,
`plugins/`, `src/mmo/data/plugins/`, `examples/plugin_authoring/`,
`gui/desktop-tauri/`, `gui/`, and `gui/desktop-tauri/src-tauri/`.

## 2. What dark code means in this repo

Dark code is production behavior whose purpose, boundaries, failure modes, data
handling, or ownership cannot be explained from the repo alone.
In MMO, dark code includes:

- hidden audio mutation, render behavior changes, or fallback behavior that is
  not obvious from code, schemas, receipts, fixtures, and docs
- hidden filesystem side effects such as silent deletes, bundle rewrites,
  packaged-data rewires, or workspace writes
- plugin authority, gate behavior, or approval semantics that are not obvious
  from manifests, receipts, or docs
- schema, ontology, status, or artifact meanings redefined in random call sites
- missing ownership, failure-mode notes, rollback notes, or sensitivity notes
  for local session data, corpus data, media tags, and machine paths

## 3. Working modes for existing code

### Pass 0: Read-only inventory

- Inspection and analysis only.
- No file changes.
- Use this pass to identify ownership, contracts, side effects, risks, and
  missing evidence.

### Pass 1: Comment and docs only

- Allowed: comments, manifests, ADRs, runbooks, architecture notes, README
  sections, and other explanatory docs.
- Not allowed: logic changes, control-flow changes, import changes, dependency
  bumps, config changes, schema changes, ontology changes, or formatting sweeps
  outside touched comment lines.
- Treat behavior-sensitive comments as code. Do not alter shebangs, encoding
  markers, pragma comments, linter directives, type-affecting docblocks, SQL
  hints, or framework magic comments in a docs-only pass.

### Pass 2: Behavior-preserving cleanup

- Only after the area has baseline docs or comments.
- Requires tests, fixtures, or equivalent evidence that behavior is unchanged.
- No feature work in the same PR.
- Keep the cleanup narrow enough that a reviewer can explain why it is safe.

## 4. Rules for new code

Every non-trivial change must:

- state what changed and why
- link tests or fixture evidence to the intended behavior
- add security/privacy, observability, and rollback/failure notes when relevant
- update docs, manifests, or contract notes when a subsystem changes

Repo-specific rules:

- Keep PRs small and single-purpose.
- Preserve cross-platform install safety on Linux, Windows, and macOS.
- Do not assume repo-root paths for packaged or runtime data. Use
  `mmo.resources`, packaged data, and install-safe entrypoints.
- Prefer one shared resolver or contract implementation per concept. Do not add
  parallel CLI-only, desktop-only, or render-only logic unless the split is
  intentional and documented.
- Stable IDs only. Never rename or repurpose published ontology IDs, schema
  enums, or `ISSUE.*` IDs silently. Add new IDs instead.
- Register new `ISSUE.*` IDs in `ontology/issues.yaml` before they appear in
  code, tests, docs, or UI fixtures.
- Keep backend status meanings owned by `src/mmo/core/statuses.py`, schema
  enums in `schemas/statuses.schema.json`, and display mappings in shared
  backend or desktop layers.
- Do not infer success from artifact existence. Emit explicit status, warning,
  and failure reasons where validity matters.

Environment preflight is mandatory:

- confirm active branch, working directory, active interpreter or virtualenv, and whether this shell uses `python`, `python3`, or only repo runners
- confirm whether `pytest` and required extras are installed in that environment
- confirm the exact verification command and whether repo runners are needed to set `PYTHONPATH=src` and repo-local temp roots

Verification anchors:

- `python tools/validate_contracts.py`, `python tools/validate_policies.py`, and `python tools/run_policy_fixtures.py`
- `tools/run_pytest.sh -q`, `tools/run_pytest.ps1 -q`, and `tools/run_pytest.cmd -q`
- the repo pytest runners are the safe default because they set `PYTHONPATH=src` and keep temp artifacts repo-local

A test command that does not run in the correct environment does not count as
validation.

## 5. Unknowns and evidence

Do not guess.

If you cannot confidently explain a file, module, side effect, or contract:

- stop before changing behavior
- record the unknown in `docs/unknowns/`
- include the file or module name, what is unclear, what evidence you found,
  what you checked, and what decision is blocked

Do not create shadow explanations in comments to cover uncertainty. If the
requested behavior already exists, improve visibility, tests, receipts, or docs
instead of duplicating enforcement.

## 6. Sensitive areas that require explicit human approval

Require approval before changing anything that touches:

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
  behavior, GUI RPC flows, local servers, external callbacks, or any new side
  effect that acts outside the current process
- compliance-sensitive data handling, including any future health, finance,
education, child, legal, location, or biometric data

## 7. What must never appear in logs, comments, tests, docs, or examples

Never commit or paste:

- passwords, access tokens, API keys, secrets, cookies, session identifiers,
  encryption keys, signing keys, decrypted payloads, connection strings, signed
  URLs, or private callback URLs
- full request or response bodies containing sensitive local data, or raw
  personal data beyond the minimum needed for a safe example
- real customer, artist, or collaborator audio or session data copied from
  production or personal machines
- embedded media tags or metadata copied from real private stems unless scrubbed
- absolute personal filesystem paths from developer or user machines
- workspace receipts, reports, manifests, or event logs copied from real
  private sessions unless redacted and explicitly safe to publish
- private corpus outputs under `corpus/` or `private/`
- plugin assets, binaries, or samples that are not licensed for redistribution

MMO is not a health or finance product, but it does handle high-value creative
data. Treat stems, render artifacts, workspace receipts, media tags, and local
machine paths as sensitive by default.

## 8. Comment standard

Comments explain why, not what.

When non-obvious code needs a comment, cover the parts that matter:

- purpose and rationale
- invariants and edge cases
- failure modes
- security and privacy assumptions
- authority, determinism, and concurrency assumptions
- performance tradeoffs
- idempotency or ordering constraints when relevant

Do not add comments that only narrate obvious syntax. Do not use comments to
hide uncertainty, undocumented policy, or folklore.

## 9. Writing voice for comments and docs

Use short sentences, plain words, active voice when clearer, and direct naming
of risks, guardrails, and failure states.

Avoid vague openings such as:

- "This ensures"
- "This allows"
- "This enables"

Avoid filler such as:

- `robust`, `seamless`, `utilize`, `leverage`, `facilitate`, `comprehensive`,
  `streamline`, `cutting-edge`, `scalable solution`, `in order to`,
  `it's important to note`, `it should be noted`, `essentially`, `basically`,
  `actually`, `simply`, and `just`

## 10. Documentation minimums

When a subsystem changes, update at least one practical source of truth:

- service or module manifest
- architecture note
- runbook update
- ADR update
- README section
- contract or schema note

Preferred MMO documentation targets:

- `docs/README.md` for doc map changes
- numbered docs such as `docs/02-architecture.md`
- `docs/manual/` for user-visible workflow or UI changes
- `docs/semantic_contracts.md` for ownership or mirroring clarifications
- schema or ontology notes alongside `schemas/` and `ontology/`
- `PROJECT_WHEN_COMPLETE.md`, `CHANGELOG.md`, and `GEMINI.md` when progress,
  release notes, or operator guidance must stay aligned with repo reality

Keep this practical. Do not create policy graveyards or duplicate the same rule
across multiple files without a reason.

## 11. PR close-out format

End every PR with a short note that covers:

- what changed in plain English
- unknowns found
- security or privacy impact
- observability impact
- docs touched
- follow-up work, if any

MMO PRs should also include a one-line imperative title, 3-6 bullets
describing what changed and why, a short list of files touched, and the exact
validation commands actually run plus blockers if full validation did not
execute in the correct environment.

## 12. Repo-specific appendix

Critical systems: `src/mmo/core/` for artifact contracts, planning, QA, and
statuses; `src/mmo/dsp/` for decode, transcode, export, channel layout, and
audio-processing boundaries; `src/mmo/plugins/`, `plugins/`, and
`src/mmo/data/plugins/` for bounded extension behavior; `src/mmo/cli.py` and
`src/mmo/cli_commands/` for install-safe CLI surfaces; `gui/desktop-tauri/`
and `gui/desktop-tauri/src-tauri/` for desktop workflow, sidecar packaging, and
platform bundles.

Sensitive data classes: private stems and session audio; render outputs and
compare artifacts; workspace receipts, manifests, QA reports, and event logs;
media tags and embedded metadata; local filesystem paths and machine-specific
environment details; private corpus scans and suggestion outputs under
`corpus/` or `private/`.

Highest-risk directories and files: `src/mmo/core/`, `src/mmo/dsp/`,
`src/mmo/plugins/`, `schemas/`, `ontology/`, `tools/`, `gui/desktop-tauri/`,
`examples/plugin_authoring/`, and `src/mmo/data/plugins/`.

Preferred places for unknowns and architecture docs: `docs/unknowns/`,
`docs/README.md`, `docs/02-architecture.md`, `docs/semantic_contracts.md`,
`docs/manual/`, and `docs/ontology_migrations/` when ontology removals or
migrations are involved.
