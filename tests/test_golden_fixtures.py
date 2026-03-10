"""Cross-platform golden fixtures for classify -> bus-plan -> scene -> safe-render."""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import shutil
import unittest
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mmo.cli import main
from mmo.dsp.meters import iter_wav_float64_samples

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional local dependency
    np = None

try:
    from mmo.dsp.meters_truth import compute_lufs_integrated_float64
except (ImportError, ValueError):  # pragma: no cover - optional local dependency
    compute_lufs_integrated_float64 = None

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES_ROOT = _REPO_ROOT / "fixtures" / "golden"
_PLUGINS_DIR = _REPO_ROOT / "plugins"
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_golden_fixtures" / str(os.getpid())
_PEAK_TOLERANCE_DB = 0.1
_RMS_TOLERANCE_DB = 0.1
_LUFS_TOLERANCE = 0.2


@dataclass(frozen=True)
class _FixtureSpec:
    fixture_id: str
    targets: tuple[str, ...]
    scene_template_id: str = "TEMPLATE.SEATING.ORCHESTRA_AUDIENCE"
    reference_target: str | None = None

    @property
    def fixture_root(self) -> Path:
        return _FIXTURES_ROOT / self.fixture_id

    @property
    def expected_dir(self) -> Path:
        return self.fixture_root / "expected"

    @property
    def render_targets(self) -> tuple[str, ...]:
        if self.reference_target and self.reference_target not in self.targets:
            return (self.reference_target, *self.targets)
        return self.targets


_FIXTURE_SPECS: tuple[_FixtureSpec, ...] = (
    _FixtureSpec(
        fixture_id="golden_small_stereo",
        targets=("LAYOUT.2_0",),
    ),
    _FixtureSpec(
        fixture_id="golden_small_surround",
        targets=("LAYOUT.5_1", "LAYOUT.7_1"),
        reference_target="LAYOUT.2_0",
    ),
    _FixtureSpec(
        fixture_id="golden_small_immersive",
        targets=("LAYOUT.7_1_4", "LAYOUT.9_1_6"),
        reference_target="LAYOUT.2_0",
    ),
)


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _target_slug(layout_id: str) -> str:
    return layout_id.replace(".", "_")


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_placement_only_plugins_dir(path: Path) -> Path:
    renderers_dir = path / "renderers"
    renderers_dir.mkdir(parents=True, exist_ok=True)
    source_manifest = _PLUGINS_DIR / "renderers" / "placement_mixdown_renderer.plugin.yaml"
    renderers_dir.joinpath(source_manifest.name).write_text(
        source_manifest.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _canonical_sha256(payload: Any) -> str:
    import hashlib

    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _stable_sort_rows(rows: list[Any], *, parent_key: str) -> list[Any]:
    sort_keys_by_parent = {
        "renderer_manifests": ("renderer_id",),
        "outputs": ("layout_id", "file_path", "output_id"),
        "skipped": ("recommendation_id", "action_id", "reason"),
        "qa_issues": ("severity", "issue_id", "metric"),
        "assignments": ("file_path", "stem_id", "bus_id"),
        "buses": ("bus_id",),
        "objects": ("object_id",),
        "beds": ("bed_id",),
    }
    sort_keys = sort_keys_by_parent.get(parent_key)
    if not sort_keys or not all(isinstance(item, dict) for item in rows):
        return rows
    return sorted(
        rows,
        key=lambda item: tuple(_coerce_str(item.get(key)).strip() for key in sort_keys),
    )


def normalize_artifacts(
    payload: Any,
    *,
    replacements: dict[str, str],
    parent_key: str = "",
) -> Any:
    """Normalize paths and list ordering for stable golden comparisons."""
    if isinstance(payload, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(payload.keys()):
            value = payload[key]
            normalized[key] = normalize_artifacts(
                value,
                replacements=replacements,
                parent_key=key,
            )
        return normalized

    if isinstance(payload, list):
        normalized_rows = [
            normalize_artifacts(item, replacements=replacements, parent_key=parent_key)
            for item in payload
        ]
        return _stable_sort_rows(normalized_rows, parent_key=parent_key)

    if isinstance(payload, str):
        text = payload.replace("\\", "/")
        for source, target in sorted(replacements.items(), key=lambda item: -len(item[0])):
            text = text.replace(source, target)
        if parent_key in {"bus_plan_ref", "stems_map_ref"}:
            return Path(text).name
        return text

    return payload


def _manifest_invariants(
    manifest: dict[str, Any],
    *,
    replacements: dict[str, str],
) -> dict[str, Any]:
    renderer_manifests: list[dict[str, Any]] = []
    for manifest_row in manifest.get("renderer_manifests", []):
        if not isinstance(manifest_row, dict):
            continue
        outputs: list[dict[str, Any]] = []
        for output in manifest_row.get("outputs", []):
            if not isinstance(output, dict):
                continue
            metadata = output.get("metadata")
            metadata_dict = metadata if isinstance(metadata, dict) else {}
            trace_metadata = metadata_dict.get("trace_metadata")
            trace_dict = trace_metadata if isinstance(trace_metadata, dict) else {}
            outputs.append(
                {
                    "file_path": output.get("file_path"),
                    "layout_id": output.get("layout_id"),
                    "format": output.get("format"),
                    "sample_rate_hz": output.get("sample_rate_hz"),
                    "bit_depth": output.get("bit_depth"),
                    "channel_count": output.get("channel_count"),
                    "metadata": {
                        "artifact_role": metadata_dict.get("artifact_role"),
                        "applied_policy_id": metadata_dict.get("applied_policy_id"),
                        "channel_order": metadata_dict.get("channel_order"),
                        "manifest_tags": metadata_dict.get("manifest_tags"),
                        "trace_metadata": {
                            "scene_sha256": trace_dict.get("scene_sha256"),
                            "render_contract_version": trace_dict.get("render_contract_version"),
                            "downmix_policy_version": trace_dict.get("downmix_policy_version"),
                            "layout_id": trace_dict.get("layout_id"),
                            "profile_id": trace_dict.get("profile_id"),
                            "export_profile_id": trace_dict.get("export_profile_id"),
                            "seed": trace_dict.get("seed"),
                        },
                    },
                }
            )
        skipped_rows: list[dict[str, Any]] = []
        for skipped in manifest_row.get("skipped", []):
            if not isinstance(skipped, dict):
                continue
            skipped_rows.append(
                {
                    "recommendation_id": skipped.get("recommendation_id"),
                    "action_id": skipped.get("action_id"),
                    "reason": skipped.get("reason"),
                    "gate_summary": skipped.get("gate_summary"),
                }
            )
        renderer_manifests.append(
            {
                "renderer_id": manifest_row.get("renderer_id"),
                "outputs": outputs,
                "skipped": skipped_rows,
            }
        )
    return normalize_artifacts(
        {
            "schema_version": manifest.get("schema_version"),
            "report_id": manifest.get("report_id"),
            "renderer_manifests": renderer_manifests,
        },
        replacements=replacements,
    )


def _receipt_invariants(
    receipt: dict[str, Any],
    *,
    replacements: dict[str, str],
) -> dict[str, Any]:
    fallback_final = receipt.get("fallback_final")
    fallback_dict = fallback_final if isinstance(fallback_final, dict) else {}
    return normalize_artifacts(
        {
            "schema_version": receipt.get("schema_version"),
            "context": receipt.get("context"),
            "status": receipt.get("status"),
            "dry_run": receipt.get("dry_run"),
            "target": receipt.get("target"),
            "profile_id": receipt.get("profile_id"),
            "scene_mode": receipt.get("scene_mode"),
            "scene_source_path": receipt.get("scene_source_path"),
            "scene_locks_source_path": receipt.get("scene_locks_source_path"),
            "approved_by": receipt.get("approved_by"),
            "recommendations_summary": receipt.get("recommendations_summary"),
            "qa_issues": [
                {
                    "issue_id": issue.get("issue_id"),
                    "severity": issue.get("severity"),
                }
                for issue in receipt.get("qa_issues", [])
                if isinstance(issue, dict)
            ],
            "fallback_attempts": [
                {
                    "layout_id": attempt.get("layout_id"),
                    "step_id": attempt.get("step_id"),
                    "result": attempt.get("result"),
                }
                for attempt in receipt.get("fallback_attempts", [])
                if isinstance(attempt, dict)
            ],
            "fallback_final": {
                "applied_steps": fallback_dict.get("applied_steps"),
                "final_outcome": fallback_dict.get("final_outcome"),
                "safety_collapse_applied": fallback_dict.get("safety_collapse_applied"),
                "passed_layout_ids": fallback_dict.get("passed_layout_ids"),
                "failed_layout_ids": fallback_dict.get("failed_layout_ids"),
            },
            "notes": receipt.get("notes"),
        },
        replacements=replacements,
    )


def _build_report_from_stems_map(*, fixture_root: Path, stems_map_path: Path, report_path: Path) -> None:
    stems_map_payload = json.loads(stems_map_path.read_text(encoding="utf-8"))
    assignments = stems_map_payload.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("stems_map assignments must be a list")

    stems: list[dict[str, Any]] = []
    for row in sorted(
        (item for item in assignments if isinstance(item, dict)),
        key=lambda item: _coerce_str(item.get("rel_path")),
    ):
        stem_id = _coerce_str(row.get("file_id")).strip()
        rel_path = _coerce_str(row.get("rel_path")).strip()
        if not stem_id or not rel_path:
            continue
        source_path = fixture_root / rel_path
        with wave.open(str(source_path), "rb") as handle:
            channel_count = int(handle.getnchannels())
            sample_rate_hz = int(handle.getframerate())
            frame_count = int(handle.getnframes())

        stems.append(
            {
                "stem_id": stem_id,
                "file_path": rel_path,
                "channel_count": channel_count,
                "sample_rate_hz": sample_rate_hz,
                "frame_count": frame_count,
                "measurements": [
                    {
                        "evidence_id": "EVID.METER.CLIP_SAMPLE_COUNT",
                        "unit_id": "UNIT.COUNT",
                        "value": 0,
                    },
                    {
                        "evidence_id": "EVID.METER.PEAK_DBFS",
                        "unit_id": "UNIT.DBFS",
                        "value": -9.0,
                    },
                ],
            }
        )

    report_payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "report_id": f"REPORT.GOLDEN.{fixture_root.name.upper()}",
        "project_id": f"PROJECT.GOLDEN.{fixture_root.name.upper()}",
        "generated_at": "2026-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {
            "stems_dir": fixture_root.resolve().as_posix(),
            "stems": stems,
        },
        "issues": [],
        "recommendations": [],
        "features": {},
    }
    _write_json(report_path, report_payload)


def _find_target_master_output(
    manifest: dict[str, Any],
    *,
    target_layout_id: str,
) -> dict[str, Any]:
    for renderer_manifest in manifest.get("renderer_manifests", []):
        if not isinstance(renderer_manifest, dict):
            continue
        outputs = renderer_manifest.get("outputs")
        if not isinstance(outputs, list):
            continue
        for row in outputs:
            if not isinstance(row, dict):
                continue
            if _coerce_str(row.get("layout_id")).strip() != target_layout_id:
                continue
            if Path(_coerce_str(row.get("file_path")).strip()).as_posix() != "master.wav":
                continue
            return row
    raise AssertionError(f"missing master output for {target_layout_id}")


def _round_metric(value: float | None, *, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def _dbfs_peak(samples: list[float]) -> float | None:
    if not samples:
        return None
    peak = max(abs(sample) for sample in samples)
    if peak <= 0.0:
        return None
    return 20.0 * math.log10(peak)


def _dbfs_rms(samples: list[float]) -> float | None:
    if not samples:
        return None
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    if mean_square <= 0.0:
        return None
    rms = math.sqrt(mean_square)
    if rms <= 0.0:
        return None
    return 20.0 * math.log10(rms)


def _lufs_integrated(samples: list[float], *, sample_rate_hz: int) -> float | None:
    if np is None or compute_lufs_integrated_float64 is None or not samples:
        return None
    frames = np.asarray(samples, dtype=np.float64).reshape(-1, 1)
    value = compute_lufs_integrated_float64(
        frames,
        sample_rate_hz,
        1,
        channel_mask=None,
        channel_layout=None,
    )
    if not math.isfinite(float(value)):
        return None
    return float(value)


def _measure_per_channel_metrics(
    *,
    master_path: Path,
    channel_order: list[str],
    sample_rate_hz: int,
) -> list[dict[str, Any]]:
    channel_count = len(channel_order)
    channels: list[list[float]] = [[] for _ in range(channel_count)]
    for chunk in iter_wav_float64_samples(master_path, error_context="golden fixture meters"):
        if channel_count <= 0:
            break
        for index, sample in enumerate(chunk):
            channels[index % channel_count].append(sample)

    metrics_rows: list[dict[str, Any]] = []
    for speaker_id, samples in zip(channel_order, channels):
        metrics_rows.append(
            {
                "speaker_id": speaker_id,
                "peak_dbfs": _round_metric(_dbfs_peak(samples)),
                "rms_dbfs": _round_metric(_dbfs_rms(samples)),
                "integrated_lufs": _round_metric(
                    _lufs_integrated(samples, sample_rate_hz=sample_rate_hz)
                ),
            }
        )
    return metrics_rows


def _extract_qa_issue_pairs(receipt: dict[str, Any]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for issue in receipt.get("qa_issues", []):
        if not isinstance(issue, dict):
            continue
        issue_id = _coerce_str(issue.get("issue_id")).strip()
        severity = _coerce_str(issue.get("severity")).strip()
        if not issue_id or not severity:
            continue
        pairs.append({"issue_id": issue_id, "severity": severity})
    return pairs


def _summarize_similarity_gate(result: dict[str, Any]) -> dict[str, Any]:
    attempts_summary: list[dict[str, Any]] = []
    for attempt in result.get("attempts", []):
        if not isinstance(attempt, dict):
            continue
        attempts_summary.append(
            {
                "passed": bool(attempt.get("passed")),
                "risk_level": _coerce_str(attempt.get("risk_level")).strip() or "high",
                "matrix_id": _coerce_str(attempt.get("matrix_id")).strip(),
            }
        )
    fallback_final = result.get("fallback_final")
    fallback_dict = fallback_final if isinstance(fallback_final, dict) else {}
    return {
        "gate_id": _coerce_str(result.get("gate_id")).strip(),
        "gate_version": _coerce_str(result.get("gate_version")).strip(),
        "passed": bool(result.get("passed")),
        "fallback_applied": bool(result.get("fallback_applied")),
        "risk_level": _coerce_str(result.get("risk_level")).strip() or "high",
        "matrix_id": _coerce_str(result.get("matrix_id")).strip(),
        "fallback_final_outcome": _coerce_str(fallback_dict.get("final_outcome")).strip(),
        "safety_collapse_applied": bool(fallback_dict.get("safety_collapse_applied")),
        "attempts": attempts_summary,
    }


def _fixture_run_root(spec: _FixtureSpec) -> Path:
    return _SANDBOX / spec.fixture_id


def _fixture_replacements(*, fixture_root: Path, run_root: Path) -> dict[str, str]:
    replacements = {
        _REPO_ROOT.resolve().as_posix(): "<REPO_ROOT>",
        fixture_root.resolve().as_posix(): "<FIXTURE_ROOT>",
        run_root.resolve().as_posix(): "<ROOT>",
    }
    return replacements


def _run_fixture(spec: _FixtureSpec) -> dict[str, Any]:
    run_root = _fixture_run_root(spec)
    if run_root.exists():
        shutil.rmtree(run_root, ignore_errors=True)
    run_root.mkdir(parents=True, exist_ok=True)

    stems_map_path = run_root / "stems_map.json"
    bus_plan_path = run_root / "bus_plan.json"
    scene_raw_path = run_root / "scene.raw.json"
    scene_path = run_root / "scene.json"
    report_path = run_root / "report.json"
    renders_dir = run_root / "renders"
    receipt_out_path = run_root / "receipt.json"
    plugins_dir = _write_placement_only_plugins_dir(run_root / "plugins")

    exit_code, _stdout, stderr = _run_main(
        ["stems", "classify", "--root", str(spec.fixture_root), "--out", str(stems_map_path)]
    )
    if exit_code != 0:
        raise AssertionError(f"stems classify failed for {spec.fixture_id}:\n{stderr}")

    exit_code, _stdout, stderr = _run_main(
        ["stems", "bus-plan", "--map", str(stems_map_path), "--out", str(bus_plan_path)]
    )
    if exit_code != 0:
        raise AssertionError(f"stems bus-plan failed for {spec.fixture_id}:\n{stderr}")

    exit_code, _stdout, stderr = _run_main(
        [
            "scene",
            "build",
            "--map",
            str(stems_map_path),
            "--bus",
            str(bus_plan_path),
            "--profile",
            "PROFILE.ASSIST",
            "--out",
            str(scene_raw_path),
        ]
    )
    if exit_code != 0:
        raise AssertionError(f"scene build failed for {spec.fixture_id}:\n{stderr}")

    exit_code, _stdout, stderr = _run_main(
        [
            "scene",
            "template",
            "apply",
            spec.scene_template_id,
            "--scene",
            str(scene_raw_path),
            "--out",
            str(scene_path),
        ]
    )
    if exit_code != 0:
        raise AssertionError(f"scene template apply failed for {spec.fixture_id}:\n{stderr}")

    _build_report_from_stems_map(
        fixture_root=spec.fixture_root,
        stems_map_path=stems_map_path,
        report_path=report_path,
    )

    exit_code, _stdout, stderr = _run_main(
        [
            "safe-render",
            "--report",
            str(report_path),
            "--plugins",
            str(plugins_dir),
            "--scene",
            str(scene_path),
            "--render-many",
            "--render-many-targets",
            ",".join(spec.render_targets),
            "--out-dir",
            str(renders_dir),
            "--receipt-out",
            str(receipt_out_path),
            "--export-layouts",
            ",".join(spec.render_targets),
            "--force",
        ]
    )
    if exit_code not in (0, 1):
        raise AssertionError(f"safe-render failed for {spec.fixture_id}:\n{stderr}")
    safe_render_exit_code = exit_code
    safe_render_stderr = stderr

    replacements = _fixture_replacements(fixture_root=spec.fixture_root, run_root=run_root)
    bus_plan_payload = json.loads(bus_plan_path.read_text(encoding="utf-8"))
    scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))

    target_metrics: dict[str, Any] = {}
    target_gates: dict[str, Any] = {}
    reference_master_path = None
    if spec.reference_target:
        reference_master_path = renders_dir / _target_slug(spec.reference_target) / "master.wav"
        if not reference_master_path.is_file():
            raise AssertionError(
                "missing stereo reference master for "
                f"{spec.fixture_id}: {reference_master_path}\n"
                f"safe-render exit code={safe_render_exit_code}\n{safe_render_stderr}"
            )

    for layout_id in spec.targets:
        slug = _target_slug(layout_id)
        target_dir = renders_dir / slug
        manifest_path = target_dir / "render_manifest.json"
        receipt_path = run_root / f"receipt.{slug}.json"
        master_path = target_dir / "master.wav"

        if not manifest_path.is_file():
            raise AssertionError(
                f"missing render manifest for {layout_id}: {manifest_path}\n"
                f"safe-render exit code={safe_render_exit_code}\n{safe_render_stderr}"
            )
        if not receipt_path.is_file():
            raise AssertionError(
                f"missing receipt for {layout_id}: {receipt_path}\n"
                f"safe-render exit code={safe_render_exit_code}\n{safe_render_stderr}"
            )
        if not master_path.is_file():
            raise AssertionError(
                f"missing master output for {layout_id}: {master_path}\n"
                f"safe-render exit code={safe_render_exit_code}\n{safe_render_stderr}"
            )

        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        master_output = _find_target_master_output(manifest_payload, target_layout_id=layout_id)
        metadata = master_output.get("metadata")
        metadata_dict = metadata if isinstance(metadata, dict) else {}
        trace_metadata = metadata_dict.get("trace_metadata")
        trace_dict = trace_metadata if isinstance(trace_metadata, dict) else {}

        channel_order = metadata_dict.get("channel_order")
        if not isinstance(channel_order, list) or not channel_order:
            raise AssertionError(f"missing channel_order for {layout_id}")
        sample_rate_hz = int(master_output.get("sample_rate_hz") or 0)
        if sample_rate_hz <= 0:
            raise AssertionError(f"invalid sample_rate_hz for {layout_id}")

        target_metrics[layout_id] = {
            "normalized_render_manifest_sha256": _canonical_sha256(
                _manifest_invariants(manifest_payload, replacements=replacements)
            ),
            "normalized_receipt_sha256": _canonical_sha256(
                _receipt_invariants(receipt_payload, replacements=replacements)
            ),
            "channel_count": int(master_output.get("channel_count") or 0),
            "channel_order": list(channel_order),
            "scene_sha256": _coerce_str(trace_dict.get("scene_sha256")).strip(),
            "downmix_policy_version": _coerce_str(
                trace_dict.get("downmix_policy_version")
            ).strip(),
            "render_contract_version": _coerce_str(
                trace_dict.get("render_contract_version")
            ).strip(),
            "per_channel_metrics": _measure_per_channel_metrics(
                master_path=master_path,
                channel_order=[_coerce_str(item).strip() for item in channel_order],
                sample_rate_hz=sample_rate_hz,
            ),
        }

        gate_payload: dict[str, Any] = {
            "qa_issues": _extract_qa_issue_pairs(receipt_payload),
            "downmix_similarity": None,
        }
        if layout_id != spec.reference_target:
            similarity_payload = metadata_dict.get("downmix_similarity_qa")
            if isinstance(similarity_payload, dict):
                gate_payload["downmix_similarity"] = _summarize_similarity_gate(
                    similarity_payload
                )
        target_gates[layout_id] = gate_payload

    return {
        "fixture_id": spec.fixture_id,
        "expected_bus_plan": normalize_artifacts(bus_plan_payload, replacements=replacements),
        "expected_scene": normalize_artifacts(scene_payload, replacements=replacements),
        "expected_metrics": {
            "fixture_id": spec.fixture_id,
            "scene_template_id": spec.scene_template_id,
            "tolerances": {
                "peak_dbfs": _PEAK_TOLERANCE_DB,
                "rms_dbfs": _RMS_TOLERANCE_DB,
                "integrated_lufs": _LUFS_TOLERANCE,
            },
            "targets": target_metrics,
        },
        "expected_gate_outcomes": {
            "fixture_id": spec.fixture_id,
            "targets": target_gates,
        },
    }


def write_expected_snapshots() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)
    for spec in _FIXTURE_SPECS:
        result = _run_fixture(spec)
        spec.expected_dir.mkdir(parents=True, exist_ok=True)
        _write_json(spec.expected_dir / "expected_bus_plan.json", result["expected_bus_plan"])
        _write_json(spec.expected_dir / "expected_scene.json", result["expected_scene"])
        _write_json(spec.expected_dir / "expected_metrics.json", result["expected_metrics"])
        _write_json(
            spec.expected_dir / "expected_gate_outcomes.json",
            result["expected_gate_outcomes"],
        )


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestGoldenFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.actual: dict[str, dict[str, Any]] = {}
        for spec in _FIXTURE_SPECS:
            cls.actual[spec.fixture_id] = _run_fixture(spec)

    def _expected_payload(self, spec: _FixtureSpec, file_name: str) -> dict[str, Any]:
        path = spec.expected_dir / file_name
        if not path.is_file():
            raise AssertionError(
                f"missing expected snapshot for {spec.fixture_id}: {path}"
            )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_bus_plan_snapshots_match(self) -> None:
        for spec in _FIXTURE_SPECS:
            with self.subTest(fixture=spec.fixture_id):
                actual = self.actual[spec.fixture_id]["expected_bus_plan"]
                expected = self._expected_payload(spec, "expected_bus_plan.json")
                self.assertEqual(actual, expected)

    def test_scene_snapshots_match(self) -> None:
        for spec in _FIXTURE_SPECS:
            with self.subTest(fixture=spec.fixture_id):
                actual = self.actual[spec.fixture_id]["expected_scene"]
                expected = self._expected_payload(spec, "expected_scene.json")
                self.assertEqual(actual, expected)

    def test_metrics_snapshots_match(self) -> None:
        for spec in _FIXTURE_SPECS:
            with self.subTest(fixture=spec.fixture_id):
                actual = self.actual[spec.fixture_id]["expected_metrics"]
                expected = self._expected_payload(spec, "expected_metrics.json")
                self.assertEqual(actual.get("fixture_id"), expected.get("fixture_id"))
                self.assertEqual(
                    actual.get("scene_template_id"),
                    expected.get("scene_template_id"),
                )
                self.assertEqual(actual.get("targets").keys(), expected.get("targets").keys())

                tolerances = expected.get("tolerances", {})
                peak_tol = float(tolerances.get("peak_dbfs", _PEAK_TOLERANCE_DB))
                rms_tol = float(tolerances.get("rms_dbfs", _RMS_TOLERANCE_DB))
                lufs_tol = float(tolerances.get("integrated_lufs", _LUFS_TOLERANCE))

                for target_layout_id, target_expected in expected.get("targets", {}).items():
                    target_actual = actual["targets"][target_layout_id]
                    self.assertEqual(
                        target_actual["normalized_render_manifest_sha256"],
                        target_expected["normalized_render_manifest_sha256"],
                    )
                    self.assertEqual(
                        target_actual["normalized_receipt_sha256"],
                        target_expected["normalized_receipt_sha256"],
                    )
                    self.assertEqual(
                        target_actual["channel_count"],
                        target_expected["channel_count"],
                    )
                    self.assertEqual(
                        target_actual["channel_order"],
                        target_expected["channel_order"],
                    )
                    self.assertEqual(
                        target_actual["scene_sha256"],
                        target_expected["scene_sha256"],
                    )
                    self.assertEqual(
                        target_actual["downmix_policy_version"],
                        target_expected["downmix_policy_version"],
                    )
                    self.assertEqual(
                        target_actual["render_contract_version"],
                        target_expected["render_contract_version"],
                    )

                    actual_metrics = target_actual["per_channel_metrics"]
                    expected_metrics = target_expected["per_channel_metrics"]
                    self.assertEqual(len(actual_metrics), len(expected_metrics))
                    for actual_row, expected_row in zip(actual_metrics, expected_metrics):
                        self.assertEqual(actual_row["speaker_id"], expected_row["speaker_id"])
                        self._assert_metric_close(
                            actual_row["peak_dbfs"],
                            expected_row["peak_dbfs"],
                            peak_tol,
                            f"{spec.fixture_id}:{target_layout_id}:{actual_row['speaker_id']}:peak_dbfs",
                        )
                        self._assert_metric_close(
                            actual_row["rms_dbfs"],
                            expected_row["rms_dbfs"],
                            rms_tol,
                            f"{spec.fixture_id}:{target_layout_id}:{actual_row['speaker_id']}:rms_dbfs",
                        )
                        self._assert_metric_close(
                            actual_row["integrated_lufs"],
                            expected_row["integrated_lufs"],
                            lufs_tol,
                            (
                                f"{spec.fixture_id}:{target_layout_id}:"
                                f"{actual_row['speaker_id']}:integrated_lufs"
                            ),
                        )

    def test_gate_outcomes_match(self) -> None:
        for spec in _FIXTURE_SPECS:
            with self.subTest(fixture=spec.fixture_id):
                actual = self.actual[spec.fixture_id]["expected_gate_outcomes"]
                expected = self._expected_payload(spec, "expected_gate_outcomes.json")
                self.assertEqual(actual, expected)

    def _assert_metric_close(
        self,
        actual: float | None,
        expected: float | None,
        tolerance: float,
        label: str,
    ) -> None:
        if expected is None:
            self.assertIsNone(actual, msg=label)
            return
        self.assertIsNotNone(actual, msg=label)
        if actual is None:
            return
        self.assertLessEqual(abs(actual - expected), tolerance, msg=label)
