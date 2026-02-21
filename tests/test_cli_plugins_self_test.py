import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from mmo.cli import main


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class TestCliPluginsSelfTest(unittest.TestCase):
    def test_plugins_self_test_outputs_are_byte_identical_for_gain_and_tilt(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        output_names = (
            "input.wav",
            "output.wav",
            "event_log.jsonl",
            "render_execute.json",
            "render_qa.json",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for plugin_id in ("gain_v0", "tilt_eq_v0"):
                out_dir = temp_root / plugin_id
                exit_a, stdout_a, stderr_a = _run_main(
                    [
                        "plugins",
                        "self-test",
                        plugin_id,
                        "--out-dir",
                        str(out_dir),
                    ]
                )
                self.assertEqual(exit_a, 0, msg=stderr_a)
                self.assertEqual(stderr_a, "")

                payload_a = json.loads(stdout_a)
                self.assertEqual(payload_a.get("plugin_id"), plugin_id)
                self.assertEqual(payload_a.get("out_dir"), out_dir.resolve().as_posix())

                bytes_a = {
                    output_name: (out_dir / output_name).read_bytes()
                    for output_name in output_names
                }

                exit_b, stdout_b, stderr_b = _run_main(
                    [
                        "plugins",
                        "self-test",
                        plugin_id,
                        "--out-dir",
                        str(out_dir),
                        "--force",
                    ]
                )
                self.assertEqual(exit_b, 0, msg=stderr_b)
                self.assertEqual(stderr_b, "")
                self.assertEqual(stdout_a, stdout_b)

                bytes_b = {
                    output_name: (out_dir / output_name).read_bytes()
                    for output_name in output_names
                }
                self.assertEqual(bytes_a, bytes_b)

                render_execute = json.loads((out_dir / "render_execute.json").read_text(encoding="utf-8"))
                execute_job = render_execute["jobs"][0]
                self.assertNotIn("\\", execute_job["inputs"][0]["path"])
                self.assertNotIn("\\", execute_job["outputs"][0]["path"])

                render_qa = json.loads((out_dir / "render_qa.json").read_text(encoding="utf-8"))
                qa_job = render_qa["jobs"][0]
                self.assertNotIn("\\", qa_job["input"]["path"])
                self.assertNotIn("\\", qa_job["outputs"][0]["path"])


if __name__ == "__main__":
    unittest.main()
