<!-- markdownlint-disable-file MD013 -->

# Evidence Gap Check

This pass is read-only. It checks the `needs more evidence` backlog items
against current repo-local proof and records what still blocks certainty.

## 1. Support-script audience and real call sites

- Claim not yet proven:
  which maintainer, CI, or release workflows rely on
  `tools/safe_cleanup.py`, `tools/sync_packaged_data_mirror.py`, and
  `tools/sync_claude_agents.py`
- Exact files and docs checked:
  `tools/safe_cleanup.py`, `tools/sync_packaged_data_mirror.py`,
  `tools/sync_claude_agents.py`, `docs/architecture/coverage-ledger.md`,
  `docs/review/adversarial-pass.md`, `docs/review/scenario-stress-test.md`,
  `docs/unknowns/adversarial-pass.md`,
  `docs/unknowns/scenario-stress-test.md`,
  `docs/unknowns/remediation-pass.md`
- Evidence that supports the concern:
  `safe_cleanup.py` performs allowlist-only deletion and writes a deterministic
  JSON summary. `sync_packaged_data_mirror.py` copies and deletes packaged-data
  mirror files under `src/mmo/data/`. `sync_claude_agents.py` rewrites the
  `.claude/agents/` mirror from the canonical `docs/claude_agents/` source.
  The side effects are real and bounded, which confirms these scripts are
  control-plane paths rather than harmless glue.
- Evidence still missing:
  repo-local proof of who runs each script, how often each one is used, and
  whether any workflow or maintainer runbook treats them as standard operating
  steps
- Next best repo-local check:
  trace each script through workflow jobs, docs, runbooks, and any helper
  wrappers still in the repo
- Out-of-repo boundary that still blocks certainty:
  maintainer habits or release procedures that are not written down in the repo
- Confidence after this pass:
  side effects are `verified`, but audience and ownership stay `unknown`

## 2. Helper-entrypoint audience and trusted-evidence role

- Claim not yet proven:
  whether `tools/run_renderers.py`, `tools/benchmark_render_precision.py`, and
  `tools/capture_tauri_screenshots.py` are CI-only, maintainer-only, or
  operator-facing, and whether their outputs count as trusted review evidence
- Exact files and docs checked:
  `tools/run_renderers.py`, `tools/benchmark_render_precision.py`,
  `tools/capture_tauri_screenshots.py`,
  `docs/architecture/coverage-ledger.md`,
  `docs/review/adversarial-pass.md`,
  `docs/review/scenario-stress-test.md`,
  `docs/unknowns/adversarial-pass.md`,
  `docs/unknowns/scenario-stress-test.md`,
  `docs/unknowns/remediation-pass.md`
- Evidence that supports the concern:
  `run_renderers.py` validates plugins, applies gates, loads a report, runs
  renderers, and writes a render manifest outside the main CLI story.
  `benchmark_render_precision.py` writes temp scene and request artifacts,
  calls `mmo.cli.main("render-run", ...)`, and hashes outputs. The screenshot
  helper runs Playwright and refreshes committed screenshot baselines with a
  fixed viewport contract.
- Evidence still missing:
  repo-local proof of intended audience, ownership, and whether these outputs
  are CI evidence, maintainer-only artifacts, or operator-facing results
- Next best repo-local check:
  trace the helpers through workflow files, README notes, and test harness docs
- Out-of-repo boundary that still blocks certainty:
  maintainer practice outside the repo, plus browser or Playwright runtime
  behavior for screenshot capture
- Confidence after this pass:
  helper side effects are `verified`, but audience and evidence role stay
  `unknown`

## 3. Public publish and Windows release boundaries

- Claim not yet proven:
  how `site/` is produced, and which parts of the Windows release, signing, and
  installer path are repo-owned versus runner- or installer-owned
- Exact files and docs checked:
  `.github/workflows/pages.yml`, `.github/workflows/release.yml`,
  `site/index.html`, `site/styles.css`, `tools/smoke_packaged_desktop.py`,
  `docs/architecture/system-map.md`, `docs/architecture/coverage-ledger.md`,
  `docs/review/adversarial-pass.md`,
  `docs/review/scenario-stress-test.md`,
  `docs/security/logging-audit.md`,
  `docs/unknowns/maintenance-harness.md`,
  `docs/unknowns/remediation-pass.md`
- Evidence that supports the concern:
  `pages.yml` is a real public publish control plane with `pages: write`,
  `id-token: write`, and `actions/deploy-pages`. `release.yml` validates the
  repo, builds release artifacts, and performs Windows install verification.
  `tools/smoke_packaged_desktop.py` emits path-rich smoke summaries and raw
  installer output on failure. The system map and logging audit both treat
  release and publish as real operational boundaries.
- Evidence still missing:
  repo-local proof of whether `site/` is hand-maintained or generated, plus
  repo-local proof of exact Windows installer and signing behavior beyond
  workflow comments and smoke helpers
- Next best repo-local check:
  inspect any remaining release or docs-publish notes and separate repo-owned
  facts from runner- and installer-owned behavior
- Out-of-repo boundary that still blocks certainty:
  GitHub Pages deploy behavior, GitHub-hosted runners, Windows certificate
  store behavior, installer runtime state, and CI artifact retention
- Confidence after this pass:
  the publish and release control planes are `verified`, but the missing
  boundary details remain `unknown`

## 4. Machine-readable output escape channels

- Claim not yet proven:
  which shared channels beyond the repo bug template capture or forbid
  machine-readable output from `_project.py`, `scan_session.py`, and
  `tools/agent/*`
- Exact files and docs checked:
  `src/mmo/cli_commands/_project.py`, `src/mmo/tools/scan_session.py`,
  `src/mmo/cli_commands/_gui_rpc.py`, `src/mmo/cli_commands/_analysis.py`,
  `tools/agent/run.py`, `tools/agent/trace.py`,
  `tools/agent/contract_stamp.py`, `.github/ISSUE_TEMPLATE/bug_report.yml`,
  `.github/ISSUE_TEMPLATE/feature_request.yml`,
  `.github/pull_request_template.md`, `.github/workflows/ci.yml`,
  `.github/workflows/release.yml`, `docs/13-gui-handshake.md`,
  `docs/user_guide.md`, `docs/manual/04-the-main-workflows.md`,
  `docs/agent_repl_harness.md`, `gui/server.mjs`, `gui/web/app.js`,
  `tests/test_cli_project_show.py`, `tests/test_cli_project_load_save.py`,
  `tests/test_cli_scan_lfe_audit.py`, `tests/test_cli_gui_rpc.py`,
  `tests/test_analyze_stems_keep_scan.py`, `tests/test_agent_harness.py`,
  `docs/security/logging-audit.md`,
  `docs/unknowns/logging-audit.md`,
  `docs/review/scenario-stress-test.md`,
  `docs/unknowns/adversarial-pass.md`,
  `docs/unknowns/scenario-stress-test.md`,
  `docs/unknowns/remediation-pass.md`
- Evidence that supports the concern:
  `_project.py` prints `project_dir`, per-artifact `absolute_path`, and related
  machine-readable state, and the project CLI tests parse that stdout as a
  stable JSON contract. `_gui_rpc.py`, `gui/server.mjs`, and `gui/web/app.js`
  prove one local browser-visible path for that `project.show` JSON through the
  GUI RPC bridge, and `docs/13-gui-handshake.md` documents that flow. A local
  runtime spot-check now confirms the route split: `project show --format
  json-shared` omits `project_dir` and per-artifact `absolute_path`, while
  `mmo gui rpc` still returns those fields for the same project. By contrast,
  `scan_session.py` emits report JSON with path-bearing fields and
  media-tag-derived content, but the normal repo wrappers use file-backed or
  in-memory handling: `_analysis.py` shells out with `--out`,
  `analyze_stems.py` always writes a scan report to disk, `variants.py` loads
  the scan module directly, and the scan tests parse stdout in memory without
  uploading it. `tools/agent/*` persists local NDJSON trace and contract-stamp
  artifacts with path-bearing fields. The bug template asks reporters for exact
  commands, exact artifact paths, and machine-readable behavior, while also
  telling them to remove private file paths and sensitive data. That proves one
  repo-owned manual paste channel. Workflow inspection found screenshot,
  manual, bundle, and dist uploads, but no repo-owned upload path for project
  JSON, scan JSON, or agent trace artifacts.
- Evidence still missing:
  repo-local proof of whether support transcripts, maintainer issue replies, CI
  logs, or other out-of-repo habits capture these outputs in practice, plus any
  explicit rule that forbids pasting raw project or scan JSON into shared
  channels
- Next best repo-local check:
  inspect any remaining maintainer or support guidance in the repo, then treat
  the remaining gap as an out-of-repo workflow question instead of a missing
  code path
- Out-of-repo boundary that still blocks certainty:
  support workflows, CI log handling, and issue-thread or chat practices
  outside repo-owned automation
- Confidence after this pass:
  the path-bearing output surfaces, one manual issue-report channel, and the
  lack of repo-owned workflow uploads are `verified`, but the full
  escape-channel map stays `unknown`

## 5. `tools/agent/*` artifact-contract boundary

- Claim not yet proven:
  whether any shared channel needs a sanitized trace or contract-stamp
  format before the repo changes the current persisted artifact shape
- Exact files and docs checked:
  `tools/agent/run.py`, `tools/agent/trace.py`,
  `tools/agent/contract_stamp.py`, `.gitignore`,
  `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/workflows/ci.yml`,
  `.github/workflows/release.yml`, `docs/agent_repl_harness.md`,
  `tests/test_agent_harness.py`, `docs/security/logging-audit.md`,
  `docs/unknowns/logging-audit.md`, `docs/review/safe-fix-plan.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/remediation-pass.md`
- Evidence that supports the concern:
  the agent harness intentionally persists local trace and contract-stamp
  artifacts. The current shape is deterministic, documented, and validated by
  existing docs and tests. `.gitignore` excludes `sandbox_tmp/` and
  `.mmo_agent/`, which supports the local-artifact contract. Workflow
  inspection found no repo-owned upload path for those files. The bug template
  leaves open generic manual path sharing, but it does not name these artifacts
  specifically. That makes future hardening a contract-boundary change rather
  than a casual cleanup.
- Evidence still missing:
  repo-local proof that any shared or automated channel requires a sanitized
  artifact contract, or that a human support workflow expects these exact files
  in issue threads or PR review
- Next best repo-local check:
  confirm whether any repo-owned support, review, or workflow note asks humans
  to share these artifacts before planning a contract change
- Out-of-repo boundary that still blocks certainty:
  manual sharing of trace files, support transcripts, or CI artifact handling
  outside the repo
- Confidence after this pass:
  the artifact shape and lack of repo-owned upload paths are `verified`, but
  the need for a new contract stays `unknown`

## 6. PR template enforcement outside the repo

- Claim not yet proven:
  whether branch protection, review policy, or maintainer workflow outside the
  repo requires contributors to complete `.github/pull_request_template.md`
- Exact files and docs checked:
  `.github/pull_request_template.md`,
  `docs/review/maintenance-harness.md`,
  `docs/unknowns/maintenance-harness.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/remediation-pass.md`
- Evidence that supports the concern:
  the repo has a real PR template and a maintenance harness that validates its
  presence and wording, but no repo-local GitHub policy file or branch-setting
  artifact proves completion is enforced before merge
- Evidence still missing:
  any repo-local proof of branch protection or review rules that require the
  template to be filled out
- Next best repo-local check:
  check whether any additional workflow or maintainer doc in the repo narrows
  the enforcement story further
- Out-of-repo boundary that still blocks certainty:
  GitHub branch protection and maintainer review policy outside the repo
- Confidence after this pass:
  template presence is `verified`, but enforcement remains `unknown`
