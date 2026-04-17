# Scenario Stress-Test

<!-- markdownlint-disable-file MD013 -->

Scores in this pass reflect the repo story at the start of the review, before
the follow-up doc changes proposed here.

Scale:

- `0` = current docs would miss or mis-handle the scenario
- `1` = current docs partly catch it, but the boundary is still ambiguous
- `2` = current docs catch it cleanly

## 1. Quiet support script mutates repo or packaged state

- Scenario name: Quiet support script mutates repo or packaged state
- Why plausible here: `tools/safe_cleanup.py`, `tools/sync_packaged_data_mirror.py`, and `tools/sync_claude_agents.py` already delete or rewrite repo-owned paths.
- Current doc, rule, or summary that would fail: `docs/architecture/system-map.md` and `docs/architecture/repo-slices.md` still center the main CLI, local dev shell, and packaged desktop runtime. They do not give these support scripts the same first-class control-plane treatment.
- Blind spot exposed: support tooling can change repo state, packaged data, or workspace steering without ever passing through the main runtime map.
- Doc or rule change that would close the gap: keep a dedicated support-tool and release-control-plane row in the coverage ledger and stop treating these scripts as generic tooling glue.
- Affects: coverage claims, approval gates
- Overall score: `1`

## 2. Helper entrypoint bypasses the main CLI or desktop flow but still changes trusted evidence

- Scenario name: Helper entrypoint changes trusted review evidence
- Why plausible here: `tools/run_renderers.py`, `tools/benchmark_render_precision.py`, and `tools/capture_tauri_screenshots.py` call backend modules directly or refresh screenshot baselines outside the main user entrypoints.
- Current doc, rule, or summary that would fail: recent summary subjects like `GUI: comment browser helper evidence paths` and `Desktop: comment native shell and smoke paths` can read broader than the helper-entrypoint evidence they cover.
- Blind spot exposed: a helper script can create or refresh trusted artifacts even when the main CLI and desktop maps look well explained.
- Doc or rule change that would close the gap: name these helper entrypoints as review-evidence control planes, not only as examples or tooling.
- Affects: coverage claims, evidence discipline
- Overall score: `1`

## 3. Release signing, installer smoke, or Windows verification changes shipped behavior outside the main runtime map

- Scenario name: Release control plane outruns the runtime story
- Why plausible here: `.github/workflows/release.yml` and `tools/smoke_packaged_desktop.py` already own signing, installer smoke, Windows verification, and artifact publishing.
- Current doc, rule, or summary that would fail: the system map correctly mentions release outputs, but recent summaries such as `Desktop: comment native shell and smoke paths` can still sound broader than the out-of-repo Windows signer and installer behavior the repo cannot prove from static review.
- Blind spot exposed: shipped behavior depends on GitHub runners, Windows cert-store behavior, `signtool`, and installer output that sit outside the local app runtime.
- Doc or rule change that would close the gap: keep release signing and packaged smoke listed as protected control-plane paths, and call out the out-of-repo boundary every time coverage is summarized.
- Affects: approval gates, coverage claims, protected-area handling
- Overall score: `1`

## 4. Public docs publish path changes operator-facing behavior outside the app runtime story

- Scenario name: Public docs deploy becomes shipped behavior
- Why plausible here: `.github/workflows/pages.yml` has a real deploy job and `site/` is the published payload.
- Current doc, rule, or summary that would fail: the ledger previously grouped `site/` with examples and benchmarks, and the system map treated Pages as an operational note instead of a publish boundary.
- Blind spot exposed: operator-facing docs can change in a public control plane even when no runtime code path changed.
- Doc or rule change that would close the gap: separate `site/` and `pages.yml` into a public-publish control-plane note instead of leaving them inside a generic examples bucket.
- Affects: coverage claims, control-plane handling
- Overall score: `0`

## 5. Local machine-readable product output becomes shared telemetry once wrappers or CI capture it

- Scenario name: Product output escapes into telemetry
- Why plausible here: `_project.py`, `scan_session.py`, and `tools/agent/*` already emit path-bearing JSON or NDJSON. The logging audit shows those outputs can leak once wrappers or CI capture them.
- Current doc, rule, or summary that would fail: the logging audit catches the risk, but the broader map and ledger did not previously represent machine-readable output as its own trust boundary.
- Blind spot exposed: the repo can say "local only" while still letting local product output become shared telemetry in CI, support, or issue threads.
- Doc or rule change that would close the gap: add a ledger note that machine-readable output and local trace artifacts are separate from ordinary logs and need their own boundary language.
- Affects: coverage claims, approval gates, protected-area handling
- Overall score: `1`

## 6. Shared plugin contract coverage hides a second path through bundled plugin implementations and packaged plugin data

- Scenario name: Shared plugin contracts are clean, bundled plugin behavior is not
- Why plausible here: recent summaries such as `Plugins: comment contracts and authoring paths` and `Plugins: comment loading and market paths` cover shared contracts and loading rules, while `plugins/` and `src/mmo/data/plugins/` still hold bundled implementation behavior.
- Current doc, rule, or summary that would fail: a broad plugin summary can sound like the whole plugin surface is closed when the bundled implementations have not had the same targeted review.
- Blind spot exposed: contract coverage and implementation coverage are not the same thing for plugin behavior.
- Doc or rule change that would close the gap: keep the split between shared plugin contracts and bundled plugin implementations explicit in the ledger and slice plan.
- Affects: coverage claims
- Overall score: `1`

## 7. Steering-file drift or mirrored-path churn weakens approval gates or lets a later pass touch excluded code

- Scenario name: Steering-file drift through mirrored paths
- Why plausible here: `CLAUDE.md` and `GEMINI.md` defer to `AGENTS.md`, but `tools/sync_claude_agents.py` also rewrites a workspace mirror under `.claude/agents/`. The ledger separately excludes generated and vendored desktop paths.
- Current doc, rule, or summary that would fail: the steering files say which source is authoritative, but they do not make mirrored workspace copies part of the same coverage story.
- Blind spot exposed: a reviewer can treat a mirrored or generated path as if it were a primary steering or runtime surface unless the docs keep saying which copy is authoritative.
- Doc or rule change that would close the gap: keep mirrored workspace copies and generated or vendored paths named as non-authoritative in review docs and ledger entries.
- Affects: approval gates, coverage claims
- Overall score: `1`
