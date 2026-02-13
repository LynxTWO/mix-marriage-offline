import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.cli import main
from mmo.core.roles import list_roles


def _write_tiny_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8)


class TestCliStemsClassify(unittest.TestCase):
    def _run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_classify_repeat_runs_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_path = temp_path / "stems_map.json"
            _write_tiny_wav(root / "stems" / "kick.wav")
            _write_tiny_wav(root / "stems" / "snare.wav")

            args = [
                "stems",
                "classify",
                "--root",
                str(root),
                "--out",
                str(out_path),
                "--format",
                "text",
            ]
            first_exit, first_stdout, first_stderr = self._run_main(args)
            first_payload_text = out_path.read_text(encoding="utf-8")

            second_exit, second_stdout, second_stderr = self._run_main(args)
            second_payload_text = out_path.read_text(encoding="utf-8")

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertEqual(first_stdout, second_stdout)
            self.assertEqual(first_stderr, second_stderr)
            self.assertEqual(first_payload_text, second_payload_text)

            payload = json.loads(first_payload_text)
            self.assertEqual(payload.get("version"), "0.1.0")
            assignments = payload.get("assignments")
            self.assertIsInstance(assignments, list)
            if not isinstance(assignments, list):
                return
            rel_paths = [item.get("rel_path") for item in assignments if isinstance(item, dict)]
            self.assertEqual(rel_paths, sorted(rel_paths))

    def test_explain_outputs_match_evidence_for_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            _write_tiny_wav(root / "stems" / "kick.wav")
            _write_tiny_wav(root / "stems" / "snare.wav")

            args = [
                "stems",
                "explain",
                "--root",
                str(root),
                "--file",
                "stems/kick.wav",
                "--format",
                "json",
            ]
            first_exit, first_stdout, first_stderr = self._run_main(args)
            second_exit, second_stdout, second_stderr = self._run_main(args)

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertEqual(first_stdout, second_stdout)
            self.assertEqual(first_stderr, second_stderr)

            payload = json.loads(first_stdout)
            self.assertEqual(payload.get("rel_path"), "stems/kick.wav")
            self.assertEqual(payload.get("role_id"), "ROLE.DRUM.KICK")
            candidates = payload.get("candidates")
            self.assertIsInstance(candidates, list)
            if not isinstance(candidates, list) or not candidates:
                return
            first_candidate = candidates[0]
            self.assertEqual(first_candidate.get("role_id"), "ROLE.DRUM.KICK")

    def test_explain_text_includes_derived_token_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            _write_tiny_wav(root / "stems" / "snareup.wav")

            args = [
                "stems",
                "explain",
                "--root",
                str(root),
                "--file",
                "stems/snareup.wav",
                "--format",
                "text",
            ]
            first_exit, first_stdout, first_stderr = self._run_main(args)
            second_exit, second_stdout, second_stderr = self._run_main(args)

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertEqual(first_stdout, second_stdout)
            self.assertEqual(first_stderr, second_stderr)
            self.assertIn("derived_evidence:", first_stdout)
            self.assertIn("token_split:snareup->snare+up", first_stdout)

    def test_explain_text_includes_compound_role_split_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            _write_tiny_wav(root / "stems" / "backingvox1.wav")

            args = [
                "stems",
                "explain",
                "--root",
                str(root),
                "--file",
                "stems/backingvox1.wav",
                "--format",
                "text",
            ]
            first_exit, first_stdout, first_stderr = self._run_main(args)
            second_exit, second_stdout, second_stderr = self._run_main(args)

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertEqual(first_stdout, second_stdout)
            self.assertEqual(first_stderr, second_stderr)
            self.assertIn("derived_evidence:", first_stdout)
            self.assertIn(
                "token_split_compound:backingvox->backing,vox", first_stdout
            )

    def test_unknown_role_lexicon_file_error_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_path = temp_path / "stems_map.json"
            missing_lexicon_path = temp_path / "missing.lexicon.yaml"
            _write_tiny_wav(root / "stems" / "kick.wav")

            args = [
                "stems",
                "classify",
                "--root",
                str(root),
                "--out",
                str(out_path),
                "--role-lexicon",
                str(missing_lexicon_path),
            ]
            first_exit, first_stdout, first_stderr = self._run_main(args)
            second_exit, second_stdout, second_stderr = self._run_main(args)

            self.assertNotEqual(first_exit, 0)
            self.assertNotEqual(second_exit, 0)
            self.assertEqual(first_stdout, second_stdout)
            self.assertEqual(first_stderr, second_stderr)
            self.assertIn("Failed to read Role lexicon YAML from", first_stderr)

    def test_unknown_role_in_lexicon_error_lists_sorted_known_roles(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        known_roles = list_roles(repo_root / "ontology" / "roles.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_path = temp_path / "stems_map.json"
            lexicon_path = temp_path / "role_lexicon.yaml"

            _write_tiny_wav(root / "stems" / "kick.wav")
            lexicon_path.write_text(
                "\n".join(
                    [
                        "role_lexicon:",
                        "  ROLE.UNKNOWN.CUSTOM:",
                        "    keywords:",
                        "      - custom",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            args = [
                "stems",
                "classify",
                "--root",
                str(root),
                "--out",
                str(out_path),
                "--role-lexicon",
                str(lexicon_path),
            ]
            first_exit, first_stdout, first_stderr = self._run_main(args)
            second_exit, second_stdout, second_stderr = self._run_main(args)

            expected = (
                "Unknown role_id in role_lexicon: ROLE.UNKNOWN.CUSTOM. "
                f"Known role_ids: {', '.join(known_roles)}"
            )
            self.assertNotEqual(first_exit, 0)
            self.assertNotEqual(second_exit, 0)
            self.assertEqual(first_stdout, second_stdout)
            self.assertEqual(first_stderr, second_stderr)
            self.assertEqual(first_stderr.strip(), expected)

    def test_no_common_lexicon_flag_disables_builtin_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_path = temp_path / "stems_map.json"
            # Use electricgtr2 — only matches via common lexicon keyword
            # "electricgtr", and has no compound role split that would
            # produce sub-tokens matching roles.yaml keywords.
            _write_tiny_wav(root / "stems" / "electricgtr2.wav")

            default_args = [
                "stems",
                "classify",
                "--root",
                str(root),
                "--out",
                str(out_path),
                "--format",
                "json",
            ]
            default_exit, default_stdout, default_stderr = self._run_main(default_args)
            self.assertEqual(default_exit, 0, msg=default_stderr)
            default_payload = json.loads(default_stdout)
            default_assignments = default_payload.get("assignments")
            self.assertIsInstance(default_assignments, list)
            if not isinstance(default_assignments, list) or not default_assignments:
                return
            self.assertEqual(default_assignments[0].get("role_id"), "ROLE.GTR.ELECTRIC")

            disabled_args = [
                *default_args,
                "--no-common-lexicon",
            ]
            disabled_exit, disabled_stdout, disabled_stderr = self._run_main(disabled_args)
            self.assertEqual(disabled_exit, 0, msg=disabled_stderr)
            disabled_payload = json.loads(disabled_stdout)
            disabled_assignments = disabled_payload.get("assignments")
            self.assertIsInstance(disabled_assignments, list)
            if not isinstance(disabled_assignments, list) or not disabled_assignments:
                return
            self.assertEqual(disabled_assignments[0].get("role_id"), "ROLE.OTHER.UNKNOWN")


if __name__ == "__main__":
    unittest.main()
