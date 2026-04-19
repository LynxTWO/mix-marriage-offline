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
| Keep documented support scripts on the maintainer-tool side unless new automation appears | Quiet support and control-plane scripts `tools/safe_cleanup.py`, `tools/sync_packaged_data_mirror.py`, and `tools/sync_claude_agents.py` | High | Medium | Repo-local docs and git history now support the current story: all three scripts are human-run maintainer or contributor tools, and the only automation shadow is indirect `PKG.MIRROR` enforcement rather than hidden execution of the sync itself. The remaining gap sits outside the repo in unwritten bootstrap or maintainer practice. | `docs/review/evidence-gap-check.md` section 1; `docs/PROJECT_INSTRUCTIONS.md`; `docs/00-quickstart.md`; `docs/21-loudness-profiles.md`; `CLAUDE.md`; `docs/contributing/ai-workflow.md`; `tools/validate_packaged_data_mirror.py`; git history for the three scripts and nearby docs or validator paths; `docs/architecture/coverage-ledger.md` row `Support tooling, smoke harnesses, and release control plane` | verified | no | out-of-repo maintainer workflow check | Do not reopen this slice for repo-local cleanup unless a future bootstrap note, setup helper, or workflow starts calling one of these scripts directly. | Watch future workflow and setup-doc changes. If repo-owned automation appears later, rerun the support-tool evidence pass and `npx --yes markdownlint-cli` on the touched docs. | tooling or release maintainers | deferred |
| Confirm Windows release and installer boundary | Windows release path in `.github/workflows/release.yml` and `tools/smoke_packaged_desktop.py` | High | Medium | The repo now proves the release workflow order, artifact selection, optional signing path, real install smoke orchestration, install-state capture, and cleanup policy. It still does not prove runner, signer, installer, or hosted release behavior end to end. | `docs/review/evidence-gap-check.md` section 4; `docs/unknowns/evidence-gap-pass.md`; `docs/review/adversarial-pass.md`; `docs/review/scenario-stress-test.md`; `docs/security/logging-audit.md`; `tests/test_packaged_desktop_smoke.py`; git history for `release.yml` and `tools/smoke_packaged_desktop.py` | verified | no | Windows release boundary audit or sanitized dry-run capture | Keep separating repo-owned workflow facts from GitHub runner, signer, installer, and hosted-release behavior. Capture a sanitized Windows release dry run when that environment is available. | Inspect any future hosted-run receipts against the current workflow and smoke tests; if a later code or workflow change lands, rerun the packaged smoke tests and `python3 tools/validate_contracts.py`. | desktop packaging or release tooling | open |
| Keep GitHub Pages on the committed-static side unless the repo adds generation | Public docs publish path in `.github/workflows/pages.yml` and `site/` | Medium | Medium | The repo now proves a committed static site payload and a direct upload deploy path. The remaining gap is GitHub Pages hosting behavior, not missing repo-local generation proof. | `docs/review/evidence-gap-check.md` section 3; `docs/unknowns/evidence-gap-pass.md`; `docs/review/scenario-stress-test.md`; `site/index.html`; `site/styles.css`; git history for `site/` and `pages.yml` | verified | no | docs-publish boundary refresh | Treat `site/` as a committed static payload unless a future workflow or build step starts generating it. Reopen the boundary only if the deploy path changes. | If the site workflow or content pipeline changes later, rerun workflow inspection and `npx --yes markdownlint-cli` on the touched docs. | docs or release maintainers | deferred |
| Evaluate `tools/agent/*` artifact-contract hardening | Agent trace and contract-stamp artifacts in `tools/agent/run.py`, `tools/agent/trace.py`, and `tools/agent/contract_stamp.py` | High | Medium | The path-bearing local artifacts are verified, but the current trace and stamp shape is also persisted, documented, validated, and kept local by default. That makes the open question a contract-boundary problem, not a small hardening fix. | `docs/security/logging-audit.md` finding for `tools/agent/*`; `docs/unknowns/logging-audit.md`; `docs/review/safe-fix-plan.md`; `docs/architecture/coverage-ledger.md` row `Machine-readable product output and local trace escape`; `docs/agent_repl_harness.md`; `.gitignore`; workflow inspection showing no repo-owned upload path | verified | no | artifact-contract audit or machine-readable output review | Determine whether any human support or review channel needs a sanitized trace or stamp contract before changing the persisted artifact shape. | Review support and artifact-sharing practice outside the repo; if a later contract change is approved, run `tools/run_pytest.sh -q tests/test_agent_harness.py` and inspect fresh local trace and stamp samples. | agent harness | deferred |
| Keep renderer and precision helpers on the maintainer-local side unless a workflow promotes them | Helper entrypoints `tools/run_renderers.py` and `tools/benchmark_render_precision.py` | Medium | Medium | The repo now proves `capture_tauri_screenshots.py` is both a CI evidence path and a maintainer baseline-refresh tool. Git history for the other two helpers still points to maintainer-local renderer or benchmark tooling, not trusted review surfaces. The remaining gap is future promotion, not missing repo-local evidence today. | `docs/review/evidence-gap-check.md` section 2; `.github/workflows/ci.yml`; `docs/manual/assets/screenshots/README.md`; git history for `tools/run_renderers.py` and `tools/benchmark_render_precision.py`; `docs/architecture/coverage-ledger.md` support-tool row; `docs/review/adversarial-pass.md` | verified | no | helper-entrypoint ownership note if future promotion happens | Keep `capture_tauri_screenshots.py` on the trusted-evidence side and treat `run_renderers.py` plus `benchmark_render_precision.py` as maintainer-local helpers unless a future workflow or README names them as review evidence. | Watch future workflow, README, and benchmark-doc changes. If one of these helpers is promoted later, add a boundary note and rerun the support-tool evidence pass. | GUI or tooling maintainers | deferred |
| Confirm PR template enforcement outside the repo | GitHub PR workflow and branch-protection behavior around `.github/pull_request_template.md` | Medium | Low | The maintenance harness can enforce asset presence and wording, but it cannot prove that GitHub or branch protection forces contributors to fill the template before merge. | `docs/review/maintenance-harness.md` remaining limits; `docs/unknowns/maintenance-harness.md` PR-template row | unknown | no | branch-protection and review-policy check | Confirm whether any out-of-repo branch-protection, review policy, or maintainer habit treats template completion as required. If not, keep this as reviewer guidance rather than pretending it is enforced. | Review GitHub branch-protection and maintainer policy outside the repo; if repo docs change later, run `npx --yes markdownlint-cli docs/review/maintenance-harness.md docs/unknowns/maintenance-harness.md`. | not declared in repo | open |

## Coverage limits

The current repo evidence still leaves these holes outside repo-local proof:

- support scripts that mutate repo or packaged state without a fully documented
  maintainer or CI audience
- release tooling, Windows signing, packaged smoke, and installer behavior that
  depend on GitHub runners, Windows tooling, or installer state outside the repo
- GitHub Pages hosting behavior after the repo uploads the committed static
  `site/` payload
- machine-readable CLI JSON, NDJSON traces, and other local artifacts that
  become telemetry once wrappers, CI, or support workflows capture them
- steering mirrors under `.claude/agents/` that can look authoritative enough
  to distort review focus if the canonical source is not restated

No reviewed anti-dark-code evidence in this repo showed a sibling repo,
submodule-owned runtime, remote config service, feature-flag dashboard,
checked-in notebook workflow, admin tool, or migration path that currently
changes shipped behavior. This backlog therefore does not add remediation items
for those categories.
