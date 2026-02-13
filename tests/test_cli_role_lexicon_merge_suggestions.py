"""Tests for mmo role-lexicon merge-suggestions CLI command and core merge logic."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from mmo.cli import main
from mmo.core.role_lexicon import merge_suggestions_into_lexicon, render_role_lexicon_yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_cli_rl_merge"


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


# ---------------------------------------------------------------------------
# Core function tests
# ---------------------------------------------------------------------------

class TestMergeSuggestionsCore(unittest.TestCase):
    def test_deterministic_output(self) -> None:
        suggestions = {
            "role_lexicon": {
                "ROLE.DRUMS.KICK": {"keywords": ["kick", "kck", "bd"]},
                "ROLE.DRUMS.SNARE": {"keywords": ["snare", "sn"]},
            }
        }
        r1 = merge_suggestions_into_lexicon(suggestions)
        r2 = merge_suggestions_into_lexicon(suggestions)
        self.assertEqual(
            json.dumps(r1, sort_keys=True),
            json.dumps(r2, sort_keys=True),
        )

    def test_deny_filters_tokens(self) -> None:
        suggestions = {
            "role_lexicon": {
                "ROLE.DRUMS.KICK": {"keywords": ["kick", "bad_token", "bd"]},
            }
        }
        result = merge_suggestions_into_lexicon(
            suggestions, deny=frozenset(["bad_token"])
        )
        merged_kws = result["merged"]["role_lexicon"]["ROLE.DRUMS.KICK"]["keywords"]
        self.assertNotIn("bad_token", merged_kws)
        self.assertIn("kick", merged_kws)
        self.assertIn("deny", result["keywords_skipped"])

    def test_allow_includes_only_listed_tokens(self) -> None:
        suggestions = {
            "role_lexicon": {
                "ROLE.DRUMS.KICK": {"keywords": ["kick", "bd", "extra"]},
            }
        }
        result = merge_suggestions_into_lexicon(
            suggestions, allow=frozenset(["kick", "bd"])
        )
        merged_kws = result["merged"]["role_lexicon"]["ROLE.DRUMS.KICK"]["keywords"]
        self.assertIn("kick", merged_kws)
        self.assertIn("bd", merged_kws)
        self.assertNotIn("extra", merged_kws)
        self.assertIn("allow_miss", result["keywords_skipped"])

    def test_allow_overrides_invalid_filter(self) -> None:
        """--allow can explicitly include digit-only or short tokens."""
        suggestions = {
            "role_lexicon": {
                "ROLE.DRUMS.KICK": {"keywords": ["5", "x", "kick"]},
            }
        }
        # Without allow: "5" and "x" would be filtered as invalid.
        r_no_allow = merge_suggestions_into_lexicon(suggestions)
        kws_no = r_no_allow["merged"]["role_lexicon"]["ROLE.DRUMS.KICK"]["keywords"]
        self.assertNotIn("5", kws_no)
        self.assertNotIn("x", kws_no)

        # With allow: "5" and "x" are explicitly included.
        r_allow = merge_suggestions_into_lexicon(
            suggestions, allow=frozenset(["5", "x", "kick"])
        )
        kws_allow = r_allow["merged"]["role_lexicon"]["ROLE.DRUMS.KICK"]["keywords"]
        self.assertIn("5", kws_allow)
        self.assertIn("x", kws_allow)

    def test_max_per_role_clamp_deterministic(self) -> None:
        keywords = [f"kw_{chr(ord('a') + i)}" for i in range(10)]
        suggestions = {
            "role_lexicon": {
                "ROLE.TEST": {"keywords": keywords},
            }
        }
        result = merge_suggestions_into_lexicon(suggestions, max_per_role=3)
        merged_kws = result["merged"]["role_lexicon"]["ROLE.TEST"]["keywords"]
        self.assertEqual(len(merged_kws), 3)
        # Must be lexicographically first 3.
        self.assertEqual(merged_kws, sorted(keywords)[:3])
        self.assertTrue(result["max_per_role_applied"])
        self.assertIn("clamp", result["keywords_skipped"])

    def test_duplicate_skipped(self) -> None:
        base = {
            "role_lexicon": {
                "ROLE.DRUMS.KICK": {"keywords": ["kick"]},
            }
        }
        suggestions = {
            "role_lexicon": {
                "ROLE.DRUMS.KICK": {"keywords": ["kick", "bd"]},
            }
        }
        result = merge_suggestions_into_lexicon(suggestions, base=base)
        self.assertIn("duplicate", result["keywords_skipped"])
        self.assertEqual(result["keywords_added_count"], 1)  # only "bd" added

    def test_invalid_tokens_skipped(self) -> None:
        suggestions = {
            "role_lexicon": {
                "ROLE.TEST": {"keywords": ["good", "42", "x"]},
            }
        }
        result = merge_suggestions_into_lexicon(suggestions)
        self.assertIn("invalid", result["keywords_skipped"])
        self.assertIn("42", result["keywords_skipped"]["invalid"])
        self.assertIn("x", result["keywords_skipped"]["invalid"])

    def test_merged_yaml_sorted_and_deterministic(self) -> None:
        suggestions = {
            "role_lexicon": {
                "ROLE.ZZZ": {"keywords": ["zzz"]},
                "ROLE.AAA": {"keywords": ["aaa"]},
            }
        }
        result = merge_suggestions_into_lexicon(suggestions)
        yaml_text = render_role_lexicon_yaml(result["merged"])
        lines = yaml_text.strip().split("\n")
        # Roles must be sorted.
        role_lines = [l for l in lines if l.startswith("  ROLE.")]
        self.assertEqual(role_lines, sorted(role_lines))

    def test_base_roles_preserved(self) -> None:
        base = {
            "role_lexicon": {
                "ROLE.EXISTING": {"keywords": ["existing_kw"]},
            }
        }
        suggestions = {
            "role_lexicon": {
                "ROLE.NEW": {"keywords": ["new_kw"]},
            }
        }
        result = merge_suggestions_into_lexicon(suggestions, base=base)
        merged = result["merged"]["role_lexicon"]
        self.assertIn("ROLE.EXISTING", merged)
        self.assertIn("ROLE.NEW", merged)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCliMergeSuggestions(unittest.TestCase):
    def test_merge_produces_output_file(self) -> None:
        base_dir = _SANDBOX / "basic"
        sugg_path = base_dir / "suggestions.yaml"
        out_path = base_dir / "merged.yaml"

        _write_yaml(sugg_path, (
            "role_lexicon:\n"
            "  ROLE.DRUMS.KICK:\n"
            "    keywords:\n"
            "      - kick\n"
            "      - bd\n"
        ))

        exit_code, stdout, stderr = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out_path),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertTrue(out_path.exists())
        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["keywords_added_count"], 2)

    def test_dry_run_does_not_write(self) -> None:
        base_dir = _SANDBOX / "dryrun"
        sugg_path = base_dir / "suggestions.yaml"
        out_path = base_dir / "merged.yaml"

        _write_yaml(sugg_path, (
            "role_lexicon:\n"
            "  ROLE.DRUMS.KICK:\n"
            "    keywords:\n"
            "      - kick\n"
        ))

        exit_code, stdout, stderr = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out_path),
            "--dry-run",
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertFalse(out_path.exists())
        result = json.loads(stdout)
        self.assertTrue(result["dry_run"])

    def test_deterministic_cli_output(self) -> None:
        base_dir = _SANDBOX / "determinism"
        sugg_path = base_dir / "suggestions.yaml"
        out1 = base_dir / "merged1.yaml"
        out2 = base_dir / "merged2.yaml"

        _write_yaml(sugg_path, (
            "role_lexicon:\n"
            "  ROLE.DRUMS.SNARE:\n"
            "    keywords:\n"
            "      - snare\n"
            "      - sn\n"
            "  ROLE.DRUMS.KICK:\n"
            "    keywords:\n"
            "      - kick\n"
        ))

        exit1, stdout1, stderr1 = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out1),
        ])
        exit2, stdout2, stderr2 = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out2),
        ])

        self.assertEqual(exit1, 0, msg=stderr1)
        self.assertEqual(exit2, 0, msg=stderr2)
        self.assertEqual(
            out1.read_text(encoding="utf-8"),
            out2.read_text(encoding="utf-8"),
        )

    def test_deny_allow_cli_flags(self) -> None:
        base_dir = _SANDBOX / "deny_allow"
        sugg_path = base_dir / "suggestions.yaml"
        out_path = base_dir / "merged.yaml"

        _write_yaml(sugg_path, (
            "role_lexicon:\n"
            "  ROLE.DRUMS.KICK:\n"
            "    keywords:\n"
            "      - kick\n"
            "      - bad\n"
            "      - extra\n"
        ))

        exit_code, stdout, stderr = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out_path),
            "--deny", "bad",
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        self.assertIn("deny", result["keywords_skipped_count"])

    def test_max_per_role_cli(self) -> None:
        base_dir = _SANDBOX / "clamp"
        sugg_path = base_dir / "suggestions.yaml"
        out_path = base_dir / "merged.yaml"

        _write_yaml(sugg_path, (
            "role_lexicon:\n"
            "  ROLE.TEST:\n"
            "    keywords:\n"
            "      - alpha\n"
            "      - bravo\n"
            "      - charlie\n"
            "      - delta\n"
            "      - echo\n"
        ))

        exit_code, stdout, stderr = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out_path),
            "--max-per-role", "2",
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        self.assertTrue(result["max_per_role_applied"])
        self.assertEqual(result["keywords_added_count"], 2)

    def test_json_paths_forward_slashes(self) -> None:
        base_dir = _SANDBOX / "slashes"
        sugg_path = base_dir / "suggestions.yaml"
        out_path = base_dir / "merged.yaml"

        _write_yaml(sugg_path, (
            "role_lexicon:\n"
            "  ROLE.TEST:\n"
            "    keywords:\n"
            "      - test_token\n"
        ))

        exit_code, stdout, stderr = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out_path),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        self.assertNotIn("\\", result["out_path"])

    def test_text_format_output(self) -> None:
        base_dir = _SANDBOX / "textfmt"
        sugg_path = base_dir / "suggestions.yaml"
        out_path = base_dir / "merged.yaml"

        _write_yaml(sugg_path, (
            "role_lexicon:\n"
            "  ROLE.DRUMS.KICK:\n"
            "    keywords:\n"
            "      - kick\n"
        ))

        exit_code, stdout, stderr = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out_path),
            "--format", "text",
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertIn("written to", stdout.lower())

    def test_tolerates_header_comments(self) -> None:
        """Suggestions YAML with # HUMAN REVIEW REQUIRED header must parse fine."""
        base_dir = _SANDBOX / "comments"
        sugg_path = base_dir / "suggestions.yaml"
        out_path = base_dir / "merged.yaml"

        _write_yaml(sugg_path, (
            "# HUMAN REVIEW REQUIRED\n"
            "# Generated by tools/stem_corpus_scan.py as a starter draft.\n"
            "role_lexicon:\n"
            "  ROLE.DRUMS.KICK:\n"
            "    keywords:\n"
            "      - kick\n"
        ))

        exit_code, stdout, stderr = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out_path),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        self.assertTrue(result["ok"])

    def test_merged_yaml_sorting_and_dedupe(self) -> None:
        base_dir = _SANDBOX / "sortdedupe"
        sugg_path = base_dir / "suggestions.yaml"
        out_path = base_dir / "merged.yaml"

        _write_yaml(sugg_path, (
            "role_lexicon:\n"
            "  ROLE.ZZZ:\n"
            "    keywords:\n"
            "      - zzz\n"
            "      - zzz\n"
            "  ROLE.AAA:\n"
            "    keywords:\n"
            "      - aaa\n"
        ))

        exit_code, _, stderr = _run_main([
            "role-lexicon", "merge-suggestions",
            "--suggestions", str(sugg_path),
            "--out", str(out_path),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        content = out_path.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        role_lines = [l for l in lines if l.startswith("  ROLE.")]
        self.assertEqual(role_lines, sorted(role_lines))
        # "zzz" should appear only once.
        self.assertEqual(content.count("zzz"), 1)


if __name__ == "__main__":
    unittest.main()
