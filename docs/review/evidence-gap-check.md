<!-- markdownlint-disable-file MD013 -->

# Evidence Gap Check

This pass is read-only. It checks the `needs more evidence` backlog items
against current repo-local proof and records what still blocks certainty.

## 1. Support-script audience and real call sites

- Claim not yet proven:
  whether any hidden bootstrap, wrapper, or out-of-repo maintainer routine
  relies on `tools/safe_cleanup.py`, `tools/sync_packaged_data_mirror.py`, or
  `tools/sync_claude_agents.py` beyond the documented human-run paths
- Exact files and docs checked:
  `tools/safe_cleanup.py`, `tools/sync_packaged_data_mirror.py`,
  `tools/sync_claude_agents.py`, `.github/workflows/ci.yml`,
  `.github/workflows/release.yml`, `docs/PROJECT_INSTRUCTIONS.md`,
  `docs/00-quickstart.md`, `docs/21-loudness-profiles.md`, `CLAUDE.md`,
  `docs/contributing/ai-workflow.md`,
  `tools/validate_packaged_data_mirror.py`,
  git history for the three scripts and their nearby docs or validator paths,
  `docs/architecture/coverage-ledger.md`, `docs/review/adversarial-pass.md`,
  `docs/review/scenario-stress-test.md`,
  `docs/unknowns/adversarial-pass.md`,
  `docs/unknowns/scenario-stress-test.md`,
  `docs/unknowns/remediation-pass.md`
- Evidence that supports the concern:
  `safe_cleanup.py` performs allowlist-only deletion and writes a deterministic
  JSON summary. `sync_packaged_data_mirror.py` copies and deletes packaged-data
  mirror files under `src/mmo/data/`. `sync_claude_agents.py` rewrites the
  `.claude/agents/` mirror from the canonical `docs/claude_agents/` source.
  The side effects are real and bounded, which confirms these scripts are
  control-plane paths rather than harmless glue. The repo now proves all three
  human-run audiences: `docs/PROJECT_INSTRUCTIONS.md` and
  `docs/00-quickstart.md` tell maintainers to run `safe_cleanup.py`,
  `docs/21-loudness-profiles.md` plus `tools/validate_packaged_data_mirror.py`
  tell maintainers to run `sync_packaged_data_mirror.py` when packaged data
  drifts, and `CLAUDE.md` plus `docs/contributing/ai-workflow.md` tell local
  contributors that `.claude/agents/` is a synced convenience mirror driven by
  `sync_claude_agents.py`. CI and release still do not run any of the three
  scripts directly, but `sync_packaged_data_mirror.py` is enforced indirectly
  because `validate_contracts.py` runs `PKG.MIRROR` in CI and release.
  Git history now reinforces that split: `safe_cleanup.py` was introduced and
  later hardened through maintainer-facing docs and tests, not workflow hooks;
  `sync_packaged_data_mirror.py` was introduced beside `PKG.MIRROR` validation
  and later maintainer docs, which proves indirect enforcement rather than
  hidden execution of the sync itself; and `sync_claude_agents.py` was added as
  a local contributor convenience sync, not as CI or release automation.
- Evidence still missing:
  repo-local proof of any bootstrap or wrapper outside the recorded docs and
  history, because the repo cannot prove the absence of out-of-repo maintainer
  habits
- Next best repo-local check:
  treat the scripts as human-run maintainer tools unless a future bootstrap
  note, setup helper, or workflow starts calling them directly
- Out-of-repo boundary that still blocks certainty:
  maintainer habits or local bootstrap routines that are not written down in
  the repo
- Confidence after this pass:
  side effects are `verified`, the documented human audience is now `verified`
  for all three scripts, git history also supports that human-run audience, and
  the remaining gap is hidden automation or unwritten maintainer practice

## 2. Helper-entrypoint audience and trusted-evidence role

- Claim not yet proven:
  whether `tools/run_renderers.py` and `tools/benchmark_render_precision.py`
  have a documented audience or trusted-output role comparable to the
  screenshot capture helper
- Exact files and docs checked:
  `tools/run_renderers.py`, `tools/benchmark_render_precision.py`,
  `tools/capture_tauri_screenshots.py`, `.github/workflows/ci.yml`,
  `docs/manual/assets/screenshots/README.md`,
  `gui/desktop-tauri/tests/capture-screenshots.spec.ts`,
  git history for the three helpers and their nearby tests or workflow notes,
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
  fixed viewport contract. The repo now proves `capture_tauri_screenshots.py`
  has two real audiences: `.github/workflows/ci.yml` regenerates screenshots
  and uploads them as review artifacts, and
  `docs/manual/assets/screenshots/README.md` documents it as the maintainer
  refresh path for committed baselines. Git history now narrows the remaining
  two helpers further: `run_renderers.py` came from an internal pipeline helper
  lineage and still looks like a maintainer-local renderer or manifest tool,
  while `benchmark_render_precision.py` came in as part of a DSP feature bring
  up and still looks like a maintainer-local benchmark helper. Neither history
  trail proves a CI, release, or trusted review-evidence role.
- Evidence still missing:
  repo-local proof that `run_renderers.py` or
  `benchmark_render_precision.py` should be treated as anything broader than
  maintainer-local helpers
- Next best repo-local check:
  keep `capture_tauri_screenshots.py` on the trusted-evidence side and treat
  the other two helpers as maintainer-local unless a future README, workflow,
  or benchmark note promotes them into a named review surface
- Out-of-repo boundary that still blocks certainty:
  maintainer practice outside the repo for the renderer and benchmark helpers
- Confidence after this pass:
  helper side effects are `verified`, screenshot-helper audience and evidence
  role are `verified`, git history supports a maintainer-local role for the
  remaining two helpers, and a broader trusted-evidence role remains `unknown`

## 3. Public docs publish boundary

- Claim not yet proven:
  whether anything broader than the committed `site/` tree shapes the public
  docs path inside the repo
- Exact files and docs checked:
  `.github/workflows/pages.yml`, `site/index.html`, `site/styles.css`,
  `site/.nojekyll`, `docs/architecture/system-map.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/review/adversarial-pass.md`,
  `docs/review/scenario-stress-test.md`,
  `docs/unknowns/scenario-stress-test.md`,
  `docs/unknowns/maintenance-harness.md`,
  git history for `site/` and `pages.yml`
- Evidence that supports the concern:
  `pages.yml` is a real public publish control plane with `pages: write`,
  `id-token: write`, `actions/upload-pages-artifact`, and
  `actions/deploy-pages`, but it uploads `site/` as-is. The tracked site tree
  is only `index.html`, `styles.css`, and `.nojekyll`. I found no repo-local
  script, package task, or workflow step that generates or rewrites `site/`
  before deploy. Git history also supports direct editing of the committed
  static files rather than a generated-output flow.
- Evidence still missing:
  repo-local proof that no external tool is ever used before a commit lands,
  plus any repo-local proof of GitHub Pages hosting, caching, or environment
  behavior after the artifact leaves the repo
- Next best repo-local check:
  treat `site/` as a committed static publish payload unless a later build
  command, generator, or workflow step starts producing it
- Out-of-repo boundary that still blocks certainty:
  GitHub-hosted runner execution, `actions/*` internals, GitHub Pages hosting,
  and serving or caching behavior after deploy
- Confidence after this pass:
  the repo-owned static site payload and direct deploy contract are `verified`.
  The hosted Pages behavior is still `unknown`.

## 4. Windows release and installer boundary

- Claim not yet proven:
  which parts of the Windows release, signing, and installer path are fully
  repo-owned versus runner-, signer-, or installer-owned
- Exact files and docs checked:
  `.github/workflows/release.yml`, `tools/smoke_packaged_desktop.py`,
  `tests/test_packaged_desktop_smoke.py`, `docs/README.md`, `docs/STATUS.md`,
  `docs/architecture/system-map.md`, `docs/architecture/coverage-ledger.md`,
  `docs/review/adversarial-pass.md`,
  `docs/review/scenario-stress-test.md`,
  `docs/security/logging-audit.md`,
  `docs/unknowns/maintenance-harness.md`,
  `docs/unknowns/remediation-pass.md`,
  git history for `release.yml` and `tools/smoke_packaged_desktop.py`
- Evidence that supports the concern:
  `release.yml` validates the repo, builds platform artifacts, prepares
  optional Windows signing inputs, signs payloads and installers when secrets
  are present, performs a real Windows installer smoke run, verifies installed
  signatures, and only then assembles the GitHub release from downloaded
  artifacts. `tools/smoke_packaged_desktop.py` is the repo-owned smoke harness
  behind that path, and `tests/test_packaged_desktop_smoke.py` covers the
  NSIS preference, install-state handling, redacted receipts, uninstall
  normalization, and cleanup policy choices. `docs/README.md` and
  `docs/STATUS.md` also keep one boundary honest: automated smoke exists, but
  final human fresh-install signoff still happens outside CI when promoting a
  release candidate or public tag. The logging audit and system map both treat
  this as a real control plane with bounded but still sensitive output.
- Evidence still missing:
  repo-local proof of exact Windows certificate-store behavior, `signtool`
  availability and semantics on the hosted runner, installer side effects
  beyond the recorded state file, and a sanitized end-to-end release receipt
- Next best repo-local check:
  keep separating repo-owned workflow facts from signer, runner, and installer
  behavior, then capture a sanitized Windows dry run when that environment is
  available
- Out-of-repo boundary that still blocks certainty:
  GitHub-hosted runners, Windows certificate store behavior, `signtool`,
  installer runtime state, GitHub Releases, and CI artifact retention
- Confidence after this pass:
  the repo-owned release control plane is `verified`, but the end-to-end
  Windows release boundary remains `unknown`

## 5. Machine-readable output escape channels

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
  `mmo gui rpc` still returns those fields for the same project. `scan_session`
  now has the same shell-split pattern: `--format json-shared` drops
  `session.stems_dir`, per-stem hashes, source tags, and path-detail fields,
  and shell stdout now defaults to that shared-safe profile. The normal repo
  wrappers still keep scan output file-backed or in memory: `_analysis.py`
  shells out with `--out`, `analyze_stems.py` always writes a scan report to
  disk, `variants.py` loads the scan module directly, and the scan tests parse
  stdout in memory without uploading it. `tools/agent/*` persists local NDJSON
  trace and contract-stamp artifacts with path-bearing fields. The bug
  template asks reporters for exact commands, exact artifact paths, and
  machine-readable behavior, while also telling them to remove private file
  paths and sensitive data. That proves one repo-owned manual paste channel.
  Workflow inspection found screenshot, manual, bundle, and dist uploads, but
  no repo-owned upload path for project JSON, scan JSON, or agent trace
  artifacts.
- Evidence still missing:
  repo-local proof of whether support transcripts, maintainer issue replies, CI
  logs, or other out-of-repo habits capture the explicit local `json`,
  file-backed scan reports, or agent artifacts in practice, plus any explicit
  rule that forbids pasting raw local JSON into shared channels
- Next best repo-local check:
  inspect any remaining maintainer or support guidance in the repo, then treat
  the remaining gap as an out-of-repo workflow question instead of a missing
  code path
- Out-of-repo boundary that still blocks certainty:
  support workflows, CI log handling, and issue-thread or chat practices
  outside repo-owned automation
- Confidence after this pass:
  the path-bearing output surfaces, one manual issue-report channel, and the
  lack of repo-owned workflow uploads are `verified`. The remaining unknown is
  no longer the shell defaults. It is the handling of the explicit local
  contracts and local artifacts outside the repo.

## 6. `tools/agent/*` artifact-contract boundary

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
