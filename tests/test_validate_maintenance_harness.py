import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestValidateMaintenanceHarness(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _validator_script(self) -> Path:
        return self._repo_root() / "tools" / "validate_maintenance_harness.py"

    def _run_validator(self, repo_root: Path) -> tuple[int, dict]:
        result = subprocess.run(
            [
                self._python_cmd(),
                os.fspath(self._validator_script()),
                "--repo-root",
                os.fspath(repo_root),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        return result.returncode, json.loads(result.stdout)

    def _write(self, repo_root: Path, relative_path: str, text: str) -> None:
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _create_minimal_repo(self, repo_root: Path) -> None:
        self._write(
            repo_root,
            ".github/pull_request_template.md",
            "\n".join(
                [
                    "# PR Checklist",
                    "",
                    "## Plain Change Record",
                    "",
                    "- What changed:",
                    "- Why it changed:",
                    "- What remains unclear:",
                    "- Risk changed:",
                    "- Approval needed:",
                    "- Docs updated:",
                    "- Anti-dark-code comments checked:",
                    "- Tests or checks run:",
                    "- Repo evidence reviewed:",
                    "",
                    "## Required checks",
                    "",
                    "- [ ] Linked the exact `docs/STATUS.md` milestone checklist item(s) touched by this PR.",
                    "- [ ] Updated `docs/milestones.yaml` state if any milestone actually moved.",
                    "- [ ] Updated `CHANGELOG.md` under `## [Unreleased]` for any user-facing behavior change.",
                    "- [ ] Ran `python tools/validate_contracts.py` and the needed tests or checks.",
                    "- [ ] Listed exact blockers or skips when validation did not run in the correct environment.",
                    "- [ ] Replaced, updated, or explicitly explained any anti-dark-code comment removed by this PR.",
                    "",
                ]
            ),
        )
        self._write(
            repo_root,
            "docs/contributing/ai-workflow.md",
            "\n".join(
                [
                    "# MMO AI Workflow",
                    "",
                    "## Start From Repo Truth",
                    "",
                    "Read `AGENTS.md`, `docs/architecture/system-map.md`, `docs/architecture/coverage-ledger.md`, `docs/security/logging-audit.md`, `docs/review/adversarial-pass.md`, and `docs/review/scenario-stress-test.md` when they apply.",
                    "",
                    "## Keep Unknowns Visible",
                    "",
                    "Write unknowns down instead of guessing.",
                    "",
                    "## Respect Approval Gates",
                    "",
                    "Use `AGENTS.md` for protected areas.",
                    "",
                    "## Re-check Anti-Dark-Code Comments",
                    "",
                    "Update stale comments in the same change.",
                    "",
                    "If a change removes or rewrites an anti-dark-code comment, replace it in the same change or state in the PR record why the old comment no longer applies.",
                    "",
                ]
            ),
        )
        self._write(
            repo_root,
            "docs/review/maintenance-harness.md",
            "\n".join(
                [
                    "# Maintenance Harness",
                    "",
                    "## Hard Gates",
                    "",
                    "## Reviewer Checks Only",
                    "",
                    "## Doc Triggers",
                    "",
                    "## Protected Areas Requiring Approval",
                    "",
                    "## Logging And Telemetry Checks",
                    "",
                    "## Remaining Human-Review Limits",
                    "",
                    "The PR template keeps a comment-drift reminder.",
                    "The harness cannot prove a removed explanatory comment was the right comment to remove.",
                    "",
                ]
            ),
        )
        self._write(
            repo_root,
            "docs/unknowns/maintenance-harness.md",
            "\n".join(
                [
                    "# Maintenance Harness Unknowns",
                    "",
                    "| Area or file | Concern | Why it matters | Evidence found so far | Likely owner if known | Next best check | Risk level |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                    "| `.github/pull_request_template.md` | Template completion is not enforced | Review quality can drift | Template exists | not declared in repo | Check branch protection outside the repo | Medium |",
                    "| `.github/workflows/release.yml` | Out-of-repo behavior still matters | Release behavior crosses repo boundaries | Release workflow exists | not declared in repo | Re-check on release changes | High |",
                    "| `.claude/agents/` | Mirror drift can confuse authority | A mirrored copy can look primary | Sync path exists | not declared in repo | Re-check when sync logic changes | Medium |",
                    "| `tools/validate_maintenance_harness.py` | Narrow logging rule misses richer leaks | Reviewers can overtrust the gate | The rule only checks obvious same-line patterns | not declared in repo | Keep the logging audit current | High |",
                    "",
                ]
            ),
        )
        self._write(
            repo_root,
            "docs/README.md",
            "\n".join(
                [
                    "# MMO Docs Index",
                    "",
                    "## Contribution Workflow",
                    "",
                    "- [Contributor AI workflow](contributing/ai-workflow.md)",
                    "- [PR checklist template](../.github/pull_request_template.md)",
                    "",
                ]
            ),
        )
        self._write(repo_root, "src/dummy.py", "value = 1\n")
        self._write(repo_root, "tools/dummy.py", "value = 2\n")
        self._write(repo_root, "tests/dummy.py", "value = 3\n")

    def test_validate_maintenance_harness_current_repo_is_ok(self) -> None:
        result = subprocess.run(
            [self._python_cmd(), os.fspath(self._validator_script())],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("errors"), [])
        logging_scan = payload.get("logging_scan", {})
        self.assertTrue(logging_scan.get("ok"))
        self.assertEqual(logging_scan.get("matches"), [])

    def test_missing_required_snippet_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            self._create_minimal_repo(temp_root)
            readme_path = temp_root / "docs" / "README.md"
            readme_path.write_text("# MMO Docs Index\n", encoding="utf-8")

            returncode, payload = self._run_validator(temp_root)

        self.assertNotEqual(returncode, 0)
        self.assertFalse(payload.get("ok"))
        self.assertIn(
            "docs/README.md is missing required snippet: 'contributing/ai-workflow.md'",
            payload.get("errors", []),
        )

    def test_obvious_sensitive_logging_pattern_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            self._create_minimal_repo(temp_root)
            log_call = "print("
            secret = '"password"'
            leaky_source = "bad_line = " + repr(log_call + secret + ")") + "\n"
            leaky_source += "eval(bad_line)\n"
            self._write(
                temp_root,
                "tools/leaky.py",
                leaky_source,
            )

            returncode, payload = self._run_validator(temp_root)

        self.assertNotEqual(returncode, 0)
        self.assertFalse(payload.get("ok"))
        matches = payload.get("logging_scan", {}).get("matches", [])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].get("path"), "tools/leaky.py")
        self.assertIn("obvious-drift check", payload.get("warnings", [])[0])


if __name__ == "__main__":
    unittest.main()
