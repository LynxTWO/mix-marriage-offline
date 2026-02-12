import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from mmo.cli import main
from mmo.core.stems_overrides import apply_overrides, load_stems_overrides


def _sample_stems_map() -> dict:
    return {
        "version": "0.1.0",
        "stems_index_ref": "demo/stems_index.json",
        "roles_ref": "ontology/roles.yaml",
        "assignments": [
            {
                "file_id": "STEMFILE.aaaaaaaaaa",
                "rel_path": "stems/vox_lead.wav",
                "role_id": "ROLE.OTHER.UNKNOWN",
                "confidence": 0.1,
                "bus_group": "BG.OTHER",
                "reasons": [
                    "no_match",
                    "override:OLD",
                    "confidence=0.100",
                ],
                "link_group_id": None,
            },
            {
                "file_id": "STEMFILE.bbbbbbbbbb",
                "rel_path": "stems/kick.wav",
                "role_id": "ROLE.DRUM.KICK",
                "confidence": 0.9,
                "bus_group": "BG.RHYTHM",
                "reasons": ["keyword=kick(+4)", "confidence=0.750"],
                "link_group_id": None,
            },
        ],
        "summary": {
            "counts_by_role": {
                "ROLE.DRUM.KICK": 1,
                "ROLE.OTHER.UNKNOWN": 1,
            },
            "counts_by_bus_group": {
                "BG.OTHER": 1,
                "BG.RHYTHM": 1,
            },
            "unknown_files": 1,
        },
    }


class TestStemsOverrides(unittest.TestCase):
    def _run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_load_stems_overrides_valid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            overrides_path = Path(temp_dir) / "stems_overrides.yaml"
            overrides_path.write_text(
                "\n".join(
                    [
                        "version: \"0.1.0\"",
                        "overrides:",
                        "  - override_id: \"OVERRIDE.001\"",
                        "    match:",
                        "      rel_path: \"stems/kick.wav\"",
                        "    role_id: \"ROLE.DRUM.KICK\"",
                        "  - override_id: \"OVERRIDE.010\"",
                        "    match:",
                        "      regex: \"^stems/vox.*\\\\.wav$\"",
                        "    role_id: \"ROLE.VOCAL.LEAD\"",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            payload = load_stems_overrides(overrides_path)
            self.assertEqual(payload.get("version"), "0.1.0")
            overrides = payload.get("overrides")
            self.assertIsInstance(overrides, list)
            if not isinstance(overrides, list):
                return
            self.assertEqual(
                [item.get("override_id") for item in overrides],
                ["OVERRIDE.001", "OVERRIDE.010"],
            )

    def test_load_stems_overrides_rejects_unsorted_override_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            overrides_path = Path(temp_dir) / "stems_overrides.yaml"
            overrides_path.write_text(
                "\n".join(
                    [
                        "version: \"0.1.0\"",
                        "overrides:",
                        "  - override_id: \"OVERRIDE.010\"",
                        "    match:",
                        "      rel_path: \"stems/vox.wav\"",
                        "    role_id: \"ROLE.VOCAL.LEAD\"",
                        "  - override_id: \"OVERRIDE.001\"",
                        "    match:",
                        "      rel_path: \"stems/kick.wav\"",
                        "    role_id: \"ROLE.DRUM.KICK\"",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as exc:
                load_stems_overrides(overrides_path)
            self.assertIn("sorted by override_id", str(exc.exception))

    def test_load_stems_overrides_rejects_invalid_regex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            overrides_path = Path(temp_dir) / "stems_overrides.yaml"
            overrides_path.write_text(
                "\n".join(
                    [
                        "version: \"0.1.0\"",
                        "overrides:",
                        "  - override_id: \"OVERRIDE.001\"",
                        "    match:",
                        "      regex: \"[\"",
                        "    role_id: \"ROLE.VOCAL.LEAD\"",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as exc:
                load_stems_overrides(overrides_path)
            self.assertIn("failed to compile", str(exc.exception))
            self.assertIn("OVERRIDE.001", str(exc.exception))

    def test_apply_overrides_uses_first_sorted_override_id(self) -> None:
        stems_map = _sample_stems_map()
        overrides_payload = {
            "version": "0.1.0",
            "overrides": [
                {
                    "override_id": "OVERRIDE.010",
                    "match": {"rel_path": "stems/vox_lead.wav"},
                    "role_id": "ROLE.VOCAL.DOUBLES",
                },
                {
                    "override_id": "OVERRIDE.001",
                    "match": {"regex": "^stems/vox.*\\.wav$"},
                    "role_id": "ROLE.VOCAL.LEAD",
                },
            ],
        }

        patched = apply_overrides(stems_map, overrides_payload)
        self.assertNotEqual(patched, stems_map)
        self.assertEqual(
            patched["assignments"][0]["role_id"],
            "ROLE.VOCAL.LEAD",
        )
        self.assertEqual(
            patched["assignments"][0]["reasons"],
            ["no_match", "confidence=0.100", "override:OVERRIDE.001"],
        )
        self.assertEqual(patched["summary"]["unknown_files"], 0)
        self.assertEqual(
            patched["summary"]["counts_by_role"],
            {"ROLE.DRUM.KICK": 1, "ROLE.VOCAL.LEAD": 1},
        )
        self.assertEqual(
            stems_map["assignments"][0]["role_id"],
            "ROLE.OTHER.UNKNOWN",
        )

    def test_cli_stems_overrides_default_validate_apply_and_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_map_path = temp_path / "stems_map.json"
            overrides_path = temp_path / "stems_overrides.yaml"
            template_path = temp_path / "template.yaml"
            out_map_path = temp_path / "stems_map.overridden.json"

            stems_map_path.write_text(
                json.dumps(_sample_stems_map(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            overrides_path.write_text(
                "\n".join(
                    [
                        "version: \"0.1.0\"",
                        "overrides:",
                        "  - override_id: \"OVERRIDE.001\"",
                        "    match:",
                        "      rel_path: \"stems/vox_lead.wav\"",
                        "    role_id: \"ROLE.VOCAL.LEAD\"",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            default_exit, _, default_stderr = self._run_main(
                [
                    "stems",
                    "overrides",
                    "default",
                    "--out",
                    str(template_path),
                ]
            )
            self.assertEqual(default_exit, 0)
            self.assertEqual(default_stderr, "")
            self.assertIn("override_id", template_path.read_text(encoding="utf-8"))
            self.assertIn("# Stem assignment overrides.", template_path.read_text(encoding="utf-8"))

            validate_exit, validate_stdout, validate_stderr = self._run_main(
                [
                    "stems",
                    "overrides",
                    "validate",
                    "--in",
                    str(overrides_path),
                ]
            )
            self.assertEqual(validate_exit, 0)
            self.assertEqual(validate_stderr, "")
            self.assertEqual(validate_stdout.strip(), "Stems overrides are valid.")

            apply_exit, apply_stdout, apply_stderr = self._run_main(
                [
                    "stems",
                    "apply-overrides",
                    "--map",
                    str(stems_map_path),
                    "--overrides",
                    str(overrides_path),
                    "--out",
                    str(out_map_path),
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(apply_exit, 0)
            self.assertEqual(apply_stderr, "")
            apply_payload = json.loads(apply_stdout)
            self.assertEqual(apply_payload["assignments"][0]["role_id"], "ROLE.VOCAL.LEAD")
            self.assertTrue(out_map_path.exists())

            review_exit, review_stdout, review_stderr = self._run_main(
                [
                    "stems",
                    "review",
                    "--map",
                    str(out_map_path),
                    "--format",
                    "text",
                ]
            )
            self.assertEqual(review_exit, 0)
            self.assertEqual(review_stderr, "")
            self.assertIn("stems/vox_lead.wav", review_stdout)
            self.assertIn("ROLE.VOCAL.LEAD", review_stdout)
            self.assertIn("unknown_files=0", review_stdout)


if __name__ == "__main__":
    unittest.main()
