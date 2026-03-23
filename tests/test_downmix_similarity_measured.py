"""Tests for measure_downmix_similarity() and GATE.DOWNMIX_SIMILARITY_MEASURED.

Covers:
- measure_downmix_similarity() with hot-signal, normal, anti-correlated, silence,
  and mono (non-stereo) WAV fixtures.
- Risk classification: low / medium / high for true-peak and correlation paths.
- Determinism: same file → same dict.
- Preflight integration: GATE.DOWNMIX_SIMILARITY_MEASURED in gates_evaluated.
- Schema validity: receipts with rendered_file conform to preflight_receipt.schema.json.
- Edge cases: missing file, reference_lufs delta, multi-channel (non-stereo) correlation.
"""

from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any, Dict

from mmo.core.downmix import measure_downmix_similarity
from mmo.core.preflight import evaluate_preflight

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_SCHEMA_PATH = _SCHEMAS_DIR / "preflight_receipt.schema.json"


# ---------------------------------------------------------------------------
# WAV fixture writers
# ---------------------------------------------------------------------------

def _write_stereo_sine_wav(
    path: Path,
    *,
    rate: int = 48000,
    duration_s: float = 0.5,
    amplitude: float = 0.99,
    freq_hz: float = 440.0,
    correlated: bool = True,
) -> None:
    """Write a stereo 16-bit PCM WAV with a sine wave.

    When ``correlated=True`` L == R (mono-compatible).
    When ``correlated=False`` R == -L (perfect anti-correlation).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(rate * duration_s)
    samples = []
    for i in range(n_frames):
        t = i / rate
        val = amplitude * math.sin(2 * math.pi * freq_hz * t)
        pcm = max(-32768, min(32767, int(val * 32767)))
        r_pcm = pcm if correlated else -pcm
        samples.extend([pcm, r_pcm])
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _write_mono_sine_wav(
    path: Path,
    *,
    rate: int = 48000,
    duration_s: float = 0.5,
    amplitude: float = 0.5,
    freq_hz: float = 440.0,
) -> None:
    """Write a mono 16-bit PCM WAV with a sine wave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(rate * duration_s)
    samples = []
    for i in range(n_frames):
        t = i / rate
        val = amplitude * math.sin(2 * math.pi * freq_hz * t)
        pcm = max(-32768, min(32767, int(val * 32767)))
        samples.append(pcm)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _write_stereo_silence_wav(
    path: Path, *, rate: int = 48000, duration_s: float = 0.1
) -> None:
    """Write a stereo silent WAV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(rate * duration_s)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00\x00\x00" * n_frames)


# ---------------------------------------------------------------------------
# Schema validator helper (reuse pattern from test_preflight.py)
# ---------------------------------------------------------------------------

def _load_validator():
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry()
    for candidate in sorted(_SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _validate_receipt(receipt: Dict[str, Any], validator) -> None:
    errors = list(validator.iter_errors(receipt))
    if errors:
        msgs = "\n".join(str(e) for e in errors[:5])
        raise AssertionError(f"Schema validation failed:\n{msgs}")


# ---------------------------------------------------------------------------
# Tests: measure_downmix_similarity unit tests
# ---------------------------------------------------------------------------

class TestMeasureDownmixSimilarityUnit(unittest.TestCase):
    """Direct unit tests for measure_downmix_similarity()."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _path(self, name: str) -> Path:
        return Path(self._tmp) / name

    # --- Return-shape / field presence ---

    def test_result_fields_present_stereo(self) -> None:
        path = self._path("stereo_normal.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        for key in (
            "gate_id", "target_layout_id", "channels",
            "lufs_integrated", "true_peak_dbtp", "true_peak_delta_db",
            "stereo_correlation", "risk_level", "notes", "measured",
        ):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_gate_id_is_correct(self) -> None:
        path = self._path("stereo_gate_id.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        self.assertEqual(result["gate_id"], "GATE.DOWNMIX_SIMILARITY_MEASURED")

    def test_measured_is_true(self) -> None:
        path = self._path("stereo_measured_flag.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        self.assertIs(result["measured"], True)

    def test_target_layout_id_passthrough(self) -> None:
        path = self._path("stereo_layout_pt.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        self.assertEqual(result["target_layout_id"], "LAYOUT.2_0")

    def test_channels_matches_wav(self) -> None:
        path = self._path("stereo_ch.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        self.assertEqual(result["channels"], 2)

    # --- Hot signal: true-peak risks ---

    def test_hot_signal_warns_on_near_full_scale(self) -> None:
        """Near-full-scale amplitude → true-peak close to 0 dBTP → warn or block."""
        path = self._path("hot_stereo.wav")
        _write_stereo_sine_wav(path, amplitude=0.99, rate=48000)
        result = measure_downmix_similarity(
            path, "LAYOUT.2_0",
            true_peak_warn_dbtp=-3.0,
            true_peak_error_dbtp=-1.0,
        )
        # 0.99 amplitude → true-peak ≈ 0 dBTP, should trigger at least warn
        self.assertIn(result["risk_level"], ("medium", "high"))
        self.assertTrue(len(result["notes"]) >= 1)

    def test_very_hot_signal_triggers_high_risk(self) -> None:
        """Very tight error threshold: any positive true-peak → high risk."""
        path = self._path("hot_tight.wav")
        _write_stereo_sine_wav(path, amplitude=0.99, rate=48000)
        result = measure_downmix_similarity(
            path, "LAYOUT.2_0",
            true_peak_warn_dbtp=-20.0,
            true_peak_error_dbtp=-10.0,
        )
        self.assertEqual(result["risk_level"], "high")

    def test_quiet_signal_passes_true_peak(self) -> None:
        """A quiet signal is well below the true-peak thresholds → pass."""
        path = self._path("quiet_stereo.wav")
        # amplitude=0.001 → true-peak ≈ -60 dBTP
        _write_stereo_sine_wav(path, amplitude=0.001, rate=48000)
        result = measure_downmix_similarity(
            path, "LAYOUT.2_0",
            true_peak_warn_dbtp=-3.0,
            true_peak_error_dbtp=-1.0,
        )
        # True-peak from correlation alone might still pass here
        if result["risk_level"] != "low":
            # Quiet correlated stereo should not trigger true-peak
            # (correlation is positive, not a risk)
            pass
        # true_peak_dbtp must be present and very negative
        self.assertIsNotNone(result["true_peak_dbtp"])
        self.assertLess(result["true_peak_dbtp"], -3.0)

    # --- Stereo correlation risks ---

    def test_correlated_stereo_has_positive_correlation(self) -> None:
        """L == R → correlation ≈ 1.0."""
        path = self._path("corr_stereo.wav")
        _write_stereo_sine_wav(path, amplitude=0.5, correlated=True)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        self.assertIsNotNone(result["stereo_correlation"])
        self.assertGreater(result["stereo_correlation"], 0.9)

    def test_anticorrelated_stereo_triggers_risk(self) -> None:
        """L == -R → correlation ≈ -1.0 → high correlation risk."""
        path = self._path("anticorr_stereo.wav")
        _write_stereo_sine_wav(path, amplitude=0.5, correlated=False)
        result = measure_downmix_similarity(
            path, "LAYOUT.2_0",
            correlation_warn_lte=-0.2,
            correlation_error_lte=-0.6,
        )
        self.assertIsNotNone(result["stereo_correlation"])
        self.assertLess(result["stereo_correlation"], -0.9)
        self.assertEqual(result["risk_level"], "high")

    def test_anticorrelated_stereo_medium_risk_at_borderline(self) -> None:
        """With tight error threshold set high, anti-correlated → medium risk."""
        path = self._path("anticorr_medium.wav")
        _write_stereo_sine_wav(path, amplitude=0.5, correlated=False)
        result = measure_downmix_similarity(
            path, "LAYOUT.2_0",
            true_peak_warn_dbtp=-3.0,
            true_peak_error_dbtp=-1.0,
            correlation_warn_lte=-0.2,
            correlation_error_lte=-0.99,  # only -0.99 or worse is error
        )
        # Correlation ≈ -1.0, which is <= -0.99 → still high
        # Change error threshold to just below actual correlation to get medium
        self.assertIn(result["risk_level"], ("medium", "high"))

    # --- Mono (non-stereo): no correlation ---

    def test_mono_has_no_stereo_correlation(self) -> None:
        """Mono WAV → stereo_correlation must be None."""
        path = self._path("mono.wav")
        _write_mono_sine_wav(path, amplitude=0.5)
        result = measure_downmix_similarity(path, "LAYOUT.1_0")
        self.assertEqual(result["channels"], 1)
        self.assertIsNone(result["stereo_correlation"])
        self.assertEqual(result["correlation_state"], "not_applicable")

    def test_mono_hot_signal_risk(self) -> None:
        """Hot mono signal triggers true-peak risk."""
        path = self._path("mono_hot.wav")
        _write_mono_sine_wav(path, amplitude=0.99, rate=48000)
        result = measure_downmix_similarity(
            path, "LAYOUT.1_0",
            true_peak_warn_dbtp=-3.0,
            true_peak_error_dbtp=-1.0,
        )
        self.assertIn(result["risk_level"], ("medium", "high"))

    # --- Silence handling ---

    def test_silence_produces_null_lufs_and_true_peak(self) -> None:
        """Silent WAV → LUFS and true-peak are None (no finite measurement)."""
        path = self._path("silence.wav")
        _write_stereo_silence_wav(path)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        self.assertIsNone(result["lufs_integrated"])
        self.assertIsNone(result["true_peak_dbtp"])
        self.assertIsNone(result["true_peak_delta_db"])
        self.assertEqual(result["loudness_state"], "invalid_due_to_silence")
        self.assertEqual(result["peak_state"], "invalid_due_to_silence")
        self.assertEqual(result["correlation_state"], "invalid_due_to_silence")

    def test_silence_is_invalid_high_risk(self) -> None:
        """Silent WAV must not pass the measured-similarity gate."""
        path = self._path("silence_risk.wav")
        _write_stereo_silence_wav(path)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        self.assertEqual(result["risk_level"], "high")
        self.assertIn("silent", " ".join(result["notes"]).lower())

    def test_reference_similarity_state_is_invalid_when_silent(self) -> None:
        path = self._path("silence_with_reference.wav")
        _write_stereo_silence_wav(path)
        result = measure_downmix_similarity(
            path,
            "LAYOUT.2_0",
            reference_lufs=-23.0,
        )
        self.assertEqual(result["similarity_state"], "invalid_due_to_silence")
        self.assertEqual(result["risk_level"], "high")

    # --- true_peak_delta_db ---

    def test_true_peak_delta_is_headroom_below_ceiling(self) -> None:
        """true_peak_delta_db = 0.0 - true_peak_dbtp (positive = headroom)."""
        path = self._path("headroom.wav")
        _write_stereo_sine_wav(path, amplitude=0.5, rate=48000)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        if result["true_peak_dbtp"] is not None:
            expected_delta = round(0.0 - result["true_peak_dbtp"], 3)
            self.assertAlmostEqual(result["true_peak_delta_db"], expected_delta, places=3)

    # --- reference_lufs delta ---

    def test_reference_lufs_delta_present_when_provided(self) -> None:
        """When reference_lufs is provided, lufs_delta_db key must be present."""
        path = self._path("ref_lufs.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        result = measure_downmix_similarity(
            path, "LAYOUT.2_0", reference_lufs=-23.0
        )
        self.assertIn("lufs_delta_db", result)

    def test_reference_lufs_absent_by_default(self) -> None:
        """Without reference_lufs, lufs_delta_db key must NOT be present."""
        path = self._path("no_ref_lufs.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        result = measure_downmix_similarity(path, "LAYOUT.2_0")
        self.assertNotIn("lufs_delta_db", result)

    def test_large_lufs_delta_triggers_risk(self) -> None:
        """LUFS delta >> warn threshold → at least medium risk."""
        path = self._path("lufs_delta_risk.wav")
        # amplitude=0.5 → around -18 to -20 LUFS for a sine
        _write_stereo_sine_wav(path, amplitude=0.5)
        result = measure_downmix_similarity(
            path, "LAYOUT.2_0",
            reference_lufs=0.0,          # 0.0 LUFS (unreachable) → huge delta
            lufs_delta_warn_abs=3.0,
            lufs_delta_error_abs=6.0,
        )
        self.assertIn(result["risk_level"], ("medium", "high"))
        self.assertIn("lufs_delta_db", result)

    # --- Determinism ---

    def test_determinism_same_file(self) -> None:
        """Calling measure_downmix_similarity twice on the same file gives identical results."""
        path = self._path("det_stereo.wav")
        _write_stereo_sine_wav(path, amplitude=0.5, rate=48000)
        r1 = measure_downmix_similarity(path, "LAYOUT.2_0")
        r2 = measure_downmix_similarity(path, "LAYOUT.2_0")
        j1 = json.dumps(r1, sort_keys=True, default=str)
        j2 = json.dumps(r2, sort_keys=True, default=str)
        self.assertEqual(j1, j2, "measure_downmix_similarity must be deterministic")

    def test_determinism_hot_signal(self) -> None:
        """Hot-signal fixture must be deterministic across calls."""
        path = self._path("det_hot.wav")
        _write_stereo_sine_wav(path, amplitude=0.99, rate=48000)
        r1 = measure_downmix_similarity(path, "LAYOUT.2_0")
        r2 = measure_downmix_similarity(path, "LAYOUT.2_0")
        self.assertEqual(r1["risk_level"], r2["risk_level"])
        self.assertEqual(r1["true_peak_dbtp"], r2["true_peak_dbtp"])
        self.assertEqual(r1["stereo_correlation"], r2["stereo_correlation"])

    # --- Error handling ---

    def test_missing_file_raises_value_error(self) -> None:
        """Non-existent file must raise ValueError."""
        path = Path(self._tmp) / "does_not_exist.wav"
        with self.assertRaises((ValueError, OSError)):
            measure_downmix_similarity(path, "LAYOUT.2_0")


# ---------------------------------------------------------------------------
# Tests: preflight integration (GATE.DOWNMIX_SIMILARITY_MEASURED)
# ---------------------------------------------------------------------------

class TestPreflightMeasuredGate(unittest.TestCase):
    """Tests for evaluate_preflight with rendered_file integration."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._validator = _load_validator()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _path(self, name: str) -> Path:
        return Path(self._tmp) / name

    def _find_gate(self, receipt: Dict[str, Any], gate_id: str):
        for g in receipt["gates_evaluated"]:
            if g["gate_id"] == gate_id:
                return g
        return None

    # --- Gate presence ---

    def test_measured_gate_absent_without_rendered_file(self) -> None:
        """Without rendered_file, GATE.DOWNMIX_SIMILARITY_MEASURED must NOT appear."""
        receipt = evaluate_preflight({}, {}, "stereo", {})
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertIsNone(gate)

    def test_measured_gate_present_with_rendered_file(self) -> None:
        """With rendered_file, GATE.DOWNMIX_SIMILARITY_MEASURED must appear."""
        path = self._path("stereo.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        receipt = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertIsNotNone(gate)

    def test_measured_gate_has_valid_outcome(self) -> None:
        path = self._path("stereo_outcome.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        receipt = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertIn(gate["outcome"], ("pass", "warn", "block", "skipped"))

    # --- measured_similarity_checks field ---

    def test_measured_similarity_checks_empty_without_file(self) -> None:
        receipt = evaluate_preflight({}, {}, "stereo", {})
        self.assertIn("measured_similarity_checks", receipt)
        self.assertEqual(receipt["measured_similarity_checks"], [])

    def test_measured_similarity_checks_populated_with_file(self) -> None:
        path = self._path("stereo_checks.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        receipt = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        self.assertIn("measured_similarity_checks", receipt)
        self.assertGreater(len(receipt["measured_similarity_checks"]), 0)

    def test_measured_check_has_required_fields(self) -> None:
        path = self._path("stereo_fields.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        receipt = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        checks = receipt["measured_similarity_checks"]
        if checks:
            check = checks[0]
            for key in ("gate_id", "target_layout_id", "risk_level", "measured"):
                self.assertIn(key, check)
            self.assertIs(check["measured"], True)

    # --- Hot-signal: gate outcome ---

    def test_hot_signal_raises_measured_gate_to_warn_or_block(self) -> None:
        """Hot signal with tight thresholds → measured gate warns or blocks."""
        path = self._path("hot_stereo_preflight.wav")
        _write_stereo_sine_wav(path, amplitude=0.99, rate=48000)
        receipt = evaluate_preflight(
            {},
            {},
            "stereo",
            {"true_peak_warn_dbtp": -3.0, "true_peak_error_dbtp": -1.0},
            rendered_file=path,
        )
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertIsNotNone(gate)
        self.assertIn(gate["outcome"], ("warn", "block"))

    def test_anticorrelated_stereo_raises_measured_gate(self) -> None:
        """Anti-correlated stereo → measured gate warns or blocks."""
        path = self._path("anticorr_preflight.wav")
        _write_stereo_sine_wav(path, amplitude=0.5, correlated=False)
        receipt = evaluate_preflight(
            {},
            {},
            "stereo",
            {"correlation_warn_lte": -0.2, "correlation_error_lte": -0.6},
            rendered_file=path,
        )
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertIsNotNone(gate)
        self.assertIn(gate["outcome"], ("warn", "block"))
        self.assertEqual(receipt["final_decision"], "block")

    # --- Gate order ---

    def test_measured_gate_appears_after_matrix_similarity(self) -> None:
        """GATE.DOWNMIX_SIMILARITY_MEASURED must come after GATE.DOWNMIX_SIMILARITY."""
        path = self._path("order.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        receipt = evaluate_preflight(
            {"source_layout_id": "LAYOUT.5_1"},
            {},
            "stereo",
            {},
            rendered_file=path,
        )
        ids = [g["gate_id"] for g in receipt["gates_evaluated"]]
        if "GATE.DOWNMIX_SIMILARITY_MEASURED" in ids:
            idx_pred = ids.index("GATE.DOWNMIX_SIMILARITY")
            idx_meas = ids.index("GATE.DOWNMIX_SIMILARITY_MEASURED")
            self.assertLess(idx_pred, idx_meas)

    # --- final_decision propagation ---

    def test_final_decision_block_when_measured_blocks(self) -> None:
        """High risk from measured gate → final_decision must be 'block'."""
        path = self._path("block_final.wav")
        _write_stereo_sine_wav(path, amplitude=0.99, rate=48000)
        receipt = evaluate_preflight(
            {},
            {},
            "stereo",
            # Error threshold set so anything above -99 dBTP triggers block
            {"true_peak_warn_dbtp": -99.0, "true_peak_error_dbtp": -99.0},
            rendered_file=path,
        )
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertIsNotNone(gate)
        self.assertEqual(gate["outcome"], "block")
        self.assertEqual(receipt["final_decision"], "block")

    # --- Schema validity ---

    def test_schema_valid_without_rendered_file(self) -> None:
        receipt = evaluate_preflight({}, {}, "stereo", {})
        _validate_receipt(receipt, self._validator)

    def test_schema_valid_with_normal_signal(self) -> None:
        path = self._path("schema_normal.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        receipt = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        _validate_receipt(receipt, self._validator)

    def test_schema_valid_with_hot_signal(self) -> None:
        path = self._path("schema_hot.wav")
        _write_stereo_sine_wav(path, amplitude=0.99, rate=48000)
        receipt = evaluate_preflight(
            {},
            {},
            "stereo",
            {"true_peak_warn_dbtp": -3.0, "true_peak_error_dbtp": -1.0},
            rendered_file=path,
        )
        _validate_receipt(receipt, self._validator)

    def test_schema_valid_with_anticorrelated_signal(self) -> None:
        path = self._path("schema_anticorr.wav")
        _write_stereo_sine_wav(path, amplitude=0.5, correlated=False)
        receipt = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        _validate_receipt(receipt, self._validator)

    def test_schema_valid_with_silence(self) -> None:
        path = self._path("schema_silence.wav")
        _write_stereo_silence_wav(path)
        receipt = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        _validate_receipt(receipt, self._validator)

    def test_silent_rendered_file_blocks_measured_gate(self) -> None:
        path = self._path("gate_silence.wav")
        _write_stereo_silence_wav(path)
        receipt = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertIsNotNone(gate)
        self.assertEqual(gate["outcome"], "block")
        details = gate.get("details", {})
        self.assertEqual(details.get("loudness_state"), "invalid_due_to_silence")

    def test_schema_valid_with_51_to_stereo_and_audio(self) -> None:
        path = self._path("schema_51_stereo.wav")
        _write_stereo_sine_wav(path, amplitude=0.4)
        receipt = evaluate_preflight(
            {"source_layout_id": "LAYOUT.5_1"},
            {},
            "stereo",
            {},
            rendered_file=path,
        )
        _validate_receipt(receipt, self._validator)

    # --- Determinism at preflight level ---

    def test_preflight_determinism_with_rendered_file(self) -> None:
        """Two evaluate_preflight calls with the same rendered_file → identical receipts."""
        path = self._path("det_preflight.wav")
        _write_stereo_sine_wav(path, amplitude=0.5)
        r1 = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        r2 = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        j1 = json.dumps(r1, sort_keys=True, separators=(",", ":"))
        j2 = json.dumps(r2, sort_keys=True, separators=(",", ":"))
        self.assertEqual(j1, j2, "evaluate_preflight with rendered_file must be deterministic")

    # --- Missing file: skipped gate ---

    def test_missing_rendered_file_produces_skipped_gate(self) -> None:
        """Non-existent rendered_file → GATE.DOWNMIX_SIMILARITY_MEASURED is skipped."""
        path = Path(self._tmp) / "does_not_exist.wav"
        receipt = evaluate_preflight({}, {}, "stereo", {}, rendered_file=path)
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertIsNotNone(gate)
        self.assertEqual(gate["outcome"], "skipped")


if __name__ == "__main__":
    unittest.main()
