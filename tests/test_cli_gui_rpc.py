"""Tests for ``mmo gui rpc``."""

import contextlib
import io
import json
import os
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from mmo import __version__ as _MMO_VERSION
from mmo.cli import main
from mmo.cli_commands import _gui_rpc

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_gui_rpc" / str(os.getpid())
)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _run_rpc(
    requests: list[dict[str, object] | str],
) -> tuple[int, list[dict[str, object]], str, str]:
    request_lines: list[str] = []
    for request in requests:
        if isinstance(request, str):
            request_lines.append(request)
        else:
            request_lines.append(json.dumps(request, sort_keys=True))

    stdin_payload = ""
    if request_lines:
        stdin_payload = "\n".join(request_lines) + "\n"

    stdin = io.StringIO(stdin_payload)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdin", stdin):
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(["gui", "rpc"])

    stdout_text = stdout.getvalue()
    responses = [
        json.loads(line)
        for line in stdout_text.splitlines()
        if line.strip()
    ]
    return exit_code, responses, stdout_text, stderr.getvalue()


def _write_tiny_wav(path: Path, *, channels: int = 1, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 8 * channels)


def _init_project(base: Path) -> tuple[Path, Path]:
    stems_root = base / "stems_root"
    _write_tiny_wav(stems_root / "stems" / "kick.wav")
    _write_tiny_wav(stems_root / "stems" / "snare.wav")

    project_dir = base / "project"
    exit_code, _, stderr = _run_main(
        [
            "project",
            "init",
            "--stems-root",
            str(stems_root),
            "--out-dir",
            str(project_dir),
        ]
    )
    assert exit_code == 0, f"project init failed: {stderr}"

    exit_code, _, stderr = _run_main(
        [
            "project",
            "render-init",
            str(project_dir),
            "--target-layout",
            "LAYOUT.2_0",
        ]
    )
    assert exit_code == 0, f"project render-init failed: {stderr}"
    return project_dir, stems_root


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil

    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestGuiRpcStableErrors(unittest.TestCase):
    def test_unknown_method_is_refused_with_stable_error(self) -> None:
        request = {
            "id": "req-unknown",
            "method": "project.destroy_everything",
            "params": {},
        }
        exit_a, responses_a, stdout_a, stderr_a = _run_rpc([request])
        exit_b, responses_b, stdout_b, stderr_b = _run_rpc([request])

        self.assertEqual(exit_a, 0)
        self.assertEqual(exit_b, 0)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(responses_a, responses_b)

        self.assertEqual(len(responses_a), 1)
        response = responses_a[0]
        self.assertEqual(response["id"], "req-unknown")
        self.assertFalse(response["ok"])
        self.assertEqual(
            response["error"],
            {
                "code": "RPC.UNKNOWN_METHOD",
                "message": "Unknown method: project.destroy_everything",
            },
        )

    def test_env_doctor_runtime_error_is_method_failed(self) -> None:
        with patch(
            "mmo.cli_commands._gui_rpc.build_env_doctor_report",
            side_effect=RuntimeError("MMO temporary directory is unavailable."),
        ):
            exit_code, responses, _, stderr = _run_rpc(
                [
                    {
                        "id": "req-env",
                        "method": "env.doctor",
                        "params": {},
                    }
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(len(responses), 1)
        self.assertEqual(
            responses[0],
            {
                "error": {
                    "code": "RPC.METHOD_FAILED",
                    "message": "MMO temporary directory is unavailable.",
                },
                "id": "req-env",
                "ok": False,
            },
        )


class TestGuiRpcDiscover(unittest.TestCase):
    def test_rpc_discover_is_byte_identical_across_runs(self) -> None:
        request = {
            "id": "req-discover",
            "method": "rpc.discover",
            "params": {},
        }
        exit_a, responses_a, stdout_a, stderr_a = _run_rpc([request])
        exit_b, responses_b, stdout_b, stderr_b = _run_rpc([request])

        self.assertEqual(exit_a, 0)
        self.assertEqual(exit_b, 0)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(responses_a, responses_b)
        self.assertNotIn("\\", stdout_a)

        self.assertEqual(len(responses_a), 1)
        response = responses_a[0]
        self.assertEqual(response["id"], "req-discover")
        self.assertTrue(response["ok"])

        result = response["result"]
        self.assertEqual(result["rpc_version"], "1")
        expected_build = (
            _MMO_VERSION.strip()
            if isinstance(_MMO_VERSION, str) and _MMO_VERSION.strip()
            else "unknown"
        )
        self.assertEqual(result["server_build"], expected_build)

    def test_rpc_discover_methods_match_allowlist_sorted(self) -> None:
        exit_code, responses, _, stderr = _run_rpc(
            [
                {
                    "id": "req-discover-methods",
                    "method": "rpc.discover",
                    "params": {},
                }
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(len(responses), 1)

        response = responses[0]
        self.assertTrue(response["ok"])
        result = response["result"]

        methods = result["methods"]
        expected_methods = sorted(_gui_rpc._RPC_METHOD_HANDLERS.keys())
        self.assertEqual(methods, expected_methods)

        method_details = result["method_details"]
        self.assertEqual(sorted(method_details.keys()), methods)
        for method_name in methods:
            self.assertIn(method_name, method_details)
            details = method_details[method_name]
            self.assertIn("params_schema", details)
            self.assertIn("result_shape", details)
            params_schema = details["params_schema"]
            self.assertIn("required", params_schema)
            self.assertIn("optional", params_schema)
            self.assertIn("examples", params_schema)

    def test_unknown_method_behavior_unchanged_after_rpc_discover(self) -> None:
        requests = [
            {
                "id": "req-discover",
                "method": "rpc.discover",
                "params": {},
            },
            {
                "id": "req-unknown-after-discover",
                "method": "project.destroy_everything",
                "params": {},
            },
        ]
        exit_a, responses_a, stdout_a, stderr_a = _run_rpc(requests)
        exit_b, responses_b, stdout_b, stderr_b = _run_rpc(requests)

        self.assertEqual(exit_a, 0)
        self.assertEqual(exit_b, 0)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(responses_a, responses_b)

        self.assertEqual(len(responses_a), 2)
        self.assertTrue(responses_a[0]["ok"])
        self.assertEqual(
            responses_a[1],
            {
                "error": {
                    "code": "RPC.UNKNOWN_METHOD",
                    "message": "Unknown method: project.destroy_everything",
                },
                "id": "req-unknown-after-discover",
                "ok": False,
            },
        )


class TestGuiRpcDeterminism(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir, cls.stems_root = _init_project(_SANDBOX / "determinism")

    def _requests(self) -> list[dict[str, object]]:
        return [
            {
                "id": "1",
                "method": "env.doctor",
                "params": {},
            },
            {
                "id": "2",
                "method": "project.build_gui",
                "params": {
                    "project_dir": str(self.project_dir),
                    "pack_out": str(self.project_dir / "project_gui_rpc.zip"),
                    "scan": True,
                    "scan_stems": str(self.stems_root),
                    "scan_out": str(self.project_dir / "report.json"),
                    "force": True,
                    "event_log": True,
                    "event_log_force": True,
                },
            },
            {
                "id": "3",
                "method": "project.show",
                "params": {
                    "project_dir": str(self.project_dir),
                },
            },
            {
                "id": "4",
                "method": "project.validate",
                "params": {
                    "project_dir": str(self.project_dir),
                },
            },
            {
                "id": "5",
                "method": "project.pack",
                "params": {
                    "project_dir": str(self.project_dir),
                    "out": str(self.project_dir / "project_pack_rpc.zip"),
                    "force": True,
                },
            },
        ]

    def test_five_supported_methods_are_deterministic(self) -> None:
        exit_a, responses_a, stdout_a, stderr_a = _run_rpc(self._requests())
        exit_b, responses_b, stdout_b, stderr_b = _run_rpc(self._requests())

        self.assertEqual(exit_a, 0)
        self.assertEqual(exit_b, 0)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(responses_a, responses_b)
        self.assertNotIn("\\", stdout_a)

        self.assertEqual(len(responses_a), 5)
        by_id = {item["id"]: item for item in responses_a}
        for request_id in ("1", "2", "3", "4", "5"):
            self.assertIn(request_id, by_id)
            self.assertTrue(by_id[request_id]["ok"])

        env_result = by_id["1"]["result"]
        self.assertIn("checks", env_result)
        self.assertIn("paths", env_result)

        project_show_result = by_id["3"]["result"]
        self.assertEqual(
            project_show_result["project_dir"],
            self.project_dir.resolve().as_posix(),
        )

        validate_result = by_id["4"]["result"]
        self.assertIn("ok", validate_result)
        self.assertIn("summary", validate_result)

        build_gui_result = by_id["2"]["result"]
        self.assertTrue(build_gui_result["ok"])
        self.assertEqual(
            build_gui_result["pack_out"],
            (self.project_dir / "project_gui_rpc.zip").resolve().as_posix(),
        )

        pack_result = by_id["5"]["result"]
        self.assertTrue(pack_result["ok"])
        self.assertEqual(
            pack_result["out"],
            (self.project_dir / "project_pack_rpc.zip").resolve().as_posix(),
        )


if __name__ == "__main__":
    unittest.main()
