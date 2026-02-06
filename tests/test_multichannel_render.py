import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema

from mmo.core.pipeline import PluginEntry, run_renderers
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.plugins.interfaces import PluginCapabilities


def _py_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    src_root = str(repo_root / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_root if not existing else f"{src_root}{os.pathsep}{existing}"
    return env


def _render_manifest(report_path: Path, out_manifest_path: Path, out_dir: Path, repo_root: Path) -> dict:
    subprocess.run(
        [
            os.fspath(os.getenv("PYTHON", "") or sys.executable),
            "-m",
            "mmo",
            "render",
            "--report",
            os.fspath(report_path),
            "--plugins",
            os.fspath(repo_root / "plugins"),
            "--out-manifest",
            os.fspath(out_manifest_path),
            "--out-dir",
            os.fspath(out_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_py_env(repo_root),
    )
    return json.loads(out_manifest_path.read_text(encoding="utf-8"))


def _gain_trim_manifest(manifest: dict) -> dict:
    renderer_manifests = manifest.get("renderer_manifests", [])
    if not isinstance(renderer_manifests, list):
        return {}
    for item in renderer_manifests:
        if (
            isinstance(item, dict)
            and item.get("renderer_id") == "PLUGIN.RENDERER.GAIN_TRIM"
        ):
            return item
    return {}


def _make_six_channel_flac(ffmpeg_cmd: list[str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = list(ffmpeg_cmd) + [
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=220:duration=0.25:sample_rate=48000",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=330:duration=0.25:sample_rate=48000",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=0.25:sample_rate=48000",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=550:duration=0.25:sample_rate=48000",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=660:duration=0.25:sample_rate=48000",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=770:duration=0.25:sample_rate=48000",
        "-filter_complex",
        "[0:a][1:a][2:a][3:a][4:a][5:a]join=inputs=6:channel_layout=5.1[aout]",
        "-map",
        "[aout]",
        "-c:a",
        "flac",
        os.fspath(output_path),
    ]
    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )


class _ExplodingRenderer:
    def __init__(self) -> None:
        self.called = False

    def render(self, session, recommendations, output_dir=None):  # type: ignore[no-untyped-def]
        self.called = True
        raise AssertionError("renderer should not be called when max_channels is exceeded")


class TestMultichannelRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffmpeg_cmd = resolve_ffmpeg_cmd()

    def test_render_six_channel_flac_reports_channel_count(self) -> None:
        if self.ffmpeg_cmd is None:
            raise unittest.SkipTest("ffmpeg not available")

        repo_root = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (repo_root / "schemas" / "render_manifest.schema.json").read_text(encoding="utf-8")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"
            out_dir = temp_path / "renders"
            source_flac = stems_dir / "surround.flac"

            _make_six_channel_flac(list(self.ffmpeg_cmd), source_flac)

            report = {
                "schema_version": "0.1.0",
                "report_id": "REPORT.RENDER.MULTICHANNEL.6CH.001",
                "project_id": "PROJECT.TEST",
                "generated_at": "2000-01-01T00:00:00Z",
                "engine_version": "0.1.0",
                "ontology_version": "0.1.0",
                "session": {
                    "stems_dir": stems_dir.resolve().as_posix(),
                    "stems": [
                        {
                            "stem_id": "surround",
                            "file_path": "surround.flac",
                            "channel_count": 6,
                            "sample_rate_hz": 48000,
                            "bits_per_sample": 16,
                        }
                    ],
                },
                "issues": [],
                "recommendations": [
                    {
                        "recommendation_id": "REC.RENDER.GAIN.MULTICHANNEL.001",
                        "action_id": "ACTION.UTILITY.GAIN",
                        "risk": "low",
                        "requires_approval": False,
                        "eligible_render": True,
                        "target": {"scope": "stem", "stem_id": "surround"},
                        "params": [{"param_id": "PARAM.GAIN.DB", "value": -4.0}],
                    }
                ],
            }
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            manifest = _render_manifest(report_path, out_manifest_path, out_dir, repo_root)
            jsonschema.Draft202012Validator(schema).validate(manifest)

            gain_manifest = _gain_trim_manifest(manifest)
            outputs = gain_manifest.get("outputs", [])
            self.assertEqual(len(outputs), 1)
            output = outputs[0]

            output_path = out_dir / Path(output["file_path"])
            self.assertTrue(output_path.exists())
            self.assertEqual(output.get("channel_count"), 6)
            self.assertEqual(output.get("sample_rate_hz"), 48000)

            with wave.open(str(output_path), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 6)
                self.assertEqual(handle.getframerate(), 48000)

    def test_run_renderers_skips_when_plugin_channel_limit_exceeded(self) -> None:
        renderer = _ExplodingRenderer()
        plugins = [
            PluginEntry(
                plugin_id="PLUGIN.RENDERER.EXPLODING",
                plugin_type="renderer",
                version="0.1.0",
                capabilities=PluginCapabilities(max_channels=32),
                instance=renderer,
                manifest_path=Path("plugins/renderers/exploding.plugin.yaml"),
                manifest={},
            )
        ]
        report = {
            "session": {
                "stems": [
                    {
                        "stem_id": "surround",
                        "file_path": "surround.wav",
                        "channel_count": 64,
                    }
                ]
            },
            "recommendations": [
                {
                    "recommendation_id": "REC.CH64.B",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "eligible_render": True,
                    "target": {"scope": "stem", "stem_id": "surround"},
                },
                {
                    "recommendation_id": "REC.CH64.A",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "eligible_render": True,
                    "target": {"scope": "stem", "stem_id": "surround"},
                },
            ],
        }

        manifests = run_renderers(report, plugins)
        self.assertFalse(renderer.called)
        self.assertEqual(len(manifests), 1)

        repo_root = Path(__file__).resolve().parents[1]
        render_schema = json.loads(
            (repo_root / "schemas" / "render_manifest.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(render_schema).validate(
            {
                "schema_version": "0.1.0",
                "report_id": "REPORT.CHANNEL.LIMIT",
                "renderer_manifests": manifests,
            }
        )

        manifest = manifests[0]
        self.assertEqual(manifest.get("renderer_id"), "PLUGIN.RENDERER.EXPLODING")
        self.assertEqual(manifest.get("outputs"), [])
        skipped = manifest.get("skipped")
        self.assertIsInstance(skipped, list)
        if not isinstance(skipped, list):
            return

        self.assertEqual(
            [item.get("recommendation_id") for item in skipped if isinstance(item, dict)],
            ["REC.CH64.A", "REC.CH64.B"],
        )
        for item in skipped:
            if not isinstance(item, dict):
                continue
            self.assertEqual(item.get("reason"), "plugin_channel_limit")
            self.assertEqual(item.get("gate_summary"), "")
            details = item.get("details")
            self.assertIsInstance(details, dict)
            if not isinstance(details, dict):
                continue
            self.assertEqual(details.get("plugin_id"), "PLUGIN.RENDERER.EXPLODING")
            self.assertEqual(details.get("required_channels"), 64)
            self.assertEqual(details.get("max_channels"), 32)


if __name__ == "__main__":
    unittest.main()
