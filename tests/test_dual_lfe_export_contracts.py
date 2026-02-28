"""Regression tests for dual-LFE export-contract behavior."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.render_reporting import build_render_report_from_plan

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_FIXTURES_DIR = _REPO_ROOT / "fixtures" / "render"

_DUAL_LFE_FIXTURES: dict[str, dict[str, object]] = {
    "dual_lfe_5_2.render_plan.json": {
        "target_layout_id": "LAYOUT.5_2",
        "channel_count": 7,
        "channel_order": [
            "SPK.L",
            "SPK.R",
            "SPK.C",
            "SPK.LFE",
            "SPK.LFE2",
            "SPK.LS",
            "SPK.RS",
        ],
        "ffmpeg_channel_layout": "FL+FR+FC+LFE+LFE2+SL+SR",
    },
    "dual_lfe_7_2.render_plan.json": {
        "target_layout_id": "LAYOUT.7_2",
        "channel_count": 9,
        "channel_order": [
            "SPK.L",
            "SPK.R",
            "SPK.C",
            "SPK.LFE",
            "SPK.LFE2",
            "SPK.LS",
            "SPK.RS",
            "SPK.LRS",
            "SPK.RRS",
        ],
        "ffmpeg_channel_layout": "FL+FR+FC+LFE+LFE2+SL+SR+BL+BR",
    },
    "dual_lfe_7_2_4.render_plan.json": {
        "target_layout_id": "LAYOUT.7_2_4",
        "channel_count": 13,
        "channel_order": [
            "SPK.L",
            "SPK.R",
            "SPK.C",
            "SPK.LFE",
            "SPK.LFE2",
            "SPK.LS",
            "SPK.RS",
            "SPK.LRS",
            "SPK.RRS",
            "SPK.TFL",
            "SPK.TFR",
            "SPK.TRL",
            "SPK.TRR",
        ],
        "ffmpeg_channel_layout": "FL+FR+FC+LFE+LFE2+SL+SR+BL+BR+TFL+TFR+TBL+TBR",
    },
}


def _validator(schema_name: str) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(_SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads((_SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _dual_lfe_render_plan_fixture(name: str) -> dict:
    fixture_path = _FIXTURES_DIR / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture_name", sorted(_DUAL_LFE_FIXTURES))
def test_dual_lfe_fixture_plan_and_report_validate(fixture_name: str) -> None:
    plan = _dual_lfe_render_plan_fixture(fixture_name)
    _validator("render_plan.schema.json").validate(plan)
    report = build_render_report_from_plan(plan, status="completed", reason="rendered")
    _validator("render_report.schema.json").validate(report)


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    sorted(_DUAL_LFE_FIXTURES.items()),
)
def test_dual_lfe_render_report_contains_channel_order_and_wav_warning(
    fixture_name: str,
    expected: dict[str, object],
) -> None:
    plan = _dual_lfe_render_plan_fixture(fixture_name)
    report = build_render_report_from_plan(plan, status="completed", reason="rendered")

    jobs = report.get("jobs")
    assert isinstance(jobs, list)
    assert len(jobs) == 1
    job = jobs[0]
    assert isinstance(job, dict)
    assert job.get("target_layout_id") == expected["target_layout_id"]
    assert job.get("channel_count") == expected["channel_count"]
    assert job.get("channel_order") == expected["channel_order"]
    assert job.get("ffmpeg_channel_layout") == expected["ffmpeg_channel_layout"]

    warnings = job.get("warnings")
    assert isinstance(warnings, list)
    joined = " ".join(warnings)
    assert "DIRECTOUT (mask=0)" in joined
    assert "LFE2" in joined
    assert "How to validate:" in joined


@pytest.mark.parametrize("fixture_name", sorted(_DUAL_LFE_FIXTURES))
def test_dual_lfe_warning_not_emitted_for_non_wav_outputs(fixture_name: str) -> None:
    plan = _dual_lfe_render_plan_fixture(fixture_name)
    jobs = plan.get("jobs")
    assert isinstance(jobs, list)
    jobs[0]["output_formats"] = ["flac"]

    report = build_render_report_from_plan(plan, status="completed", reason="rendered")
    report_jobs = report.get("jobs")
    assert isinstance(report_jobs, list)
    job = report_jobs[0]
    assert isinstance(job, dict)
    assert "warnings" not in job
