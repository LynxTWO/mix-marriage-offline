<!-- markdownlint-disable-file MD013 -->

# Remediation Backlog

This backlog is a synthesis pass built from current anti-dark-code evidence in
the repo. It does not claim full repo coverage beyond what
`docs/architecture/coverage-ledger.md` already supports.

Risk and likely impact use `High`, `Medium`, and `Low`.
Confidence uses `verified`, `inferred`, and `unknown`.
Approval values use `yes` and `no`.
Status values use `open`, `blocked`, `deferred`, and `ready`.

Recently completed on this branch:

- GUI stderr forwarding in `gui/lib/mmo_cli_runner.mjs` and
  `gui/lib/rpc_process_client.mjs` now uses allowlisted summaries backed by
  `cd gui && npm test`. Keep `docs/review/approval-packets.md` as the approval
  trail for that protected-area edit.
- Safe-render live progress in `src/mmo/cli_commands/_renderers.py` now keeps
  `where` on target IDs, stable labels, and workspace-relative refs instead of
  absolute paths. Keep `docs/review/approval-packets.md` as the approval trail
  for that protected-area edit.
- `project show --format json-shared`, `project save --format json-shared`,
  and `project load --format json-shared` now provide additive shared-log-safe
  JSON profiles, and the shell-facing CLI default for `project save` and
  `project load` now uses the shared-safe contract while RPC keeps the local
  `json` contract.
- `project show` now also defaults to the shared-safe shell profile while GUI
  and RPC stay on explicit local `json`.
- `scan_session` and `mmo scan` now support `--format json-shared`, and
  shell-facing scan stdout now defaults to the shared-safe contract while
  `--out` and explicit `--format json` keep the full local report.
- `tools/smoke_packaged_desktop.py` and `.github/workflows/release.yml` now
  keep packaged smoke and Windows release console output on artifact labels,
  installer kind, signature status, and bounded status summaries while leaving
  full install-state and installer-log detail on disk only.
- Bundled plugin implementations and packaged plugin data now have a dedicated
  read-only review in `docs/review/bundled-plugin-review.md`. The coverage
  ledger moved that slice from `deferred` to `mapped`.
- `src/mmo/core/plugin_loader.py` and `src/mmo/core/plugin_market.py` now have
  targeted trust-boundary comments backed by
  `docs/review/bundled-plugin-trust-boundary-audit.md`.
- `src/mmo/plugins/renderers/mixdown_renderer.py`,
  `src/mmo/plugins/renderers/placement_mixdown_renderer.py`, and
  `src/mmo/plugins/renderers/safe_renderer.py` now have targeted invariant
  comments backed by `docs/review/bundled-renderer-comment-audit.md`.
- `src/mmo/plugins/detectors/lfe_corrective_detector.py` and
  `src/mmo/plugins/resolvers/lfe_corrective_resolver.py` now have targeted
  approval-boundary comments backed by
  `docs/review/bundled-corrective-plugin-audit.md`.
- `src/mmo/dsp/plugins/registry.py`, `src/mmo/plugins/subjective/__init__.py`,
  and `src/mmo/plugins/subjective/binaural_preview_v0.py` now have targeted
  subjective-bypass notes backed by
  `docs/review/bundled-subjective-bypass-audit.md`.

## Safe to fix now

No open item currently fits this bucket. The bundled-plugin review completed on
this branch, and the next useful plugin follow-up now touches protected
authority or render paths.

## Approval-gated

No open item currently fits this bucket. The current protected log-boundary
items landed on this branch, and the remaining work now sits in evidence gaps
or future explicit-local contract decisions.

## Needs more evidence

| Title | Area or slice | Risk level | Likely impact | Why it matters | Evidence found | Confidence | Approval needed | Recommended next prompt or pass type | Smallest safe next step | Verification plan | Owner if known | Current status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Decide how checkout examples and offline market assets fit the bundled-plugin authority story | Bundled plugin surfaces in `plugins/`, `src/mmo/data/plugins/`, `src/mmo/data/plugin_market/assets/plugins/`, and `src/mmo/plugins/` | High | High | The bundled-plugin comment batches now cover the shipped code-path trust boundaries, but the repo still does not prove the intended long-term contract for checkout-only examples or market-asset parity. That blocks stronger closure or a broader plugin cleanup pass. | `docs/review/bundled-plugin-review.md`; `docs/review/bundled-subjective-bypass-audit.md`; `docs/unknowns/bundled-plugin-review.md`; `docs/architecture/coverage-ledger.md`; `docs/architecture/repo-slices.md` | verified | no | plugin-authority evidence pass | Resolve one boundary at a time: checkout examples or market-asset parity. Do not fold those questions back into another protected code-comment batch. | Review plugin docs, plugin-market tests, and any release or packaging notes that define intended parity; if a later doc or code change lands, rerun the plugin-loader and plugin-market checks from the older bundled-plugin approval packets. | not declared in repo | open |
| Confirm machine-readable output and trace escape channels | Machine-readable product output in `_project.py`, `src/mmo/tools/scan_session.py`, and `tools/agent/*` | High | High | The repo has verified path-bearing JSON and trace artifacts. Shell-facing project and scan commands now default to shared-safe output, but the repo still needs proof about how out-of-repo support or CI practice handles explicit local `json`, file-backed scan receipts, and local trace artifacts. That still blocks safe prioritization between further redaction, documentation, and operator guidance. | `docs/review/scenario-stress-test.md` section 5; `docs/unknowns/adversarial-pass.md` row for `_project.py`, `scan_session.py`, and `tools/agent/*`; `docs/unknowns/scenario-stress-test.md`; `docs/unknowns/logging-audit.md`; `docs/review/evidence-gap-check.md`; `.github/ISSUE_TEMPLATE/bug_report.yml`; GUI RPC inspection; workflow inspection of `.github/workflows/ci.yml` and `.github/workflows/release.yml`; shared-safe project and scan output passes on this branch | inferred | no | explicit-local output contract review or machine-readable output follow-up | Separate the next pass into two parts: decide whether explicit local project and scan JSON should narrow further, and keep `tools/agent/*` on the deferred artifact-contract track unless a shared workflow is proven. | Review any remaining maintainer or support guidance outside the repo; if a later code fix follows, reuse the verification plans from the project or scan output batches and `tests/test_agent_harness.py` for the deferred agent-contract track. | CLI, tooling, or support maintainers | open |
| Check for hidden automation behind the documented support scripts | Quiet support and control-plane scripts `tools/safe_cleanup.py`, `tools/sync_packaged_data_mirror.py`, and `tools/sync_claude_agents.py` | High | Medium | The repo now proves all three scripts are documented human-run paths. The remaining risk is not who they are for. It is whether any hidden bootstrap, wrapper, or release-prep routine runs them automatically outside the written docs. | `docs/review/evidence-gap-check.md` section 1; `docs/PROJECT_INSTRUCTIONS.md`; `docs/00-quickstart.md`; `docs/21-loudness-profiles.md`; `CLAUDE.md`; `docs/contributing/ai-workflow.md`; `tools/validate_packaged_data_mirror.py`; `docs/architecture/coverage-ledger.md` row `Support tooling, smoke harnesses, and release control plane` | verified | no | support-tool audience audit | Inspect script history and any setup or bootstrap notes before reopening this slice. Treat the current repo-local audience story as human-run unless stronger automation proof appears. | Check `git log --` history for the three scripts and any setup docs; if a follow-up note lands, run `npx --yes markdownlint-cli` on the touched docs. | tooling or release maintainers | open |
| Confirm public publish and Windows release boundaries | Pages publish path in `.github/workflows/pages.yml` and `site/`, plus Windows release and installer behavior in `.github/workflows/release.yml` and packaged smoke outputs | High | Medium | Public docs deploy and Windows release behavior both sit partly outside repo-owned runtime code. The repo confirms these boundaries exist, but it does not yet prove which parts are hand-maintained, generated, runner-dependent, or installer-dependent. | `docs/review/adversarial-pass.md` Pages and release-control-plane findings; `docs/review/scenario-stress-test.md` sections 3 and 4; `docs/unknowns/adversarial-pass.md`; `docs/unknowns/scenario-stress-test.md`; `docs/unknowns/maintenance-harness.md` | unknown | no | publish-and-release boundary audit | Separate the public publish boundary from the Windows release boundary in a follow-up evidence pass. Record what is repo-owned, what is GitHub or runner-owned, and what still depends on installer or signing runtime behavior. | Inspect repo docs, workflow jobs, and any available release dry-run notes; if a later release-path change follows, use the smoke and workflow verification plan already listed in the approval-gated backlog item. | docs or release maintainers | open |
| Evaluate `tools/agent/*` artifact-contract hardening | Agent trace and contract-stamp artifacts in `tools/agent/run.py`, `tools/agent/trace.py`, and `tools/agent/contract_stamp.py` | High | Medium | The path-bearing local artifacts are verified, but the current trace and stamp shape is also persisted, documented, validated, and kept local by default. That makes the open question a contract-boundary problem, not a small hardening fix. | `docs/security/logging-audit.md` finding for `tools/agent/*`; `docs/unknowns/logging-audit.md`; `docs/review/safe-fix-plan.md`; `docs/architecture/coverage-ledger.md` row `Machine-readable product output and local trace escape`; `docs/agent_repl_harness.md`; `.gitignore`; workflow inspection showing no repo-owned upload path | verified | no | artifact-contract audit or machine-readable output review | Determine whether any human support or review channel needs a sanitized trace or stamp contract before changing the persisted artifact shape. | Review support and artifact-sharing practice outside the repo; if a later contract change is approved, run `tools/run_pytest.sh -q tests/test_agent_harness.py` and inspect fresh local trace and stamp samples. | agent harness | deferred |
| Confirm audience for the remaining unowned helper entrypoints | Helper entrypoints `tools/run_renderers.py` and `tools/benchmark_render_precision.py` | Medium | Medium | The repo now proves `capture_tauri_screenshots.py` is both a CI evidence path and a maintainer baseline-refresh tool. The remaining uncertainty is the renderer helper and the precision benchmark, which still bypass the main CLI and desktop entrypoints without a documented owner or review role. | `docs/review/evidence-gap-check.md` section 2; `.github/workflows/ci.yml`; `docs/manual/assets/screenshots/README.md`; `docs/architecture/coverage-ledger.md` support-tool row; `docs/review/adversarial-pass.md` | verified | no | helper-entrypoint audience audit | Keep the screenshot helper on the trusted-evidence side, then document whether `run_renderers.py` and `benchmark_render_precision.py` are maintainer-only helpers, benchmark tools, or something the repo expects reviewers to trust. | Confirm whether any workflow, README, or benchmark note names those two helpers directly; if a follow-up note lands, run `npx --yes markdownlint-cli` on the touched docs. | GUI or tooling maintainers | open |
| Confirm PR template enforcement outside the repo | GitHub PR workflow and branch-protection behavior around `.github/pull_request_template.md` | Medium | Low | The maintenance harness can enforce asset presence and wording, but it cannot prove that GitHub or branch protection forces contributors to fill the template before merge. | `docs/review/maintenance-harness.md` remaining limits; `docs/unknowns/maintenance-harness.md` PR-template row | unknown | no | branch-protection and review-policy check | Confirm whether any out-of-repo branch-protection, review policy, or maintainer habit treats template completion as required. If not, keep this as reviewer guidance rather than pretending it is enforced. | Review GitHub branch-protection and maintainer policy outside the repo; if repo docs change later, run `npx --yes markdownlint-cli docs/review/maintenance-harness.md docs/unknowns/maintenance-harness.md`. | not declared in repo | open |

## Coverage limits

The current repo evidence still leaves these holes outside repo-local proof:

- support scripts that mutate repo or packaged state without a fully documented
  maintainer or CI audience
- release tooling, Windows signing, packaged smoke, and installer behavior that
  depend on GitHub runners, Windows tooling, or installer state outside the repo
- GitHub Pages deploy behavior and any generation boundary behind `site/`
- machine-readable CLI JSON, NDJSON traces, and other local artifacts that
  become telemetry once wrappers, CI, or support workflows capture them
- steering mirrors under `.claude/agents/` that can look authoritative enough
  to distort review focus if the canonical source is not restated

No reviewed anti-dark-code evidence in this repo showed a sibling repo,
submodule-owned runtime, remote config service, feature-flag dashboard,
checked-in notebook workflow, admin tool, or migration path that currently
changes shipped behavior. This backlog therefore does not add remediation items
for those categories.
