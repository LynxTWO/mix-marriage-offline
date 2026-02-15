from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from mmo.core.cache_keys import cache_key, hash_lockfile, hash_run_config
from mmo.core.cache_store import (
    report_has_time_cap_stop_condition,
    report_schema_is_valid,
    rewrite_report_stems_dir,
    save_cached_report,
    try_load_cached_report,
)
from mmo.core.compare import (
    build_compare_report,
    default_label_for_compare_input,
    load_report_from_path_or_dir,
)
from mmo.core.deliverables_index import (
    build_deliverables_index_single,
    build_deliverables_index_variants,
)
from mmo.core.presets import (
    list_preset_packs,
    list_presets,
    load_preset_pack,
    load_preset_run_config,
)
from mmo.core.render_plan import build_render_plan
from mmo.core.render_plan_bridge import render_plan_to_variant_plan
from mmo.core.render_targets import (
    get_render_target,
    list_render_targets,
    resolve_render_target_id,
)
from mmo.core.role_lexicon import (
    load_role_lexicon,
    merge_suggestions_into_lexicon,
    render_role_lexicon_yaml,
)
from mmo.core.roles import list_roles, load_roles, resolve_role
from mmo.core.stems_classifier import classify_stems, classify_stems_with_evidence
from mmo.core.stems_audition import render_audition_pack
from mmo.core.stems_draft import build_draft_routing_plan, build_draft_scene
from mmo.core.translation_profiles import (
    get_translation_profile,
    list_translation_profiles,
    load_translation_profiles,
)
from mmo.core.translation_summary import build_translation_summary
from mmo.core.translation_checks import run_translation_checks
from mmo.core.translation_audition import render_translation_auditions
from mmo.core.translation_reference import (
    TranslationReferenceResolutionError,
    resolve_translation_reference_audio,
)
from mmo.core.target_recommendations import recommend_render_targets
from mmo.core.scene_templates import (
    apply_scene_templates,
    get_scene_template,
    list_scene_templates,
    preview_scene_templates,
)
from mmo.core.scene_locks import get_scene_lock, list_scene_locks
from mmo.core.intent_params import load_intent_params, validate_scene_intent
from mmo.core.stems_index import build_stems_index, resolve_stem_sets
from mmo.core.stems_overrides import apply_overrides, load_stems_overrides
from mmo.core.scene_editor import (
    INTENT_PARAM_KEY_TO_ID,
    add_lock as edit_scene_add_lock,
    remove_lock as edit_scene_remove_lock,
    set_intent as edit_scene_set_intent,
)
from mmo.core.listen_pack import build_listen_pack, index_stems_auditions
from mmo.core.project_file import (
    load_project,
    new_project,
    update_project_last_run,
    write_project,
)
from mmo.core.gui_state import default_gui_state, validate_gui_state
from mmo.core.routing import (
    apply_routing_plan_to_report,
    build_routing_plan,
    render_routing_plan,
    routing_layout_ids_from_run_config,
)
from mmo.core.run_config import (
    RUN_CONFIG_SCHEMA_VERSION,
    diff_run_config,
    load_run_config,
    merge_run_config,
    normalize_run_config,
)
from mmo.core.timeline import load_timeline
from mmo.core.variants import build_variant_plan, run_variant_plan
from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS
from mmo.ui.tui import choose_from_list, multi_toggle, render_header, yes_no

try:
    import jsonschema
except ImportError:  # pragma: no cover - environment issue
    jsonschema = None

_PRESET_PREVIEW_DEFAULT_PROFILE_ID = "PROFILE.ASSIST"
_PRESET_PREVIEW_DEFAULT_METERS = "truth"
_PRESET_PREVIEW_DEFAULT_MAX_SECONDS = 120.0
_PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID = "LAYOUT.2_0"
_BASELINE_RENDER_TARGET_ID = "TARGET.STEREO.2_0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_FORMAT_SET_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_RUN_COMMAND_EPILOG = (
    "One button for musicians: analyze your stems, then optionally export notes, "
    "apply safe fixes, render lossless files, and build a UI bundle in one pass."
)
_UI_OVERLAY_CHIPS: tuple[str, ...] = (
    "Warm",
    "Air",
    "Punch",
    "Glue",
    "Wide",
    "Safe",
    "Live",
    "Vocal",
)
_SCENE_INTENT_KEYS: tuple[str, ...] = (
    "width",
    "depth",
    "azimuth_deg",
    "loudness_bias",
    "confidence",
)
_DEFAULT_RENDER_MANY_TRANSLATION_PROFILE_IDS: tuple[str, ...] = (
    "TRANS.MONO.COLLAPSE",
    "TRANS.DEVICE.PHONE",
    "TRANS.DEVICE.SMALL_SPEAKER",
)
_DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S = 30.0


# ── Subcommand handlers (extracted to cli_commands/) ──
from mmo.cli_commands._helpers import *  # noqa: F401,F403
from mmo.cli_commands._analysis import *  # noqa: F401,F403
from mmo.cli_commands._renderers import *  # noqa: F401,F403
from mmo.cli_commands._stems import *  # noqa: F401,F403
from mmo.cli_commands._scene import *  # noqa: F401,F403
from mmo.cli_commands._registries import *  # noqa: F401,F403
from mmo.cli_commands._workflows import *  # noqa: F401,F403
from mmo.cli_commands._project import *  # noqa: F401,F403
from mmo.cli_commands._utilities import *  # noqa: F401,F403


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MMO command-line tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan stems and write a report JSON.")
    scan_parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
    scan_parser.add_argument("--out", required=True, help="Path to output report JSON.")
    scan_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    scan_parser.add_argument(
        "--peak",
        action="store_true",
        help="Compute WAV sample peak meter readings for stems.",
    )

    analyze_parser = subparsers.add_parser(
        "analyze", help="Run scan + pipeline + exports for a stems directory."
    )
    analyze_parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
    analyze_parser.add_argument(
        "--out-report",
        required=True,
        help="Path to the output report JSON after running the pipeline.",
    )
    analyze_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    analyze_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    analyze_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    analyze_parser.add_argument(
        "--peak",
        action="store_true",
        help="Compute WAV sample peak meter readings for stems.",
    )
    analyze_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to the plugins directory.",
    )
    analyze_parser.add_argument(
        "--keep-scan",
        action="store_true",
        help="Keep the intermediate scan report JSON instead of deleting it.",
    )
    analyze_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for gate eligibility (default: PROFILE.ASSIST).",
    )
    analyze_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="Reuse cached analysis by lockfile + run_config hash (default: on).",
    )
    analyze_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )

    stems_parser = subparsers.add_parser("stems", help="Stem-set resolver tools.")
    stems_subparsers = stems_parser.add_subparsers(dest="stems_command", required=True)
    stems_scan_parser = stems_subparsers.add_parser(
        "scan",
        help="Resolve stem sets and write a stems_index artifact JSON.",
    )
    stems_scan_parser.add_argument(
        "--root",
        required=True,
        help="Root directory to scan for stem sets.",
    )
    stems_scan_parser.add_argument(
        "--out",
        required=True,
        help="Path to output stems_index JSON.",
    )
    stems_scan_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for stdout summary.",
    )
    stems_sets_parser = stems_subparsers.add_parser(
        "sets",
        help="List stem-set candidates for a root directory.",
    )
    stems_sets_parser.add_argument(
        "--root",
        required=True,
        help="Root directory to scan for stem sets.",
    )
    stems_sets_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for stem-set listing.",
    )
    stems_classify_parser = stems_subparsers.add_parser(
        "classify",
        help="Classify stems by role and write a stems_map artifact JSON.",
    )
    stems_classify_input = stems_classify_parser.add_mutually_exclusive_group(required=True)
    stems_classify_input.add_argument(
        "--index",
        help="Path to an existing stems_index JSON.",
    )
    stems_classify_input.add_argument(
        "--root",
        help="Root directory to scan for stems before classification.",
    )
    stems_classify_parser.add_argument(
        "--out",
        required=True,
        help="Path to output stems_map JSON.",
    )
    stems_classify_parser.add_argument(
        "--role-lexicon",
        default=None,
        help="Optional path to role lexicon extension YAML.",
    )
    stems_classify_parser.add_argument(
        "--no-common-lexicon",
        action="store_true",
        help="Disable built-in common role lexicon baseline.",
    )
    stems_classify_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for stdout summary.",
    )
    stems_explain_parser = stems_subparsers.add_parser(
        "explain",
        help="Explain role-matching evidence for one stem file.",
    )
    stems_explain_input = stems_explain_parser.add_mutually_exclusive_group(required=True)
    stems_explain_input.add_argument(
        "--index",
        help="Path to an existing stems_index JSON.",
    )
    stems_explain_input.add_argument(
        "--root",
        help="Root directory to scan for stems before explanation.",
    )
    stems_explain_parser.add_argument(
        "--file",
        required=True,
        help="Stem rel_path or file_id to explain.",
    )
    stems_explain_parser.add_argument(
        "--role-lexicon",
        default=None,
        help="Optional path to role lexicon extension YAML.",
    )
    stems_explain_parser.add_argument(
        "--no-common-lexicon",
        action="store_true",
        help="Disable built-in common role lexicon baseline.",
    )
    stems_explain_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for explanation output.",
    )
    stems_apply_overrides_parser = stems_subparsers.add_parser(
        "apply-overrides",
        help="Apply stems overrides to an existing stems_map JSON.",
    )
    stems_apply_overrides_parser.add_argument(
        "--map",
        required=True,
        help="Path to an existing stems_map JSON.",
    )
    stems_apply_overrides_parser.add_argument(
        "--overrides",
        required=True,
        help="Path to stems overrides YAML.",
    )
    stems_apply_overrides_parser.add_argument(
        "--out",
        required=True,
        help="Path to output patched stems_map JSON.",
    )
    stems_apply_overrides_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for stdout summary.",
    )
    stems_review_parser = stems_subparsers.add_parser(
        "review",
        help="Review assignments from an existing stems_map JSON.",
    )
    stems_review_parser.add_argument(
        "--map",
        required=True,
        help="Path to an existing stems_map JSON.",
    )
    stems_review_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for review output.",
    )
    stems_overrides_parser = stems_subparsers.add_parser(
        "overrides",
        help="Stems override artifact tools.",
    )
    stems_overrides_subparsers = stems_overrides_parser.add_subparsers(
        dest="stems_overrides_command",
        required=True,
    )
    stems_overrides_default_parser = stems_overrides_subparsers.add_parser(
        "default",
        help="Write a default stems overrides YAML template.",
    )
    stems_overrides_default_parser.add_argument(
        "--out",
        required=True,
        help="Path to output stems overrides YAML.",
    )
    stems_overrides_validate_parser = stems_overrides_subparsers.add_parser(
        "validate",
        help="Validate a stems overrides YAML file.",
    )
    stems_overrides_validate_parser.add_argument(
        "--in",
        dest="in_path",
        required=True,
        help="Path to stems overrides YAML.",
    )
    stems_pipeline_parser = stems_subparsers.add_parser(
        "pipeline",
        help="One-command scan + classify + default overrides.",
    )
    stems_pipeline_parser.add_argument(
        "--root",
        required=True,
        help="Root directory to scan for stem sets.",
    )
    stems_pipeline_parser.add_argument(
        "--out-dir",
        required=True,
        help="Directory for stems_index.json, stems_map.json, and stems_overrides.yaml.",
    )
    stems_pipeline_parser.add_argument(
        "--role-lexicon",
        default=None,
        help="Optional path to role lexicon extension YAML.",
    )
    stems_pipeline_parser.add_argument(
        "--no-common-lexicon",
        action="store_true",
        help="Disable built-in common role lexicon baseline.",
    )
    stems_pipeline_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing stems_overrides.yaml.",
    )
    stems_pipeline_parser.add_argument(
        "--bundle",
        default=None,
        help="Optional path to write a ui_bundle.json pointer set.",
    )

    stems_draft_parser = stems_subparsers.add_parser(
        "draft",
        help="Generate preview-only scene and routing_plan drafts from a stems_map.",
    )
    stems_draft_parser.add_argument(
        "--stems-map",
        required=True,
        help="Path to stems_map.json.",
    )
    stems_draft_parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for draft files.",
    )
    stems_draft_parser.add_argument(
        "--scene-out",
        default="scene.draft.json",
        help="Output filename for the draft scene (default: scene.draft.json).",
    )
    stems_draft_parser.add_argument(
        "--routing-out",
        default="routing_plan.draft.json",
        help="Output filename for the draft routing plan (default: routing_plan.draft.json).",
    )
    stems_draft_parser.add_argument(
        "--stems-dir",
        default="/DRAFT/stems",
        help="Absolute stems_dir for scene.source (default: /DRAFT/stems).",
    )
    stems_draft_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text).",
    )
    stems_draft_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing output files.",
    )

    stems_audition_parser = stems_subparsers.add_parser(
        "audition",
        help="Render per-bus-group audition WAV bounces from a stems_map.",
    )
    stems_audition_parser.add_argument(
        "--stems-map",
        required=True,
        help="Path to stems_map.json.",
    )
    stems_audition_parser.add_argument(
        "--stems-dir",
        required=True,
        help="Root directory where stem audio files live.",
    )
    stems_audition_parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory (auditions written to <out-dir>/stems_auditions/).",
    )
    stems_audition_parser.add_argument(
        "--segment",
        type=float,
        default=30.0,
        help="Audition segment length in seconds (default: 30).",
    )
    stems_audition_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json).",
    )
    stems_audition_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing audition outputs and manifest.",
    )

    run_parser = subparsers.add_parser(
        "run",
        help=(
            "One-shot workflow: analyze plus optional export/apply/render/bundle "
            "artifacts in one deterministic output folder."
        ),
        epilog=_RUN_COMMAND_EPILOG,
    )
    run_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    run_parser.add_argument(
        "--out",
        required=True,
        help="Path to the deterministic output directory.",
    )
    run_parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Optional preset ID from presets/index.json. May be provided multiple times.",
    )
    run_parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="Optional run config JSON path. May be provided multiple times.",
    )
    run_parser.add_argument(
        "--profile",
        default=None,
        help="Authority profile ID override.",
    )
    run_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    run_parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="max_seconds override in run_config.",
    )
    run_parser.add_argument(
        "--export-pdf",
        action="store_true",
        help="Export report PDF.",
    )
    run_parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export recall CSV.",
    )
    run_parser.add_argument(
        "--truncate-values",
        type=int,
        default=None,
        help="truncate_values override in run_config.",
    )
    run_parser.add_argument(
        "--apply",
        action="store_true",
        help="Run auto-apply renderer flow.",
    )
    run_parser.add_argument(
        "--render",
        action="store_true",
        help="Run render-eligible renderer flow.",
    )
    run_parser.add_argument(
        "--output-formats",
        default=None,
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    run_parser.add_argument(
        "--timeline",
        default=None,
        help="Optional path to a timeline JSON with section markers.",
    )
    run_parser.add_argument(
        "--bundle",
        action="store_true",
        help="Build a UI bundle JSON.",
    )
    run_parser.add_argument(
        "--scene",
        action="store_true",
        help="Build a scene.json intent artifact.",
    )
    run_parser.add_argument(
        "--render-plan",
        action="store_true",
        help="Build a render_plan.json artifact (auto-builds scene.json if needed).",
    )
    run_parser.add_argument(
        "--scene-templates",
        default=None,
        help="Comma-separated scene template IDs applied in --render-many before render-plan/variants.",
    )
    run_parser.add_argument(
        "--render-many",
        action="store_true",
        help="Mix once, then render many targets via scene/render_plan -> variants.",
    )
    run_parser.add_argument(
        "--targets",
        default=_BASELINE_RENDER_TARGET_ID,
        help=(
            "Comma-separated target IDs or aliases for --render-many "
            "(default: TARGET.STEREO.2_0)."
        ),
    )
    run_parser.add_argument(
        "--context",
        action="append",
        choices=["render", "auto_apply"],
        default=[],
        help="Repeatable context for --render-many render_plan jobs.",
    )
    run_parser.add_argument(
        "--translation",
        action="store_true",
        help=(
            "For --render-many, run translation checks when a TARGET.STEREO.2_0 "
            "deliverable exists."
        ),
    )
    run_parser.add_argument(
        "--translation-profiles",
        default=None,
        help=(
            "Comma-separated translation profile IDs for --render-many. "
            "Implies --translation."
        ),
    )
    run_parser.add_argument(
        "--translation-audition",
        action="store_true",
        help=(
            "For --render-many, write optional translation audition WAVs when a "
            "TARGET.STEREO.2_0 deliverable exists."
        ),
    )
    run_parser.add_argument(
        "--translation-audition-segment",
        type=float,
        default=_DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S,
        help="Segment duration in seconds for --translation-audition (default: 30).",
    )
    run_parser.add_argument(
        "--deliverables-index",
        action="store_true",
        help="Also write deliverables_index.json summarizing file deliverables.",
    )
    run_parser.add_argument(
        "--listen-pack",
        action="store_true",
        help="Also write listen_pack.json for musician audition guidance.",
    )
    run_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="Reuse cached analysis by lockfile + run_config hash (default: on).",
    )
    run_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    run_parser.add_argument(
        "--format-set",
        action="append",
        default=[],
        help=(
            "Repeatable output format set in <name>:<csv> form. "
            "When present, run delegates to variants mode."
        ),
    )
    run_parser.add_argument(
        "--variants",
        action="store_true",
        help="Force delegation to variants mode, even for a single preset/config.",
    )

    ui_parser = subparsers.add_parser(
        "ui",
        help="Interactive terminal launcher for musicians.",
    )
    ui_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    ui_parser.add_argument(
        "--out",
        required=True,
        help="Path to the deterministic output directory.",
    )
    ui_parser.add_argument(
        "--project",
        default=None,
        help="Optional project JSON path for lockfile and last-run context.",
    )
    ui_parser.add_argument(
        "--nerd",
        action="store_true",
        help="Show IDs, meter details, and full internal paths.",
    )

    export_parser = subparsers.add_parser(
        "export", help="Export CSV/PDF artifacts from a report JSON."
    )
    export_parser.add_argument("--report", required=True, help="Path to report JSON.")
    export_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    export_parser.add_argument("--csv", default=None, help="Optional output CSV path.")
    export_parser.add_argument("--pdf", default=None, help="Optional output PDF path.")
    export_parser.add_argument(
        "--no-measurements",
        action="store_true",
        help="Omit Measurements section from PDF output.",
    )
    export_parser.add_argument(
        "--no-gates",
        action="store_true",
        help="Omit gate fields/sections from exports.",
    )
    export_parser.add_argument(
        "--truncate-values",
        type=int,
        default=200,
        help="Truncate PDF cell values to this length.",
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare two reports (or report folders) and summarize what changed.",
    )
    compare_parser.add_argument(
        "--a",
        required=True,
        help="Path to side A report JSON, or a directory containing report.json.",
    )
    compare_parser.add_argument(
        "--b",
        required=True,
        help="Path to side B report JSON, or a directory containing report.json.",
    )
    compare_parser.add_argument(
        "--out",
        required=True,
        help="Path to output compare_report JSON.",
    )
    compare_parser.add_argument(
        "--pdf",
        default=None,
        help="Optional output compare_report PDF path.",
    )

    render_parser = subparsers.add_parser(
        "render",
        help="Run renderer plugins for render-eligible recommendations.",
    )
    render_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    render_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    render_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    render_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    render_parser.add_argument(
        "--out-manifest",
        required=True,
        help="Path to output render manifest JSON.",
    )
    render_parser.add_argument(
        "--out-dir",
        default=None,
        help=(
            "Optional output directory for renderer artifacts. "
            "Required for plugins that produce real render files."
        ),
    )
    render_parser.add_argument(
        "--output-formats",
        default=None,
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    render_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for render gating (default: PROFILE.ASSIST).",
    )
    render_parser.add_argument(
        "--source-layout",
        default=None,
        help="downmix.source_layout_id override in run_config.",
    )
    render_parser.add_argument(
        "--target-layout",
        default=None,
        help="downmix.target_layout_id override in run_config.",
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help="Run renderer plugins for auto-apply eligible recommendations.",
    )
    apply_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    apply_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    apply_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    apply_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    apply_parser.add_argument(
        "--out-manifest",
        required=True,
        help="Path to output apply manifest JSON.",
    )
    apply_parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for applied renderer artifacts.",
    )
    apply_parser.add_argument(
        "--output-formats",
        default=None,
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    apply_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for auto-apply gating (default: PROFILE.ASSIST).",
    )
    apply_parser.add_argument(
        "--source-layout",
        default=None,
        help="downmix.source_layout_id override in run_config.",
    )
    apply_parser.add_argument(
        "--target-layout",
        default=None,
        help="downmix.target_layout_id override in run_config.",
    )
    apply_parser.add_argument(
        "--out-report",
        default=None,
        help=(
            "Optional output path for a report JSON rewritten to point stems to "
            "applied artifacts."
        ),
    )

    bundle_parser = subparsers.add_parser(
        "bundle",
        help=(
            "Build a single UI bundle JSON from report + optional render/apply manifests "
            "and optional applied report."
        ),
    )
    bundle_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    bundle_parser.add_argument(
        "--render-manifest",
        default=None,
        help="Optional path to render manifest JSON.",
    )
    bundle_parser.add_argument(
        "--apply-manifest",
        default=None,
        help="Optional path to apply manifest JSON.",
    )
    bundle_parser.add_argument(
        "--applied-report",
        default=None,
        help="Optional path to applied report JSON.",
    )
    bundle_parser.add_argument(
        "--project",
        default=None,
        help="Optional path to project JSON for embedding project summary metadata.",
    )
    bundle_parser.add_argument(
        "--deliverables-index",
        default=None,
        help="Optional path to deliverables_index JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--listen-pack",
        default=None,
        help="Optional path to listen_pack JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--scene",
        default=None,
        help="Optional path to scene JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--render-plan",
        default=None,
        help="Optional path to render_plan JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--stems-index",
        default=None,
        help="Optional path to stems_index JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--stems-map",
        default=None,
        help="Optional path to stems_map JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--gui-state",
        default=None,
        help="Optional path to gui_state JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--render-request",
        default=None,
        help="Optional path to render_request JSON artifact.",
    )
    bundle_parser.add_argument(
        "--render-report",
        default=None,
        help="Optional path to render_report JSON artifact.",
    )
    bundle_parser.add_argument(
        "--ui-locale",
        default=None,
        help="Optional UI copy locale (default: registry default_locale).",
    )
    bundle_parser.add_argument(
        "--out",
        required=True,
        help="Path to output UI bundle JSON.",
    )

    variants_parser = subparsers.add_parser(
        "variants",
        help="Run multiple deterministic variants in one command.",
    )
    variants_subparsers = variants_parser.add_subparsers(
        dest="variants_command",
        required=True,
    )
    variants_run_parser = variants_subparsers.add_parser(
        "run",
        help="Run one or more preset/config variants and write deterministic artifacts.",
    )
    variants_run_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    variants_run_parser.add_argument(
        "--out",
        required=True,
        help="Path to the output directory for all variant artifacts.",
    )
    variants_run_parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Optional preset ID; may be provided multiple times.",
    )
    variants_run_parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="Optional run config JSON path; may be provided multiple times.",
    )
    variants_run_parser.add_argument(
        "--apply",
        action="store_true",
        help="Run auto-apply renderer flow for each variant.",
    )
    variants_run_parser.add_argument(
        "--render",
        action="store_true",
        help="Run render-eligible renderer flow for each variant.",
    )
    variants_run_parser.add_argument(
        "--export-pdf",
        action="store_true",
        help="Export report PDF for each variant.",
    )
    variants_run_parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export report CSV for each variant.",
    )
    variants_run_parser.add_argument(
        "--bundle",
        action="store_true",
        help="Build a UI bundle for each variant.",
    )
    variants_run_parser.add_argument(
        "--scene",
        action="store_true",
        help="Build a scene.json intent artifact for each variant.",
    )
    variants_run_parser.add_argument(
        "--render-plan",
        action="store_true",
        help="Build a render_plan.json artifact for each variant (auto-builds scene.json).",
    )
    variants_run_parser.add_argument(
        "--listen-pack",
        action="store_true",
        help="Also write listen_pack.json for musician audition guidance.",
    )
    variants_run_parser.add_argument(
        "--deliverables-index",
        action="store_true",
        help="Also write deliverables_index.json for all variant outputs.",
    )
    variants_run_parser.add_argument(
        "--profile",
        default=None,
        help="Authority profile ID override for each variant.",
    )
    variants_run_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    variants_run_parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="max_seconds override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--routing",
        action="store_true",
        help="Build and persist routing_plan for each variant.",
    )
    variants_run_parser.add_argument(
        "--target-layout",
        default=None,
        help="downmix.target_layout_id override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--source-layout",
        default=None,
        help="downmix.source_layout_id override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--policy-id",
        default=None,
        help="downmix.policy_id override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--downmix-qa",
        action="store_true",
        help="Run downmix QA for each variant after analyze and merge into report.",
    )
    variants_run_parser.add_argument(
        "--qa-ref",
        default=None,
        help="Path to stereo QA reference used when --downmix-qa is enabled.",
    )
    variants_run_parser.add_argument(
        "--qa-meters",
        choices=["basic", "truth"],
        default=None,
        help="Meter pack for downmix QA (basic or truth).",
    )
    variants_run_parser.add_argument(
        "--qa-max-seconds",
        type=float,
        default=None,
        help="max_seconds override for downmix QA only.",
    )
    variants_run_parser.add_argument(
        "--truncate-values",
        type=int,
        default=None,
        help="truncate_values override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--output-formats",
        default=None,
        help=(
            "Comma-separated lossless output formats (wav,flac,wv,aiff,alac) "
            "for both render and apply variant steps."
        ),
    )
    variants_run_parser.add_argument(
        "--render-output-formats",
        default=None,
        help="Comma-separated lossless output formats for render variant steps.",
    )
    variants_run_parser.add_argument(
        "--apply-output-formats",
        default=None,
        help="Comma-separated lossless output formats for apply variant steps.",
    )
    variants_run_parser.add_argument(
        "--format-set",
        action="append",
        default=[],
        help=(
            "Repeatable output format set in <name>:<csv> form. "
            "Each set expands every base variant into a deterministic sub-variant."
        ),
    )
    variants_run_parser.add_argument(
        "--timeline",
        default=None,
        help="Optional path to a timeline JSON with section markers.",
    )
    variants_run_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="Reuse cached analysis by lockfile + run_config hash (default: on).",
    )
    variants_run_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    variants_listen_pack_parser = variants_subparsers.add_parser(
        "listen-pack",
        help="Build a deterministic listen pack index from a variant_result JSON.",
    )
    variants_listen_pack_parser.add_argument(
        "--variant-result",
        required=True,
        help="Path to variant_result JSON.",
    )
    variants_listen_pack_parser.add_argument(
        "--out",
        required=True,
        help="Path to output listen_pack JSON.",
    )
    variants_listen_pack_parser.add_argument(
        "--stems-auditions-manifest",
        default=None,
        help="Optional path to stems audition manifest.json to index.",
    )

    deliverables_parser = subparsers.add_parser(
        "deliverables",
        help="Deliverables index tools.",
    )
    deliverables_subparsers = deliverables_parser.add_subparsers(
        dest="deliverables_command",
        required=True,
    )
    deliverables_index_parser = deliverables_subparsers.add_parser(
        "index",
        help="Build a deterministic deliverables index JSON.",
    )
    deliverables_index_parser.add_argument(
        "--out-dir",
        required=True,
        help="Path to output directory that contains run artifacts.",
    )
    deliverables_index_parser.add_argument(
        "--out",
        required=True,
        help="Path to output deliverables_index JSON.",
    )
    deliverables_index_parser.add_argument(
        "--variant-result",
        default=None,
        help="Optional variant_result JSON path (switches to variants mode).",
    )

    plugins_parser = subparsers.add_parser("plugins", help="Plugin registry tools.")
    plugins_subparsers = plugins_parser.add_subparsers(dest="plugins_command", required=True)
    plugins_list_parser = plugins_subparsers.add_parser(
        "list",
        help="List discovered plugins and capability metadata.",
    )
    plugins_list_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    plugins_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the plugin list.",
    )

    presets_parser = subparsers.add_parser("presets", help="Run config preset tools.")
    presets_subparsers = presets_parser.add_subparsers(dest="presets_command", required=True)
    presets_list_parser = presets_subparsers.add_parser("list", help="List available presets.")
    presets_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the preset list.",
    )
    presets_list_parser.add_argument(
        "--tag",
        default=None,
        help="Optional tag filter (matches entries in tags).",
    )
    presets_list_parser.add_argument(
        "--category",
        default=None,
        help="Optional category filter (e.g., VIBE, WORKFLOW).",
    )
    presets_show_parser = presets_subparsers.add_parser("show", help="Show one preset.")
    presets_show_parser.add_argument(
        "preset_id",
        help="Preset ID (e.g., PRESET.SAFE_CLEANUP).",
    )
    presets_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for preset details.",
    )
    presets_preview_parser = presets_subparsers.add_parser(
        "preview",
        help="Preview musician guidance and merged run_config changes for a preset.",
    )
    presets_preview_parser.add_argument(
        "preset_id",
        help="Preset ID (e.g., PRESET.SAFE_CLEANUP).",
    )
    presets_preview_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    presets_preview_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for preview details.",
    )
    presets_preview_parser.add_argument(
        "--profile",
        default=_PRESET_PREVIEW_DEFAULT_PROFILE_ID,
        help=(
            "Profile override for previewed merge results "
            f"(default: {_PRESET_PREVIEW_DEFAULT_PROFILE_ID})."
        ),
    )
    presets_preview_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=_PRESET_PREVIEW_DEFAULT_METERS,
        help=(
            "Meters override for previewed merge results "
            f"(default: {_PRESET_PREVIEW_DEFAULT_METERS})."
        ),
    )
    presets_preview_parser.add_argument(
        "--max-seconds",
        type=float,
        default=_PRESET_PREVIEW_DEFAULT_MAX_SECONDS,
        help=(
            "max_seconds override for previewed merge results "
            f"(default: {_PRESET_PREVIEW_DEFAULT_MAX_SECONDS})."
        ),
    )
    presets_preview_parser.add_argument(
        "--source-layout",
        default=None,
        help="downmix.source_layout_id override for previewed merge results.",
    )
    presets_preview_parser.add_argument(
        "--target-layout",
        default=_PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID,
        help=(
            "downmix.target_layout_id override for previewed merge results "
            f"(default: {_PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID})."
        ),
    )
    presets_preview_parser.add_argument(
        "--policy-id",
        default=None,
        help="downmix.policy_id override for previewed merge results.",
    )
    presets_recommend_parser = presets_subparsers.add_parser(
        "recommend",
        help="Recommend presets from report vibe and safety signals.",
    )
    presets_recommend_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON used for deriving recommendations.",
    )
    presets_recommend_parser.add_argument(
        "--n",
        type=int,
        default=3,
        help="Number of presets to suggest (default: 3).",
    )
    presets_recommend_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for recommendation details.",
    )
    presets_packs_parser = presets_subparsers.add_parser(
        "packs",
        help="List and inspect preset packs.",
    )
    presets_packs_subparsers = presets_packs_parser.add_subparsers(
        dest="presets_packs_command",
        required=True,
    )
    presets_packs_list_parser = presets_packs_subparsers.add_parser(
        "list",
        help="List preset packs.",
    )
    presets_packs_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the preset pack list.",
    )
    presets_packs_show_parser = presets_packs_subparsers.add_parser(
        "show",
        help="Show one preset pack.",
    )
    presets_packs_show_parser.add_argument(
        "pack_id",
        help="Pack ID (e.g., PACK.VIBE_STARTER).",
    )
    presets_packs_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for preset pack details.",
    )

    help_parser = subparsers.add_parser("help", help="Registry help tools.")
    help_subparsers = help_parser.add_subparsers(dest="help_command", required=True)
    help_list_parser = help_subparsers.add_parser("list", help="List help entries.")
    help_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the help list.",
    )
    help_show_parser = help_subparsers.add_parser("show", help="Show one help entry.")
    help_show_parser.add_argument(
        "help_id",
        help="Help ID (e.g., HELP.PRESET.SAFE_CLEANUP).",
    )
    help_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for help details.",
    )

    targets_parser = subparsers.add_parser("targets", help="Render target registry tools.")
    targets_subparsers = targets_parser.add_subparsers(dest="targets_command", required=True)
    targets_list_parser = targets_subparsers.add_parser("list", help="List render targets.")
    targets_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the render target list.",
    )
    targets_list_parser.add_argument(
        "--long",
        action="store_true",
        help="Show notes and aliases in text output.",
    )
    targets_show_parser = targets_subparsers.add_parser("show", help="Show one render target.")
    targets_show_parser.add_argument(
        "target_id",
        help="Render target ID or alias (e.g., TARGET.STEREO.2_0, Stereo (streaming)).",
    )
    targets_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for render target details.",
    )
    targets_recommend_parser = targets_subparsers.add_parser(
        "recommend",
        help="Recommend conservative render targets from report and scene signals.",
    )
    targets_recommend_parser.add_argument(
        "--report",
        default=None,
        help="Path to report JSON, or a directory containing report.json.",
    )
    targets_recommend_parser.add_argument(
        "--scene",
        default=None,
        help="Optional path to scene JSON.",
    )
    targets_recommend_parser.add_argument(
        "--max",
        dest="max_results",
        type=int,
        default=3,
        help="Maximum number of target recommendations to return (default: 3).",
    )
    targets_recommend_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for recommended targets.",
    )

    roles_parser = subparsers.add_parser("roles", help="Role registry tools.")
    roles_subparsers = roles_parser.add_subparsers(dest="roles_command", required=True)
    roles_list_parser = roles_subparsers.add_parser("list", help="List role IDs.")
    roles_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for role list.",
    )
    roles_show_parser = roles_subparsers.add_parser("show", help="Show one role entry.")
    roles_show_parser.add_argument(
        "role_id",
        help="Role ID (e.g., ROLE.BASS.AMP).",
    )
    roles_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for role details.",
    )

    translation_parser = subparsers.add_parser(
        "translation",
        help="Translation profile registry tools.",
    )
    translation_subparsers = translation_parser.add_subparsers(
        dest="translation_command",
        required=True,
    )
    translation_list_parser = translation_subparsers.add_parser(
        "list",
        help="List translation profiles.",
    )
    translation_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for translation profile list.",
    )
    translation_show_parser = translation_subparsers.add_parser(
        "show",
        help="Show one translation profile.",
    )
    translation_show_parser.add_argument(
        "profile_id",
        help="Translation profile ID (e.g., TRANS.MONO.COLLAPSE).",
    )
    translation_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for translation profile details.",
    )
    translation_run_parser = translation_subparsers.add_parser(
        "run",
        help="Run deterministic meter-only translation checks from a WAV file.",
    )
    translation_run_parser.add_argument(
        "--audio",
        required=True,
        help="Path to mono/stereo WAV input.",
    )
    translation_run_parser.add_argument(
        "--profiles",
        required=True,
        help="Comma-separated translation profile IDs.",
    )
    translation_run_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for translation check results.",
    )
    translation_run_parser.add_argument(
        "--out",
        default=None,
        help="Optional output JSON path for translation_results list.",
    )
    translation_run_parser.add_argument(
        "--report-in",
        default=None,
        help="Optional input report JSON path to patch translation_results.",
    )
    translation_run_parser.add_argument(
        "--report-out",
        default=None,
        help="Output report JSON path for patched translation_results.",
    )
    translation_run_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable deterministic translation check caching.",
    )
    translation_run_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    translation_compare_parser = translation_subparsers.add_parser(
        "compare",
        help="Run deterministic translation checks across multiple WAV inputs.",
    )
    translation_compare_audio_group = translation_compare_parser.add_mutually_exclusive_group(
        required=True
    )
    translation_compare_audio_group.add_argument(
        "--audio",
        default=None,
        help="Comma-separated WAV paths to compare.",
    )
    translation_compare_audio_group.add_argument(
        "--in-dir",
        default=None,
        help="Directory containing WAV files for comparison.",
    )
    translation_compare_parser.add_argument(
        "--glob",
        default="*.wav",
        help="Optional glob pattern for --in-dir discovery (default: *.wav).",
    )
    translation_compare_parser.add_argument(
        "--profiles",
        required=True,
        help="Comma-separated translation profile IDs.",
    )
    translation_compare_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for translation compare rows.",
    )
    translation_audition_parser = translation_subparsers.add_parser(
        "audition",
        help="Render deterministic translation audition WAVs from a WAV file.",
    )
    translation_audition_parser.add_argument(
        "--audio",
        required=True,
        help="Path to mono/stereo WAV input.",
    )
    translation_audition_parser.add_argument(
        "--profiles",
        required=True,
        help="Comma-separated translation profile IDs.",
    )
    translation_audition_parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory root for translation_auditions artifacts.",
    )
    translation_audition_parser.add_argument(
        "--segment",
        type=float,
        default=None,
        help="Optional segment duration in seconds (from start).",
    )
    translation_audition_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable deterministic translation audition caching.",
    )
    translation_audition_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )

    locks_parser = subparsers.add_parser("locks", help="Scene lock registry tools.")
    locks_subparsers = locks_parser.add_subparsers(dest="locks_command", required=True)
    locks_list_parser = locks_subparsers.add_parser("list", help="List scene locks.")
    locks_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the scene lock list.",
    )
    locks_show_parser = locks_subparsers.add_parser("show", help="Show one scene lock.")
    locks_show_parser.add_argument(
        "lock_id",
        help="Scene lock ID (e.g., LOCK.PRESERVE_DYNAMICS).",
    )
    locks_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene lock details.",
    )

    ui_copy_parser = subparsers.add_parser("ui-copy", help="UI copy registry tools.")
    ui_copy_subparsers = ui_copy_parser.add_subparsers(
        dest="ui_copy_command",
        required=True,
    )
    ui_copy_list_parser = ui_copy_subparsers.add_parser(
        "list",
        help="List UI copy entries.",
    )
    ui_copy_list_parser.add_argument(
        "--locale",
        default=None,
        help="Optional locale (default: registry default_locale).",
    )
    ui_copy_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for UI copy list.",
    )
    ui_copy_show_parser = ui_copy_subparsers.add_parser(
        "show",
        help="Show one UI copy entry.",
    )
    ui_copy_show_parser.add_argument(
        "copy_id",
        help="Copy key (e.g., COPY.NAV.DASHBOARD).",
    )
    ui_copy_show_parser.add_argument(
        "--locale",
        default=None,
        help="Optional locale (default: registry default_locale).",
    )
    ui_copy_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for UI copy details.",
    )

    ui_examples_parser = subparsers.add_parser(
        "ui-examples",
        help="Mock UI screen example tools.",
    )
    ui_examples_subparsers = ui_examples_parser.add_subparsers(
        dest="ui_examples_command",
        required=True,
    )
    ui_examples_list_parser = ui_examples_subparsers.add_parser(
        "list",
        help="List available UI screen examples.",
    )
    ui_examples_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for UI example list.",
    )
    ui_examples_show_parser = ui_examples_subparsers.add_parser(
        "show",
        help="Show one UI screen example.",
    )
    ui_examples_show_parser.add_argument(
        "filename",
        help="Example filename (for example dashboard_default_safe.json).",
    )
    ui_examples_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for UI example details.",
    )

    lock_parser = subparsers.add_parser("lock", help="Project lockfile tools.")
    lock_subparsers = lock_parser.add_subparsers(dest="lock_command", required=True)
    lock_write_parser = lock_subparsers.add_parser(
        "write", help="Write a deterministic lockfile for a stems directory."
    )
    lock_write_parser.add_argument("stems_dir", help="Path to a directory of input files.")
    lock_write_parser.add_argument(
        "--out",
        required=True,
        help="Path to output lockfile JSON.",
    )
    lock_verify_parser = lock_subparsers.add_parser(
        "verify", help="Verify a stems directory against a lockfile."
    )
    lock_verify_parser.add_argument("stems_dir", help="Path to a directory of input files.")
    lock_verify_parser.add_argument(
        "--lock",
        required=True,
        help="Path to lockfile JSON.",
    )
    lock_verify_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path for verification result JSON.",
    )

    project_parser = subparsers.add_parser("project", help="Project file tools.")
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)
    project_new_parser = project_subparsers.add_parser(
        "new",
        help="Create a new MMO project file.",
    )
    project_new_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    project_new_parser.add_argument(
        "--out",
        required=True,
        help="Path to output project JSON.",
    )
    project_new_parser.add_argument(
        "--notes",
        default=None,
        help="Optional project notes string.",
    )

    project_show_parser = project_subparsers.add_parser(
        "show",
        help="Display one project file.",
    )
    project_show_parser.add_argument(
        "--project",
        required=True,
        help="Path to a project JSON file.",
    )
    project_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for project display.",
    )

    project_run_parser = project_subparsers.add_parser(
        "run",
        help="Run workflow from a project file and update the project in place.",
    )
    project_run_parser.add_argument(
        "--project",
        required=True,
        help="Path to a project JSON file.",
    )
    project_run_parser.add_argument(
        "--out",
        required=True,
        help="Path to the deterministic output directory.",
    )
    project_run_parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Optional preset ID from presets/index.json. May be provided multiple times.",
    )
    project_run_parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="Optional run config JSON path. May be provided multiple times.",
    )
    project_run_parser.add_argument(
        "--profile",
        default=None,
        help="Authority profile ID override.",
    )
    project_run_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    project_run_parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="max_seconds override in run_config.",
    )
    project_run_parser.add_argument(
        "--export-pdf",
        action="store_true",
        help="Export report PDF.",
    )
    project_run_parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export recall CSV.",
    )
    project_run_parser.add_argument(
        "--truncate-values",
        type=int,
        default=None,
        help="truncate_values override in run_config.",
    )
    project_run_parser.add_argument(
        "--apply",
        action="store_true",
        help="Run auto-apply renderer flow.",
    )
    project_run_parser.add_argument(
        "--render",
        action="store_true",
        help="Run render-eligible renderer flow.",
    )
    project_run_parser.add_argument(
        "--output-formats",
        default=None,
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    project_run_parser.add_argument(
        "--timeline",
        default=None,
        help="Optional path to a timeline JSON with section markers.",
    )
    project_run_parser.add_argument(
        "--bundle",
        action="store_true",
        help="Build a UI bundle JSON.",
    )
    project_run_parser.add_argument(
        "--scene",
        action="store_true",
        help="Build a scene.json intent artifact.",
    )
    project_run_parser.add_argument(
        "--render-plan",
        action="store_true",
        help="Build a render_plan.json artifact (auto-builds scene.json if needed).",
    )
    project_run_parser.add_argument(
        "--scene-templates",
        default=None,
        help="Comma-separated scene template IDs applied in --render-many before render-plan/variants.",
    )
    project_run_parser.add_argument(
        "--render-many",
        action="store_true",
        help="Mix once, then render many targets via scene/render_plan -> variants.",
    )
    project_run_parser.add_argument(
        "--targets",
        default=_BASELINE_RENDER_TARGET_ID,
        help=(
            "Comma-separated target IDs or aliases for --render-many "
            "(default: TARGET.STEREO.2_0)."
        ),
    )
    project_run_parser.add_argument(
        "--context",
        action="append",
        choices=["render", "auto_apply"],
        default=[],
        help="Repeatable context for --render-many render_plan jobs.",
    )
    project_run_parser.add_argument(
        "--translation",
        action="store_true",
        help=(
            "For --render-many, run translation checks when a TARGET.STEREO.2_0 "
            "deliverable exists."
        ),
    )
    project_run_parser.add_argument(
        "--translation-profiles",
        default=None,
        help=(
            "Comma-separated translation profile IDs for --render-many. "
            "Implies --translation."
        ),
    )
    project_run_parser.add_argument(
        "--translation-audition",
        action="store_true",
        help=(
            "For --render-many, write optional translation audition WAVs when a "
            "TARGET.STEREO.2_0 deliverable exists."
        ),
    )
    project_run_parser.add_argument(
        "--translation-audition-segment",
        type=float,
        default=_DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S,
        help="Segment duration in seconds for --translation-audition (default: 30).",
    )
    project_run_parser.add_argument(
        "--deliverables-index",
        action="store_true",
        help="Also write deliverables_index.json summarizing file deliverables.",
    )
    project_run_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="Reuse cached analysis by lockfile + run_config hash (default: on).",
    )
    project_run_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    project_run_parser.add_argument(
        "--format-set",
        action="append",
        default=[],
        help=(
            "Repeatable output format set in <name>:<csv> form. "
            "When present, run delegates to variants mode."
        ),
    )
    project_run_parser.add_argument(
        "--variants",
        action="store_true",
        help="Force delegation to variants mode, even for a single preset/config.",
    )

    project_init_parser = project_subparsers.add_parser(
        "init",
        help="Scaffold a project from a stems folder (pipeline + drafts + bundle).",
    )
    project_init_parser.add_argument(
        "--stems-root",
        required=True,
        help="Root directory to scan for stem sets.",
    )
    project_init_parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for the project scaffold.",
    )
    project_init_parser.add_argument(
        "--role-lexicon",
        default=None,
        help="Optional path to role lexicon extension YAML.",
    )
    project_init_parser.add_argument(
        "--no-common-lexicon",
        action="store_true",
        help="Disable built-in common role lexicon baseline.",
    )
    project_init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing init outputs (allowlisted files only).",
    )
    project_init_parser.add_argument(
        "--bundle",
        default=None,
        help="Optional path to write a pointer bundle JSON.",
    )
    project_init_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json).",
    )

    project_refresh_parser = project_subparsers.add_parser(
        "refresh",
        help="Re-run stems pipeline and drafts for an existing project scaffold.",
    )
    project_refresh_parser.add_argument(
        "--project-dir", required=True,
        help="Path to existing project scaffold directory.",
    )
    project_refresh_parser.add_argument(
        "--stems-root", default=None,
        help="Root directory to scan for stem sets (default: <project-dir>/stems_source/ if present).",
    )
    project_refresh_parser.add_argument(
        "--role-lexicon", default=None,
        help="Optional path to role lexicon extension YAML.",
    )
    project_refresh_parser.add_argument(
        "--no-common-lexicon", action="store_true",
        help="Disable built-in common role lexicon baseline.",
    )
    project_refresh_parser.add_argument(
        "--force", action="store_true",
        help="Overwrite stems_overrides.yaml (normally preserved).",
    )
    project_refresh_parser.add_argument(
        "--format", choices=["json", "text"], default="json",
        help="Output format (default: json).",
    )

    project_validate_parser = project_subparsers.add_parser(
        "validate",
        help="Validate project scaffold files against their schemas.",
    )
    project_validate_parser.add_argument(
        "project_dir",
        help="Path to the project scaffold directory.",
    )
    project_validate_parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write validation result JSON.",
    )

    project_pack_parser = project_subparsers.add_parser(
        "pack",
        help="Pack project artifacts into a deterministic zip.",
    )
    project_pack_parser.add_argument(
        "project_dir",
        help="Path to the project scaffold directory.",
    )
    project_pack_parser.add_argument(
        "--out",
        required=True,
        help="Path to output zip file.",
    )
    project_pack_parser.add_argument(
        "--include-wavs",
        action="store_true",
        help="Include audition WAV files in the zip.",
    )
    project_pack_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output zip.",
    )

    downmix_parser = subparsers.add_parser("downmix", help="Downmix policy tools.")
    downmix_subparsers = downmix_parser.add_subparsers(dest="downmix_command", required=True)
    downmix_show_parser = downmix_subparsers.add_parser(
        "show", help="Resolve and display a downmix matrix."
    )
    downmix_show_parser.add_argument(
        "--source",
        required=True,
        help="Source layout ID (e.g., LAYOUT.5_1).",
    )
    downmix_show_parser.add_argument(
        "--target",
        required=True,
        help="Target layout ID (e.g., LAYOUT.2_0).",
    )
    downmix_show_parser.add_argument(
        "--policy",
        default=None,
        help=(
            "Optional policy ID override (e.g., POLICY.DOWNMIX.STANDARD_FOLDOWN_V0). "
            "See `mmo downmix list --policies` for available IDs."
        ),
    )
    downmix_show_parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format for the resolved matrix.",
    )
    downmix_show_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path; defaults to stdout.",
    )
    downmix_qa_parser = downmix_subparsers.add_parser(
        "qa", help="Compare folded downmix against a stereo reference."
    )
    downmix_qa_parser.add_argument(
        "--src",
        required=True,
        help="Path to the multichannel source file.",
    )
    downmix_qa_parser.add_argument(
        "--ref",
        required=True,
        help="Path to the stereo reference file.",
    )
    downmix_qa_parser.add_argument(
        "--source-layout",
        default=None,
        help="Source layout ID (e.g., LAYOUT.5_1).",
    )
    downmix_qa_parser.add_argument(
        "--target-layout",
        default="LAYOUT.2_0",
        help="Target layout ID for the fold-down (default: LAYOUT.2_0).",
    )
    downmix_qa_parser.add_argument(
        "--policy",
        default=None,
        help=(
            "Optional policy ID override (e.g., POLICY.DOWNMIX.STANDARD_FOLDOWN_V0). "
            "See `mmo downmix list --policies` for available IDs."
        ),
    )
    downmix_qa_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default="truth",
        help="Meter pack to use (basic or truth).",
    )
    downmix_qa_parser.add_argument(
        "--tolerance-lufs",
        type=float,
        default=1.0,
        help="LUFS delta tolerance for QA warnings.",
    )
    downmix_qa_parser.add_argument(
        "--tolerance-true-peak",
        type=float,
        default=1.0,
        help="True peak delta tolerance (dBTP) for QA warnings.",
    )
    downmix_qa_parser.add_argument(
        "--tolerance-corr",
        type=float,
        default=0.15,
        help="Correlation delta tolerance for QA warnings.",
    )
    downmix_qa_parser.add_argument(
        "--max-seconds",
        type=float,
        default=120.0,
        help="Maximum overlap seconds to compare (<= 0 disables the cap).",
    )
    downmix_qa_parser.add_argument(
        "--format",
        choices=["json", "csv", "pdf"],
        default="json",
        help="Output format for downmix QA results.",
    )
    downmix_qa_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path; defaults to stdout for json/csv.",
    )
    downmix_qa_parser.add_argument(
        "--truncate-values",
        type=int,
        default=200,
        help="Truncate PDF values to this length.",
    )
    downmix_qa_parser.add_argument(
        "--emit-report",
        default=None,
        help="Optional output path for a full MMO report JSON embedding downmix QA.",
    )
    downmix_qa_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help=(
            "Authority profile ID used for gate eligibility when --emit-report is set "
            "(default: PROFILE.ASSIST)."
        ),
    )
    downmix_qa_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    downmix_qa_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    downmix_list_parser = downmix_subparsers.add_parser(
        "list", help="List available downmix layouts, policies, and conversions."
    )
    downmix_list_parser.add_argument(
        "--layouts",
        action="store_true",
        help="Show available layout IDs.",
    )
    downmix_list_parser.add_argument(
        "--policies",
        action="store_true",
        help="Show available policy IDs.",
    )
    downmix_list_parser.add_argument(
        "--conversions",
        action="store_true",
        help="Show available conversions and policy coverage.",
    )
    downmix_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the list.",
    )
    downmix_render_parser = downmix_subparsers.add_parser(
        "render", help="Run renderer plugins for render-eligible recommendations."
    )
    downmix_render_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    downmix_render_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    downmix_render_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    downmix_render_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    downmix_render_parser.add_argument(
        "--out-manifest",
        required=True,
        help="Path to output render manifest JSON.",
    )
    downmix_render_parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional output directory for renderer artifacts.",
    )
    downmix_render_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for render gating (default: PROFILE.ASSIST).",
    )

    routing_parser = subparsers.add_parser("routing", help="Layout-aware routing tools.")
    routing_subparsers = routing_parser.add_subparsers(dest="routing_command", required=True)
    routing_show_parser = routing_subparsers.add_parser(
        "show", help="Build and display a deterministic stem routing plan."
    )
    routing_show_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    routing_show_parser.add_argument(
        "--source-layout",
        required=True,
        help="Source layout ID (e.g., LAYOUT.5_1).",
    )
    routing_show_parser.add_argument(
        "--target-layout",
        required=True,
        help="Target layout ID (e.g., LAYOUT.2_0).",
    )
    routing_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format for routing plan.",
    )

    scene_parser = subparsers.add_parser("scene", help="Scene intent artifact tools.")
    scene_subparsers = scene_parser.add_subparsers(
        dest="scene_command",
        required=True,
    )
    scene_build_parser = scene_subparsers.add_parser(
        "build",
        help="Build a deterministic scene JSON from a report and optional timeline.",
    )
    scene_build_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    scene_build_parser.add_argument(
        "--timeline",
        default=None,
        help="Optional path to timeline JSON.",
    )
    scene_build_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )
    scene_build_parser.add_argument(
        "--templates",
        default=None,
        help="Optional comma-separated scene template IDs to apply in order.",
    )
    scene_build_parser.add_argument(
        "--force-templates",
        action="store_true",
        help="When used with --templates, overwrite existing intent fields (hard locks still apply).",
    )
    scene_show_parser = scene_subparsers.add_parser(
        "show",
        help="Display a scene JSON.",
    )
    scene_show_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene display.",
    )
    scene_validate_parser = scene_subparsers.add_parser(
        "validate",
        help="Validate a scene JSON against schema.",
    )
    scene_validate_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_locks_parser = scene_subparsers.add_parser(
        "locks",
        help="Edit scene locks.",
    )
    scene_locks_subparsers = scene_locks_parser.add_subparsers(
        dest="scene_locks_command",
        required=True,
    )
    scene_locks_add_parser = scene_locks_subparsers.add_parser(
        "add",
        help="Add a lock to scene/object/bed intent.",
    )
    scene_locks_add_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_locks_add_parser.add_argument(
        "--scope",
        choices=["scene", "object", "bed"],
        required=True,
        help="Lock scope.",
    )
    scene_locks_add_parser.add_argument(
        "--id",
        default=None,
        help="object_id or bed_id for non-scene scopes.",
    )
    scene_locks_add_parser.add_argument(
        "--lock",
        required=True,
        help="Lock ID from ontology/scene_locks.yaml.",
    )
    scene_locks_add_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )
    scene_locks_remove_parser = scene_locks_subparsers.add_parser(
        "remove",
        help="Remove a lock from scene/object/bed intent.",
    )
    scene_locks_remove_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_locks_remove_parser.add_argument(
        "--scope",
        choices=["scene", "object", "bed"],
        required=True,
        help="Lock scope.",
    )
    scene_locks_remove_parser.add_argument(
        "--id",
        default=None,
        help="object_id or bed_id for non-scene scopes.",
    )
    scene_locks_remove_parser.add_argument(
        "--lock",
        required=True,
        help="Lock ID from ontology/scene_locks.yaml.",
    )
    scene_locks_remove_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )

    scene_intent_parser = scene_subparsers.add_parser(
        "intent",
        help="View and edit scene intent fields.",
    )
    scene_intent_subparsers = scene_intent_parser.add_subparsers(
        dest="scene_intent_command",
        required=True,
    )
    scene_intent_set_parser = scene_intent_subparsers.add_parser(
        "set",
        help="Set one scene intent field for scene/object/bed.",
    )
    scene_intent_set_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_intent_set_parser.add_argument(
        "--scope",
        choices=["scene", "object", "bed"],
        required=True,
        help="Intent scope.",
    )
    scene_intent_set_parser.add_argument(
        "--id",
        default=None,
        help="object_id or bed_id for non-scene scopes.",
    )
    scene_intent_set_parser.add_argument(
        "--key",
        choices=list(_SCENE_INTENT_KEYS),
        required=True,
        help="Intent field key.",
    )
    scene_intent_set_parser.add_argument(
        "--value",
        required=True,
        help="Intent field value.",
    )
    scene_intent_set_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )
    scene_intent_show_parser = scene_intent_subparsers.add_parser(
        "show",
        help="Show scene/object/bed intent sections.",
    )
    scene_intent_show_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_intent_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene intent display.",
    )
    scene_template_parser = scene_subparsers.add_parser(
        "template",
        help="Scene template registry and apply tools.",
    )
    scene_template_subparsers = scene_template_parser.add_subparsers(
        dest="scene_template_command",
        required=True,
    )
    scene_template_list_parser = scene_template_subparsers.add_parser(
        "list",
        help="List scene templates.",
    )
    scene_template_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene template list.",
    )
    scene_template_show_parser = scene_template_subparsers.add_parser(
        "show",
        help="Show one or more scene templates.",
    )
    scene_template_show_parser.add_argument(
        "template_ids",
        nargs="+",
        help="Scene template ID(s) (e.g., TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER).",
    )
    scene_template_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene template details.",
    )
    scene_template_apply_parser = scene_template_subparsers.add_parser(
        "apply",
        help="Apply one or more templates to a scene JSON.",
    )
    scene_template_apply_parser.add_argument(
        "template_ids",
        nargs="+",
        help="Scene template ID(s) to apply in order.",
    )
    scene_template_apply_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_template_apply_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )
    scene_template_apply_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing intent fields (hard locks are still respected).",
    )
    scene_template_preview_parser = scene_template_subparsers.add_parser(
        "preview",
        help="Preview template changes without writing files.",
    )
    scene_template_preview_parser.add_argument(
        "template_ids",
        nargs="+",
        help="Scene template ID(s) to preview in order.",
    )
    scene_template_preview_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_template_preview_parser.add_argument(
        "--force",
        action="store_true",
        help="Preview overwriting existing intent fields (hard locks are still respected).",
    )
    scene_template_preview_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for template preview.",
    )

    render_plan_parser = subparsers.add_parser(
        "render-plan",
        help="Render plan artifact tools.",
    )
    render_plan_subparsers = render_plan_parser.add_subparsers(
        dest="render_plan_command",
        required=True,
    )
    render_plan_build_parser = render_plan_subparsers.add_parser(
        "build",
        help="Build a deterministic render_plan JSON from scene + targets.",
    )
    render_plan_build_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    render_plan_build_parser.add_argument(
        "--targets",
        required=True,
        help=(
            "Comma-separated target IDs or aliases "
            "(e.g., TARGET.STEREO.2_0,5.1 (home theater))."
        ),
    )
    render_plan_build_parser.add_argument(
        "--out",
        required=True,
        help="Path to output render_plan JSON.",
    )
    render_plan_build_parser.add_argument(
        "--routing-plan",
        default=None,
        help="Optional path to routing_plan JSON.",
    )
    render_plan_build_parser.add_argument(
        "--output-formats",
        default="wav",
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    render_plan_build_parser.add_argument(
        "--context",
        action="append",
        choices=["render", "auto_apply"],
        default=[],
        help="Repeatable render context.",
    )
    render_plan_build_parser.add_argument(
        "--policy-id",
        default=None,
        help="Optional downmix policy ID override.",
    )
    render_plan_to_variants_parser = render_plan_subparsers.add_parser(
        "to-variants",
        help="Convert scene + render_plan into a schema-valid executable variant_plan.",
    )
    render_plan_to_variants_parser.add_argument(
        "--render-plan",
        required=True,
        help="Path to render_plan JSON.",
    )
    render_plan_to_variants_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    render_plan_to_variants_parser.add_argument(
        "--out",
        required=True,
        help="Path to output variant_plan JSON.",
    )
    render_plan_to_variants_parser.add_argument(
        "--out-dir",
        required=True,
        help="Root output directory used for per-variant artifact folders.",
    )
    render_plan_to_variants_parser.add_argument(
        "--run",
        action="store_true",
        help="Immediately execute the generated variant plan.",
    )
    render_plan_to_variants_parser.add_argument(
        "--listen-pack",
        action="store_true",
        help="When --run is set, also write listen_pack.json.",
    )
    render_plan_to_variants_parser.add_argument(
        "--deliverables-index",
        action="store_true",
        help="When --run is set, also write deliverables_index.json.",
    )
    render_plan_to_variants_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="When --run is set, reuse cached analysis by lockfile + run_config hash.",
    )
    render_plan_to_variants_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    render_plan_show_parser = render_plan_subparsers.add_parser(
        "show",
        help="Display a render_plan JSON.",
    )
    render_plan_show_parser.add_argument(
        "--render-plan",
        required=True,
        help="Path to render_plan JSON.",
    )
    render_plan_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for render_plan display.",
    )
    render_plan_validate_parser = render_plan_subparsers.add_parser(
        "validate",
        help="Validate a render_plan JSON against schema.",
    )
    render_plan_validate_parser.add_argument(
        "--render-plan",
        required=True,
        help="Path to render_plan JSON.",
    )
    render_plan_plan_parser = render_plan_subparsers.add_parser(
        "plan",
        help="Build a render plan from a render_request JSON + scene JSON.",
    )
    render_plan_plan_parser.add_argument(
        "--request",
        required=True,
        help="Path to render_request JSON.",
    )
    render_plan_plan_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    render_plan_plan_parser.add_argument(
        "--routing-plan",
        default=None,
        help="Optional path to routing_plan JSON.",
    )
    render_plan_plan_parser.add_argument(
        "--out",
        required=True,
        help="Path to output render_plan JSON.",
    )
    render_plan_plan_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )

    render_report_parser = subparsers.add_parser(
        "render-report",
        help="Build a render_report JSON from a render_plan.",
    )
    render_report_parser.add_argument(
        "--plan",
        required=True,
        help="Path to render_plan JSON.",
    )
    render_report_parser.add_argument(
        "--out",
        required=True,
        help="Path to output render_report JSON.",
    )
    render_report_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )

    render_run_parser = subparsers.add_parser(
        "render-run",
        help=(
            "Build a render plan from a render_request + scene, "
            "then build a render report (dry_run) in one pass."
        ),
    )
    render_run_parser.add_argument(
        "--request",
        required=True,
        help="Path to render_request JSON.",
    )
    render_run_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    render_run_parser.add_argument(
        "--routing-plan",
        default=None,
        help="Optional path to routing_plan JSON.",
    )
    render_run_parser.add_argument(
        "--plan-out",
        required=True,
        help="Path to output render_plan JSON.",
    )
    render_run_parser.add_argument(
        "--report-out",
        required=True,
        help="Path to output render_report JSON.",
    )
    render_run_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output files if they already exist.",
    )

    timeline_parser = subparsers.add_parser("timeline", help="Timeline marker tools.")
    timeline_subparsers = timeline_parser.add_subparsers(
        dest="timeline_command",
        required=True,
    )
    timeline_validate_parser = timeline_subparsers.add_parser(
        "validate",
        help="Validate and normalize a timeline JSON.",
    )
    timeline_validate_parser.add_argument(
        "--timeline",
        required=True,
        help="Path to timeline JSON.",
    )
    timeline_show_parser = timeline_subparsers.add_parser(
        "show",
        help="Show a normalized timeline JSON.",
    )
    timeline_show_parser.add_argument(
        "--timeline",
        required=True,
        help="Path to timeline JSON.",
    )
    timeline_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for timeline display.",
    )
    gui_state_parser = subparsers.add_parser("gui-state", help="GUI state artifact tools.")
    gui_state_subparsers = gui_state_parser.add_subparsers(
        dest="gui_state_command",
        required=True,
    )
    gui_state_validate_parser = gui_state_subparsers.add_parser(
        "validate",
        help="Validate a gui_state JSON file.",
    )
    gui_state_validate_parser.add_argument(
        "--in",
        dest="in_path",
        required=True,
        help="Path to gui_state JSON.",
    )
    gui_state_default_parser = gui_state_subparsers.add_parser(
        "default",
        help="Write a default gui_state JSON file.",
    )
    gui_state_default_parser.add_argument(
        "--out",
        required=True,
        help="Path to output gui_state JSON.",
    )

    role_lexicon_parser = subparsers.add_parser(
        "role-lexicon",
        help="Role lexicon tools.",
    )
    role_lexicon_subparsers = role_lexicon_parser.add_subparsers(
        dest="role_lexicon_command",
        required=True,
    )
    role_lexicon_merge_parser = role_lexicon_subparsers.add_parser(
        "merge-suggestions",
        help="Merge corpus scan suggestions into a user role lexicon YAML.",
    )
    role_lexicon_merge_parser.add_argument(
        "--suggestions",
        required=True,
        help="Path to suggestions YAML (from tools/stem_corpus_scan.py --suggestions-out).",
    )
    role_lexicon_merge_parser.add_argument(
        "--base",
        default=None,
        help="Optional path to an existing user role lexicon YAML to merge into.",
    )
    role_lexicon_merge_parser.add_argument(
        "--out",
        required=True,
        help="Path to write the merged role lexicon YAML.",
    )
    role_lexicon_merge_parser.add_argument(
        "--deny",
        default=None,
        help="Comma-separated tokens to exclude from merge.",
    )
    role_lexicon_merge_parser.add_argument(
        "--allow",
        default=None,
        help=(
            "Comma-separated tokens to include exclusively. "
            "When provided, ONLY these tokens are merged "
            "(overrides default validity filters like digit-only or len<2)."
        ),
    )
    role_lexicon_merge_parser.add_argument(
        "--max-per-role",
        type=int,
        default=100,
        help="Maximum new keywords to add per role (default: 100). Deterministic (lexicographic) selection.",
    )
    role_lexicon_merge_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary without writing the output file.",
    )
    role_lexicon_merge_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format for the summary (default: json).",
    )

    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(raw_argv)
    repo_root = Path(__file__).resolve().parents[2]
    tools_dir = repo_root / "tools"
    presets_dir = repo_root / "presets"

    if args.command == "scan":
        return _run_scan(
            tools_dir,
            Path(args.stems_dir),
            Path(args.out),
            args.meters,
            args.peak,
        )
    if args.command == "stems":
        if args.stems_command == "scan":
            try:
                payload = build_stems_index(
                    Path(args.root),
                    root_dir=args.root,
                )
                _validate_json_payload(
                    payload,
                    schema_path=repo_root / "schemas" / "stems_index.schema.json",
                    payload_name="Stems index",
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            _write_json_file(Path(args.out), payload)
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                stem_sets = (
                    payload.get("stem_sets")
                    if isinstance(payload.get("stem_sets"), list)
                    else []
                )
                print(_render_stem_sets_text(stem_sets))
            return 0

        if args.stems_command == "sets":
            try:
                payload = resolve_stem_sets(Path(args.root))
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stem_sets_text(payload))
            return 0

        if args.stems_command == "classify":
            roles_path = repo_root / "ontology" / "roles.yaml"
            try:
                stems_index_payload, stems_index_ref = _load_stems_index_for_classification(
                    repo_root=repo_root,
                    index_path=getattr(args, "index", None),
                    root_path=getattr(args, "root", None),
                )
                roles_payload = load_roles(roles_path)

                role_lexicon_payload: dict[str, Any] | None = None
                role_lexicon_ref: str | None = None
                if isinstance(args.role_lexicon, str) and args.role_lexicon.strip():
                    role_lexicon_ref = _path_ref(args.role_lexicon)
                    role_lexicon_payload = load_role_lexicon(
                        Path(args.role_lexicon),
                        roles_payload=roles_payload,
                    )

                payload = classify_stems(
                    stems_index_payload,
                    roles_payload,
                    role_lexicon=role_lexicon_payload,
                    use_common_role_lexicon=not bool(args.no_common_lexicon),
                    stems_index_ref=stems_index_ref,
                    roles_ref="ontology/roles.yaml",
                    role_lexicon_ref=role_lexicon_ref,
                )
                _validate_json_payload(
                    payload,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            _write_json_file(Path(args.out), payload)
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stems_map_text(payload))
            return 0

        if args.stems_command == "explain":
            roles_path = repo_root / "ontology" / "roles.yaml"
            try:
                stems_index_payload, stems_index_ref = _load_stems_index_for_classification(
                    repo_root=repo_root,
                    index_path=getattr(args, "index", None),
                    root_path=getattr(args, "root", None),
                )
                roles_payload = load_roles(roles_path)

                role_lexicon_payload: dict[str, Any] | None = None
                role_lexicon_ref: str | None = None
                if isinstance(args.role_lexicon, str) and args.role_lexicon.strip():
                    role_lexicon_ref = _path_ref(args.role_lexicon)
                    role_lexicon_payload = load_role_lexicon(
                        Path(args.role_lexicon),
                        roles_payload=roles_payload,
                    )

                stems_map, explanations = classify_stems_with_evidence(
                    stems_index_payload,
                    roles_payload,
                    role_lexicon=role_lexicon_payload,
                    use_common_role_lexicon=not bool(args.no_common_lexicon),
                    stems_index_ref=stems_index_ref,
                    roles_ref="ontology/roles.yaml",
                    role_lexicon_ref=role_lexicon_ref,
                )
                _validate_json_payload(
                    stems_map,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
                payload = _build_stem_explain_payload(
                    stems_map=stems_map,
                    explanations=explanations,
                    file_selector=args.file,
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stem_explain_text(payload))
            return 0

        if args.stems_command == "apply-overrides":
            try:
                stems_map_payload = _load_stems_map(
                    repo_root=repo_root,
                    map_path=Path(args.map),
                )
                overrides_payload = load_stems_overrides(Path(args.overrides))
                payload = apply_overrides(stems_map_payload, overrides_payload)
                _validate_json_payload(
                    payload,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            _write_json_file(Path(args.out), payload)
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stems_map_text(payload))
            return 0

        if args.stems_command == "review":
            try:
                payload = _load_stems_map(
                    repo_root=repo_root,
                    map_path=Path(args.map),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stems_map_text(payload))
            return 0

        if args.stems_command == "pipeline":
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            index_path = out_dir / "stems_index.json"
            map_path = out_dir / "stems_map.json"
            overrides_path = out_dir / "stems_overrides.yaml"

            roles_path = repo_root / "ontology" / "roles.yaml"
            try:
                stems_index_payload = build_stems_index(
                    Path(args.root),
                    root_dir=args.root,
                )
                _validate_json_payload(
                    stems_index_payload,
                    schema_path=repo_root / "schemas" / "stems_index.schema.json",
                    payload_name="Stems index",
                )
                _write_json_file(index_path, stems_index_payload)

                roles_payload = load_roles(roles_path)
                role_lexicon_payload: dict[str, Any] | None = None
                role_lexicon_ref: str | None = None
                if isinstance(getattr(args, "role_lexicon", None), str) and args.role_lexicon.strip():
                    role_lexicon_ref = _path_ref(args.role_lexicon)
                    role_lexicon_payload = load_role_lexicon(
                        Path(args.role_lexicon),
                        roles_payload=roles_payload,
                    )

                stems_map_payload = classify_stems(
                    stems_index_payload,
                    roles_payload,
                    role_lexicon=role_lexicon_payload,
                    use_common_role_lexicon=not bool(getattr(args, "no_common_lexicon", False)),
                    stems_index_ref="stems_index.json",
                    roles_ref="ontology/roles.yaml",
                    role_lexicon_ref=role_lexicon_ref,
                )
                _validate_json_payload(
                    stems_map_payload,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
                _write_json_file(map_path, stems_map_payload)

                overrides_written = False
                overrides_skipped = False
                if overrides_path.exists() and not getattr(args, "force", False):
                    overrides_skipped = True
                else:
                    template = _default_stems_overrides_template()
                    if not template.endswith("\n"):
                        template += "\n"
                    overrides_path.write_text(template, encoding="utf-8")
                    overrides_written = True

                bundle_path_str: str | None = None
                if isinstance(getattr(args, "bundle", None), str) and args.bundle.strip():
                    bundle_path = Path(args.bundle)
                    summary = stems_map_payload.get("summary")
                    if not isinstance(summary, dict):
                        summary = {}
                    bundle_payload: dict[str, Any] = {
                        "stems_index_path": index_path.resolve().as_posix(),
                        "stems_map_path": map_path.resolve().as_posix(),
                        "stems_summary": {
                            "counts_by_bus_group": summary.get("counts_by_bus_group", {}),
                            "unknown_files": summary.get("unknown_files", 0),
                        },
                    }
                    _write_json_file(bundle_path, bundle_payload)
                    bundle_path_str = str(bundle_path)

            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            files = stems_index_payload.get("files")
            file_count = len(files) if isinstance(files, list) else 0
            assignments = stems_map_payload.get("assignments")
            assignment_count = len(assignments) if isinstance(assignments, list) else 0

            result: dict[str, Any] = {
                "stems_index": str(index_path),
                "stems_map": str(map_path),
                "stems_overrides": str(overrides_path),
                "overrides_written": overrides_written,
                "overrides_skipped": overrides_skipped,
                "file_count": file_count,
                "assignment_count": assignment_count,
            }
            if bundle_path_str is not None:
                result["bundle"] = bundle_path_str

            print(json.dumps(result, indent=2, sort_keys=True))
            return 0

        if args.stems_command == "overrides":
            if args.stems_overrides_command == "default":
                out_path = Path(args.out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                template = _default_stems_overrides_template()
                if not template.endswith("\n"):
                    template += "\n"
                out_path.write_text(template, encoding="utf-8")
                return 0

            if args.stems_overrides_command == "validate":
                try:
                    load_stems_overrides(Path(args.in_path))
                except (RuntimeError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                print("Stems overrides are valid.")
                return 0

            print("Unknown stems overrides command.", file=sys.stderr)
            return 2

        if args.stems_command == "draft":
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            scene_path = out_dir / args.scene_out
            routing_path = out_dir / args.routing_out

            if not getattr(args, "overwrite", False):
                existing: list[str] = []
                if scene_path.exists():
                    existing.append(str(scene_path))
                if routing_path.exists():
                    existing.append(str(routing_path))
                if existing:
                    for p in existing:
                        print(f"File already exists: {p}", file=sys.stderr)
                    print("Use --overwrite to replace.", file=sys.stderr)
                    return 1

            try:
                stems_map_payload = _load_stems_map(
                    repo_root=repo_root,
                    map_path=Path(args.stems_map),
                )
                scene_payload = build_draft_scene(
                    stems_map_payload,
                    stems_dir=args.stems_dir,
                )
                routing_payload = build_draft_routing_plan(stems_map_payload)

                _validate_json_payload(
                    scene_payload,
                    schema_path=repo_root / "schemas" / "scene.schema.json",
                    payload_name="Draft scene",
                )
                _validate_json_payload(
                    routing_payload,
                    schema_path=repo_root / "schemas" / "routing_plan.schema.json",
                    payload_name="Draft routing plan",
                )

                _write_json_file(scene_path, scene_payload)
                _write_json_file(routing_path, routing_payload)
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            assignments = stems_map_payload.get("assignments")
            stems_count = len(assignments) if isinstance(assignments, list) else 0
            summary = stems_map_payload.get("summary")
            bus_groups_count = 0
            if isinstance(summary, dict):
                cbg = summary.get("counts_by_bus_group")
                if isinstance(cbg, dict):
                    bus_groups_count = len(cbg)

            fmt = getattr(args, "format", "text")
            if fmt == "json":
                result: dict[str, Any] = {
                    "ok": True,
                    "preview_only": True,
                    "stems_count": stems_count,
                    "bus_groups_count": bus_groups_count,
                    "scene_out": scene_path.as_posix(),
                    "routing_out": routing_path.as_posix(),
                }
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Draft scene written to: {scene_path.as_posix()}")
                print(f"Draft routing plan written to: {routing_path.as_posix()}")
                print(f"Stems: {stems_count}, Bus groups: {bus_groups_count}")
                print(
                    "These are preview-only drafts. "
                    "They are not auto-discovered by any workflow."
                )

            return 0

        if args.stems_command == "audition":
            out_dir = Path(args.out_dir)
            audition_dir = out_dir / "stems_auditions"

            if not getattr(args, "overwrite", False) and audition_dir.exists():
                manifest_path = audition_dir / "manifest.json"
                if manifest_path.exists():
                    print(
                        f"Audition directory already has manifest: "
                        f"{manifest_path.as_posix()}",
                        file=sys.stderr,
                    )
                    print("Use --overwrite to replace.", file=sys.stderr)
                    return 1

            try:
                stems_map_payload = _load_stems_map(
                    repo_root=repo_root,
                    map_path=Path(args.stems_map),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            result = render_audition_pack(
                stems_map_payload,
                stems_dir=Path(args.stems_dir),
                out_dir=out_dir,
                segment_seconds=args.segment,
            )

            if not result.get("ok", False):
                err_out = {
                    "ok": False,
                    "error_code": result.get("error_code", "UNKNOWN"),
                    "missing_files_count": result.get("missing_files_count", 0),
                    "groups_attempted_count": result.get(
                        "groups_attempted_count", 0
                    ),
                }
                print(json.dumps(err_out, indent=2, sort_keys=True))
                return 1

            fmt = getattr(args, "format", "json")
            if fmt == "json":
                summary: dict[str, Any] = {
                    "ok": True,
                    "out_dir": result.get("out_dir", ""),
                    "manifest_path": result.get("manifest_path", ""),
                    "rendered_groups_count": result.get(
                        "rendered_groups_count", 0
                    ),
                    "attempted_groups_count": result.get(
                        "attempted_groups_count", 0
                    ),
                    "missing_files_count": result.get("missing_files_count", 0),
                    "skipped_mismatch_count": result.get(
                        "skipped_mismatch_count", 0
                    ),
                }
                print(json.dumps(summary, indent=2, sort_keys=True))
            else:
                print(
                    f"Audition pack written to: {result.get('out_dir', '')}"
                )
                print(
                    f"Manifest: {result.get('manifest_path', '')}"
                )
                print(
                    f"Rendered: {result.get('rendered_groups_count', 0)} / "
                    f"{result.get('attempted_groups_count', 0)} groups"
                )
                missing = result.get("missing_files_count", 0)
                skipped = result.get("skipped_mismatch_count", 0)
                if missing or skipped:
                    print(
                        f"Warnings: {missing} missing, "
                        f"{skipped} skipped (see manifest)"
                    )

            return 0

        print("Unknown stems command.", file=sys.stderr)
        return 2
    if args.command == "project":
        if args.project_command == "new":
            try:
                project_payload = new_project(
                    Path(args.stems),
                    notes=args.notes,
                )
                write_project(Path(args.out), project_payload)
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            return 0

        if args.project_command == "show":
            try:
                project_payload = load_project(Path(args.project))
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(project_payload, indent=2, sort_keys=True))
            else:
                print(_render_project_text(project_payload))
            return 0

        if args.project_command == "run":
            project_path = Path(args.project)
            out_dir = Path(args.out)
            try:
                project_payload = load_project(project_path)
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            stems_dir_value = project_payload.get("stems_dir")
            if not isinstance(stems_dir_value, str) or not stems_dir_value:
                print("Project stems_dir must be a non-empty string.", file=sys.stderr)
                return 1
            stems_dir = Path(stems_dir_value)
            project_timeline_path = project_payload.get("timeline_path")
            if (
                getattr(args, "timeline", None) in {None, ""}
                and isinstance(project_timeline_path, str)
                and project_timeline_path.strip()
            ):
                args.timeline = project_timeline_path

            exit_code, run_mode = _run_workflow_from_run_args(
                repo_root=repo_root,
                tools_dir=tools_dir,
                presets_dir=presets_dir,
                stems_dir=stems_dir,
                out_dir=out_dir,
                args=args,
            )
            if exit_code != 0:
                return exit_code

            try:
                project_payload = update_project_last_run(
                    project_payload,
                    _project_last_run_payload(mode=run_mode, out_dir=out_dir),
                )
                run_config_defaults = _project_run_config_defaults(
                    mode=run_mode,
                    out_dir=out_dir,
                )
                if isinstance(run_config_defaults, dict):
                    project_payload["run_config_defaults"] = run_config_defaults

                timeline_value = getattr(args, "timeline", None)
                if isinstance(timeline_value, str) and timeline_value.strip():
                    project_payload["timeline_path"] = Path(timeline_value).resolve().as_posix()

                try:
                    from mmo.core.lockfile import build_lockfile  # noqa: WPS433

                    lock_payload = build_lockfile(stems_dir)
                except ValueError:
                    lock_payload = None
                if isinstance(lock_payload, dict):
                    lockfile_path = out_dir.resolve() / "lockfile.json"
                    _write_json_file(lockfile_path, lock_payload)
                    project_payload["lockfile_path"] = lockfile_path.as_posix()
                    project_payload["lock_hash"] = hash_lockfile(lock_payload)

                write_project(project_path, project_payload)
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            return 0

        if args.project_command == "init":
            out_dir = Path(args.out_dir)
            stems_sub = out_dir / "stems"
            drafts_sub = out_dir / "drafts"
            force = bool(getattr(args, "force", False))

            # Allowlisted output files this command may write.
            index_path = stems_sub / "stems_index.json"
            map_path = stems_sub / "stems_map.json"
            overrides_path = stems_sub / "stems_overrides.yaml"
            scene_path = drafts_sub / "scene.draft.json"
            routing_path = drafts_sub / "routing_plan.draft.json"
            drafts_readme_path = drafts_sub / "README.txt"
            root_readme_path = out_dir / "README.txt"
            bundle_path: Path | None = None
            if isinstance(getattr(args, "bundle", None), str) and args.bundle.strip():
                bundle_path = Path(args.bundle)

            # Pre-flight: refuse to overwrite non-allowlisted or protected files.
            always_overwritable = [
                index_path, map_path,
                scene_path, routing_path,
                drafts_readme_path, root_readme_path,
            ]
            if bundle_path is not None:
                always_overwritable.append(bundle_path)
            force_only = [overrides_path]

            if not force:
                blocked: list[str] = []
                for fp in force_only:
                    if fp.exists():
                        blocked.append(fp.as_posix())
                if blocked:
                    for bp in blocked:
                        print(f"File exists (use --force to overwrite): {bp}", file=sys.stderr)
                    print("Aborting.", file=sys.stderr)
                    return 1

            try:
                # --- Stems pipeline (scan + classify + overrides) ---
                stems_sub.mkdir(parents=True, exist_ok=True)

                stems_index_payload = build_stems_index(
                    Path(args.stems_root),
                    root_dir=args.stems_root,
                )
                _validate_json_payload(
                    stems_index_payload,
                    schema_path=repo_root / "schemas" / "stems_index.schema.json",
                    payload_name="Stems index",
                )
                _write_json_file(index_path, stems_index_payload)

                roles_path = repo_root / "ontology" / "roles.yaml"
                roles_payload = load_roles(roles_path)
                role_lexicon_payload: dict[str, Any] | None = None
                role_lexicon_ref: str | None = None
                if isinstance(getattr(args, "role_lexicon", None), str) and args.role_lexicon.strip():
                    role_lexicon_ref = _path_ref(args.role_lexicon)
                    role_lexicon_payload = load_role_lexicon(
                        Path(args.role_lexicon),
                        roles_payload=roles_payload,
                    )

                stems_map_payload = classify_stems(
                    stems_index_payload,
                    roles_payload,
                    role_lexicon=role_lexicon_payload,
                    use_common_role_lexicon=not bool(getattr(args, "no_common_lexicon", False)),
                    stems_index_ref="stems_index.json",
                    roles_ref="ontology/roles.yaml",
                    role_lexicon_ref=role_lexicon_ref,
                )
                _validate_json_payload(
                    stems_map_payload,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
                _write_json_file(map_path, stems_map_payload)

                overrides_written = False
                overrides_skipped = False
                if overrides_path.exists() and not force:
                    overrides_skipped = True
                else:
                    template = _default_stems_overrides_template()
                    if not template.endswith("\n"):
                        template += "\n"
                    overrides_path.write_text(template, encoding="utf-8")
                    overrides_written = True

                # --- Drafts ---
                drafts_sub.mkdir(parents=True, exist_ok=True)

                scene_payload = build_draft_scene(
                    stems_map_payload,
                    stems_dir=Path(args.stems_root).resolve().as_posix(),
                )
                routing_payload = build_draft_routing_plan(stems_map_payload)

                _validate_json_payload(
                    scene_payload,
                    schema_path=repo_root / "schemas" / "scene.schema.json",
                    payload_name="Draft scene",
                )
                _validate_json_payload(
                    routing_payload,
                    schema_path=repo_root / "schemas" / "routing_plan.schema.json",
                    payload_name="Draft routing plan",
                )

                _write_json_file(scene_path, scene_payload)
                _write_json_file(routing_path, routing_payload)

                # --- README files ---
                drafts_readme_path.write_text(
                    "PREVIEW-ONLY DRAFTS\n"
                    "\n"
                    "These draft files are preview-only.\n"
                    "They are NEVER auto-loaded by any MMO workflow.\n"
                    "To use a scene or routing plan, pass explicit flags\n"
                    "to the relevant command (e.g. future --scene / --routing-plan flags).\n",
                    encoding="utf-8",
                )
                root_readme_path.write_text(
                    "MMO Project Init Scaffold\n"
                    "\n"
                    "Edit stems/stems_overrides.yaml to adjust role assignments,\n"
                    "then rerun the pipeline and drafts:\n"
                    "\n"
                    "  python -m mmo stems pipeline --root <stems_root> --out-dir stems/\n"
                    "  python -m mmo stems draft --stems-map stems/stems_map.json --out-dir drafts/\n"
                    "\n"
                    "WARNING: Draft files in drafts/ are preview-only.\n"
                    "They are NEVER auto-loaded by any MMO workflow.\n",
                    encoding="utf-8",
                )

                # --- Optional bundle ---
                bundle_path_written: str | None = None
                if bundle_path is not None:
                    summary = stems_map_payload.get("summary")
                    if not isinstance(summary, dict):
                        summary = {}
                    project_init_section: dict[str, Any] = {
                        "stems_index_path": index_path.resolve().as_posix(),
                        "stems_map_path": map_path.resolve().as_posix(),
                        "scene_draft_path": scene_path.resolve().as_posix(),
                        "routing_draft_path": routing_path.resolve().as_posix(),
                        "preview_only": True,
                    }
                    if overrides_written:
                        project_init_section["stems_overrides_path"] = (
                            overrides_path.resolve().as_posix()
                        )
                    bundle_payload: dict[str, Any] = {
                        "stems_index_path": index_path.resolve().as_posix(),
                        "stems_map_path": map_path.resolve().as_posix(),
                        "scene_draft_path": scene_path.resolve().as_posix(),
                        "routing_plan_draft_path": routing_path.resolve().as_posix(),
                        "stems_summary": {
                            "counts_by_bus_group": summary.get("counts_by_bus_group", {}),
                            "unknown_files": summary.get("unknown_files", 0),
                        },
                        "project_init": project_init_section,
                    }
                    _write_json_file(bundle_path, bundle_payload)
                    bundle_path_written = bundle_path.as_posix()

            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            # --- Printed summary ---
            files_list = stems_index_payload.get("files")
            file_count = len(files_list) if isinstance(files_list, list) else 0
            assignments = stems_map_payload.get("assignments")
            assignment_count = len(assignments) if isinstance(assignments, list) else 0
            summary_obj = stems_map_payload.get("summary")
            bus_groups_count = 0
            if isinstance(summary_obj, dict):
                cbg = summary_obj.get("counts_by_bus_group")
                if isinstance(cbg, dict):
                    bus_groups_count = len(cbg)

            paths_written = sorted(
                fp.as_posix()
                for fp in [
                    index_path, map_path, scene_path, routing_path,
                    drafts_readme_path, root_readme_path,
                ]
            )
            if overrides_written:
                paths_written.append(overrides_path.as_posix())
                paths_written.sort()
            if bundle_path_written is not None:
                paths_written.append(bundle_path_written)
                paths_written.sort()

            result: dict[str, Any] = {
                "ok": True,
                "preview_only": True,
                "stems_root": Path(args.stems_root).as_posix(),
                "out_dir": out_dir.as_posix(),
                "paths_written": paths_written,
                "overrides_written": overrides_written,
                "overrides_skipped": overrides_skipped,
                "file_count": file_count,
                "assignment_count": assignment_count,
                "bus_groups_count": bus_groups_count,
            }
            if bundle_path_written is not None:
                result["bundle_path"] = bundle_path_written

            fmt = getattr(args, "format", "json")
            if fmt == "json":
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Project scaffold written to: {out_dir.as_posix()}")
                for wp in paths_written:
                    print(f"  {wp}")
                print(f"Stems: {file_count}, Assignments: {assignment_count}, Bus groups: {bus_groups_count}")
                if overrides_skipped:
                    print("stems_overrides.yaml already exists (use --force to overwrite).")
                print(
                    "Drafts in drafts/ are preview-only. "
                    "They are NEVER auto-loaded by any MMO workflow."
                )

            return 0

        if args.project_command == "refresh":
            project_dir = Path(args.project_dir)
            stems_sub = project_dir / "stems"
            drafts_sub = project_dir / "drafts"
            force = bool(getattr(args, "force", False))

            # Validate project directory exists with expected subdirectories.
            if not project_dir.is_dir():
                print(f"Project directory does not exist: {project_dir.as_posix()}", file=sys.stderr)
                return 1
            if not stems_sub.is_dir():
                print(f"Missing stems/ subdirectory in: {project_dir.as_posix()}", file=sys.stderr)
                return 1
            if not drafts_sub.is_dir():
                print(f"Missing drafts/ subdirectory in: {project_dir.as_posix()}", file=sys.stderr)
                return 1

            # Resolve stems_root.
            stems_root: Path
            if getattr(args, "stems_root", None) is not None:
                stems_root = Path(args.stems_root)
            else:
                default_stems_source = project_dir / "stems_source"
                if default_stems_source.is_dir():
                    stems_root = default_stems_source
                else:
                    print(
                        "Provide --stems-root or create "
                        f"{default_stems_source.as_posix()}.",
                        file=sys.stderr,
                    )
                    return 1

            # Allowlisted output paths.
            index_path = stems_sub / "stems_index.json"
            map_path = stems_sub / "stems_map.json"
            overrides_path = stems_sub / "stems_overrides.yaml"
            scene_path = drafts_sub / "scene.draft.json"
            routing_path = drafts_sub / "routing_plan.draft.json"

            try:
                # --- Stems pipeline (scan + classify + overrides) ---
                stems_index_payload = build_stems_index(
                    stems_root,
                    root_dir=str(stems_root),
                )
                _validate_json_payload(
                    stems_index_payload,
                    schema_path=repo_root / "schemas" / "stems_index.schema.json",
                    payload_name="Stems index",
                )
                _write_json_file(index_path, stems_index_payload)

                roles_path = repo_root / "ontology" / "roles.yaml"
                roles_payload = load_roles(roles_path)
                role_lexicon_payload: dict[str, Any] | None = None
                role_lexicon_ref: str | None = None
                if isinstance(getattr(args, "role_lexicon", None), str) and args.role_lexicon.strip():
                    role_lexicon_ref = _path_ref(args.role_lexicon)
                    role_lexicon_payload = load_role_lexicon(
                        Path(args.role_lexicon),
                        roles_payload=roles_payload,
                    )

                stems_map_payload = classify_stems(
                    stems_index_payload,
                    roles_payload,
                    role_lexicon=role_lexicon_payload,
                    use_common_role_lexicon=not bool(getattr(args, "no_common_lexicon", False)),
                    stems_index_ref="stems_index.json",
                    roles_ref="ontology/roles.yaml",
                    role_lexicon_ref=role_lexicon_ref,
                )
                _validate_json_payload(
                    stems_map_payload,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
                _write_json_file(map_path, stems_map_payload)

                overrides_written = False
                overrides_skipped = False
                if overrides_path.exists() and not force:
                    overrides_skipped = True
                else:
                    template = _default_stems_overrides_template()
                    if not template.endswith("\n"):
                        template += "\n"
                    overrides_path.write_text(template, encoding="utf-8")
                    overrides_written = True

                # --- Drafts ---
                scene_payload = build_draft_scene(
                    stems_map_payload,
                    stems_dir=stems_root.resolve().as_posix(),
                )
                routing_payload = build_draft_routing_plan(stems_map_payload)

                _validate_json_payload(
                    scene_payload,
                    schema_path=repo_root / "schemas" / "scene.schema.json",
                    payload_name="Draft scene",
                )
                _validate_json_payload(
                    routing_payload,
                    schema_path=repo_root / "schemas" / "routing_plan.schema.json",
                    payload_name="Draft routing plan",
                )

                _write_json_file(scene_path, scene_payload)
                _write_json_file(routing_path, routing_payload)

            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            # --- Printed summary ---
            files_list = stems_index_payload.get("files")
            file_count = len(files_list) if isinstance(files_list, list) else 0
            assignments = stems_map_payload.get("assignments")
            assignment_count = len(assignments) if isinstance(assignments, list) else 0
            summary_obj = stems_map_payload.get("summary")
            bus_groups_count = 0
            if isinstance(summary_obj, dict):
                cbg = summary_obj.get("counts_by_bus_group")
                if isinstance(cbg, dict):
                    bus_groups_count = len(cbg)

            paths_written = sorted(
                fp.as_posix()
                for fp in [index_path, map_path, scene_path, routing_path]
            )
            if overrides_written:
                paths_written.append(overrides_path.as_posix())
                paths_written.sort()

            result: dict[str, Any] = {
                "ok": True,
                "project_dir": project_dir.as_posix(),
                "stems_root": stems_root.as_posix(),
                "paths_written": paths_written,
                "overrides_written": overrides_written,
                "overrides_skipped": overrides_skipped,
                "file_count": file_count,
                "assignment_count": assignment_count,
                "bus_groups_count": bus_groups_count,
            }

            fmt = getattr(args, "format", "json")
            if fmt == "json":
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Project refreshed: {project_dir.as_posix()}")
                for wp in paths_written:
                    print(f"  {wp}")
                print(f"Stems: {file_count}, Assignments: {assignment_count}, Bus groups: {bus_groups_count}")
                if overrides_skipped:
                    print("stems_overrides.yaml preserved (use --force to overwrite).")

            return 0

        if args.project_command == "validate":
            return _run_project_validate(
                project_dir=Path(args.project_dir),
                out_path=Path(args.out) if args.out else None,
                repo_root=repo_root,
            )

        if args.project_command == "pack":
            return _run_project_pack(
                project_dir=Path(args.project_dir),
                out_path=Path(args.out),
                include_wavs=bool(getattr(args, "include_wavs", False)),
                force=bool(getattr(args, "force", False)),
            )

        print("Unknown project command.", file=sys.stderr)
        return 2
    if args.command == "ui":
        return _run_ui_workflow(
            repo_root=repo_root,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=Path(args.stems),
            out_dir=Path(args.out),
            project_path=Path(args.project) if args.project else None,
            nerd=args.nerd,
        )
    if args.command == "run":
        exit_code, _ = _run_workflow_from_run_args(
            repo_root=repo_root,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=Path(args.stems),
            out_dir=Path(args.out),
            args=args,
        )
        return exit_code
    if args.command == "analyze":
        analyze_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--profile"):
            analyze_overrides["profile_id"] = args.profile
        if _flag_present(raw_argv, "--meters"):
            analyze_overrides["meters"] = args.meters
        try:
            merged_run_config = _load_and_merge_run_config(
                args.config,
                analyze_overrides,
                preset_id=args.preset,
                presets_dir=presets_dir,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        effective_profile = _config_string(merged_run_config, "profile_id", args.profile)
        effective_meters = _config_optional_string(merged_run_config, "meters", args.meters)
        effective_preset_id = _config_optional_string(merged_run_config, "preset_id", None)
        stems_dir = Path(args.stems_dir)
        out_report_path = Path(args.out_report)
        effective_run_config = _analyze_run_config(
            profile_id=effective_profile,
            meters=effective_meters,
            preset_id=effective_preset_id,
            base_run_config=merged_run_config,
        )
        cache_enabled = args.cache == "on"
        cache_dir = Path(args.cache_dir) if args.cache_dir else None
        report_schema_path = repo_root / "schemas" / "report.schema.json"
        lock_payload: dict[str, Any] | None = None
        cache_key_value: str | None = None

        if cache_enabled:
            from mmo.core.lockfile import build_lockfile  # noqa: WPS433

            try:
                lock_payload = build_lockfile(stems_dir)
                cache_key_value = _analysis_cache_key(lock_payload, effective_run_config)
            except ValueError:
                cache_enabled = False
                lock_payload = None
                cache_key_value = None

            if lock_payload is not None:
                cached_report = try_load_cached_report(
                    cache_dir,
                    lock_payload,
                    effective_run_config,
                )
                if (
                    isinstance(cached_report, dict)
                    and report_schema_is_valid(cached_report, report_schema_path)
                ):
                    rewritten_report = rewrite_report_stems_dir(cached_report, stems_dir)
                    if report_schema_is_valid(rewritten_report, report_schema_path):
                        _write_json_file(out_report_path, rewritten_report)
                        print(f"analysis cache: hit {cache_key_value}")
                        return 0
                print(f"analysis cache: miss {cache_key_value}")

        exit_code = _run_analyze(
            tools_dir,
            stems_dir,
            out_report_path,
            effective_meters,
            args.peak,
            args.plugins,
            args.keep_scan,
            effective_profile,
        )
        if exit_code != 0:
            return exit_code
        try:
            _stamp_report_run_config(
                out_report_path,
                effective_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if cache_enabled and lock_payload is not None:
            try:
                report_payload = _load_report(out_report_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if report_schema_is_valid(report_payload, report_schema_path):
                if _should_skip_analysis_cache_save(report_payload, effective_run_config):
                    print(f"analysis cache: skip-save {cache_key_value} (time-cap stop)")
                else:
                    try:
                        save_cached_report(
                            cache_dir,
                            lock_payload,
                            effective_run_config,
                            report_payload,
                        )
                    except OSError:
                        pass
        return 0
    if args.command == "export":
        export_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--truncate-values"):
            export_overrides["truncate_values"] = args.truncate_values
        try:
            merged_run_config = _load_and_merge_run_config(args.config, export_overrides)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        truncate_values = _config_int(
            merged_run_config,
            "truncate_values",
            args.truncate_values,
        )
        return _run_export(
            tools_dir,
            Path(args.report),
            args.csv,
            args.pdf,
            no_measurements=args.no_measurements,
            no_gates=args.no_gates,
            truncate_values=truncate_values,
        )
    if args.command == "compare":
        try:
            report_a, report_path_a = load_report_from_path_or_dir(Path(args.a))
            report_b, report_path_b = load_report_from_path_or_dir(Path(args.b))
            compare_report = build_compare_report(
                report_a,
                report_b,
                label_a=default_label_for_compare_input(args.a, report_path=report_path_a),
                label_b=default_label_for_compare_input(args.b, report_path=report_path_b),
                report_path_a=report_path_a,
                report_path_b=report_path_b,
            )
            _validate_json_payload(
                compare_report,
                schema_path=repo_root / "schemas" / "compare_report.schema.json",
                payload_name="Compare report",
            )
            _write_json_file(Path(args.out), compare_report)
            if args.pdf:
                from mmo.exporters.pdf_report import (  # noqa: WPS433
                    export_compare_report_pdf,
                )

                try:
                    export_compare_report_pdf(
                        compare_report,
                        Path(args.pdf),
                    )
                except RuntimeError:
                    print(
                        "PDF export requires reportlab. Install extras: pip install .[pdf]",
                        file=sys.stderr,
                    )
                    return 2
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        return 0
    if args.command == "render":
        render_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--profile"):
            render_overrides["profile_id"] = args.profile
        if _flag_present(raw_argv, "--source-layout"):
            _set_nested(
                ["downmix", "source_layout_id"],
                render_overrides,
                args.source_layout,
            )
        if _flag_present(raw_argv, "--target-layout"):
            _set_nested(
                ["downmix", "target_layout_id"],
                render_overrides,
                args.target_layout,
            )
        if _flag_present(raw_argv, "--out-dir"):
            _set_nested(["render", "out_dir"], render_overrides, args.out_dir)
        if _flag_present(raw_argv, "--output-formats"):
            try:
                render_output_formats = _parse_output_formats_csv(args.output_formats)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _set_nested(
                ["render", "output_formats"],
                render_overrides,
                render_output_formats,
            )
        try:
            merged_run_config = _load_and_merge_run_config(
                args.config,
                render_overrides,
                preset_id=args.preset,
                presets_dir=presets_dir,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        profile_id = _config_string(merged_run_config, "profile_id", args.profile)
        out_dir = _config_nested_optional_string(
            merged_run_config,
            "render",
            "out_dir",
            args.out_dir,
        )
        output_formats = _config_nested_output_formats(
            merged_run_config,
            "render",
            ["wav"],
        )
        try:
            return _run_render_command(
                repo_root=repo_root,
                report_path=Path(args.report),
                plugins_dir=Path(args.plugins),
                out_manifest_path=Path(args.out_manifest),
                out_dir=Path(out_dir) if out_dir else None,
                profile_id=profile_id,
                command_label="render",
                output_formats=output_formats,
                run_config=merged_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.command == "apply":
        apply_config_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--profile"):
            apply_config_overrides["profile_id"] = args.profile
        if _flag_present(raw_argv, "--source-layout"):
            _set_nested(
                ["downmix", "source_layout_id"],
                apply_config_overrides,
                args.source_layout,
            )
        if _flag_present(raw_argv, "--target-layout"):
            _set_nested(
                ["downmix", "target_layout_id"],
                apply_config_overrides,
                args.target_layout,
            )
        if _flag_present(raw_argv, "--out-dir"):
            _set_nested(["render", "out_dir"], apply_config_overrides, args.out_dir)
        if _flag_present(raw_argv, "--output-formats"):
            try:
                apply_output_formats = _parse_output_formats_csv(args.output_formats)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _set_nested(
                ["apply", "output_formats"],
                apply_config_overrides,
                apply_output_formats,
            )
        try:
            merged_run_config = _load_and_merge_run_config(
                args.config,
                apply_config_overrides,
                preset_id=args.preset,
                presets_dir=presets_dir,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        profile_id = _config_string(merged_run_config, "profile_id", args.profile)
        out_dir = _config_nested_optional_string(
            merged_run_config,
            "render",
            "out_dir",
            args.out_dir,
        )
        output_formats = _config_nested_output_formats(
            merged_run_config,
            "apply",
            ["wav"],
        )
        if not out_dir:
            print(
                "Missing output directory. Provide --out-dir or set render.out_dir in --config/--preset.",
                file=sys.stderr,
            )
            return 1
        try:
            return _run_apply_command(
                repo_root=repo_root,
                report_path=Path(args.report),
                plugins_dir=Path(args.plugins),
                out_manifest_path=Path(args.out_manifest),
                out_dir=Path(out_dir),
                out_report_path=Path(args.out_report) if args.out_report else None,
                profile_id=profile_id,
                output_formats=output_formats,
                run_config=merged_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.command == "bundle":
        try:
            return _run_bundle(
                repo_root=repo_root,
                report_path=Path(args.report),
                out_path=Path(args.out),
                render_manifest_path=(
                    Path(args.render_manifest) if args.render_manifest else None
                ),
                apply_manifest_path=Path(args.apply_manifest) if args.apply_manifest else None,
                applied_report_path=Path(args.applied_report) if args.applied_report else None,
                project_path=Path(args.project) if args.project else None,
                deliverables_index_path=(
                    Path(args.deliverables_index) if args.deliverables_index else None
                ),
                listen_pack_path=Path(args.listen_pack) if args.listen_pack else None,
                scene_path=Path(args.scene) if args.scene else None,
                render_plan_path=(
                    Path(args.render_plan) if getattr(args, "render_plan", None) else None
                ),
                stems_index_path=(
                    Path(args.stems_index) if getattr(args, "stems_index", None) else None
                ),
                stems_map_path=(
                    Path(args.stems_map) if getattr(args, "stems_map", None) else None
                ),
                timeline_path=None,
                gui_state_path=Path(args.gui_state) if args.gui_state else None,
                ui_locale=args.ui_locale,
                render_request_path=(
                    Path(args.render_request) if getattr(args, "render_request", None) else None
                ),
                render_report_path=(
                    Path(args.render_report) if getattr(args, "render_report", None) else None
                ),
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.command == "deliverables":
        if args.deliverables_command != "index":
            print("Unknown deliverables command.", file=sys.stderr)
            return 2
        return _run_deliverables_index_command(
            repo_root=repo_root,
            out_dir=Path(args.out_dir),
            out_path=Path(args.out),
            variant_result_path=(
                Path(args.variant_result) if args.variant_result else None
            ),
        )
    if args.command == "variants":
        if args.variants_command == "listen-pack":
            stems_aud_manifest = getattr(args, "stems_auditions_manifest", None)
            return _run_variants_listen_pack_command(
                repo_root=repo_root,
                presets_dir=presets_dir,
                variant_result_path=Path(args.variant_result),
                out_path=Path(args.out),
                stems_auditions_manifest=(
                    Path(stems_aud_manifest) if stems_aud_manifest else None
                ),
            )
        if args.variants_command != "run":
            print("Unknown variants command.", file=sys.stderr)
            return 2

        return _run_variants_workflow(
            repo_root=repo_root,
            presets_dir=presets_dir,
            stems_dir=Path(args.stems),
            out_dir=Path(args.out),
            preset_values=list(args.preset) if isinstance(args.preset, list) else None,
            config_values=list(args.config) if isinstance(args.config, list) else None,
            apply=args.apply,
            render=args.render,
            export_pdf=args.export_pdf,
            export_csv=args.export_csv,
            bundle=args.bundle,
            scene=args.scene,
            render_plan=getattr(args, "render_plan", False),
            profile=args.profile,
            meters=args.meters,
            max_seconds=args.max_seconds,
            routing=args.routing,
            source_layout=args.source_layout,
            target_layout=args.target_layout,
            downmix_qa=args.downmix_qa,
            qa_ref=args.qa_ref,
            qa_meters=args.qa_meters,
            qa_max_seconds=args.qa_max_seconds,
            policy_id=args.policy_id,
            truncate_values=args.truncate_values,
            output_formats=args.output_formats,
            render_output_formats=args.render_output_formats,
            apply_output_formats=args.apply_output_formats,
            format_set_values=list(args.format_set) if isinstance(args.format_set, list) else None,
            listen_pack=args.listen_pack,
            deliverables_index=args.deliverables_index,
            timeline_path=Path(args.timeline) if args.timeline else None,
            cache_enabled=args.cache == "on",
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        )
    if args.command == "plugins":
        if args.plugins_command == "list":
            try:
                payload = _build_plugins_list_payload(plugins_dir=Path(args.plugins))
            except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps({"plugins": payload}, indent=2, sort_keys=True))
            else:
                print(_render_plugins_list_text(payload))
            return 0

        print("Unknown plugins command.", file=sys.stderr)
        return 2
    if args.command == "presets":
        if args.presets_command == "list":
            try:
                presets = list_presets(
                    presets_dir,
                    tag=args.tag,
                    category=args.category,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(presets, indent=2, sort_keys=True))
            else:
                for item in presets:
                    preset_id = item.get("preset_id", "")
                    label = item.get("label", "")
                    category = item.get("category")
                    category_suffix = f" [{category}]" if isinstance(category, str) else ""
                    print(f"{preset_id}  {label}{category_suffix}")
            return 0
        if args.presets_command == "show":
            try:
                payload = _build_preset_show_payload(
                    presets_dir=presets_dir,
                    preset_id=args.preset_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"{payload.get('preset_id', '')}  {payload.get('label', '')}")
                print(payload.get("description", ""))
                run_config = payload.get("run_config")
                if isinstance(run_config, dict):
                    print(json.dumps(run_config, indent=2, sort_keys=True))
            return 0
        if args.presets_command == "preview":
            cli_overrides = _build_preset_preview_cli_overrides(
                args=args,
                raw_argv=raw_argv,
            )
            try:
                payload = _build_preset_preview_payload(
                    repo_root=repo_root,
                    presets_dir=presets_dir,
                    preset_id=args.preset_id,
                    config_path=args.config,
                    cli_overrides=cli_overrides,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_preset_preview_text(payload))
            return 0
        if args.presets_command == "recommend":
            try:
                payload = _build_preset_recommendations_payload(
                    report_path=Path(args.report),
                    presets_dir=presets_dir,
                    n=args.n,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                label_map = _build_preset_label_map(presets_dir=presets_dir)
                for idx, item in enumerate(payload):
                    if idx > 0:
                        print("")
                    preset_id = item.get("preset_id", "")
                    label = label_map.get(preset_id, "")
                    overlay = item.get("overlay")
                    overlay_suffix = (
                        f" ({overlay})"
                        if isinstance(overlay, str) and overlay.strip()
                        else ""
                    )
                    print(f"{preset_id}  {label}{overlay_suffix}")
                    reasons = item.get("reasons", [])
                    if isinstance(reasons, list):
                        for reason in reasons:
                            if isinstance(reason, str):
                                print(f"  - {reason}")
            return 0
        if args.presets_command == "packs":
            if args.presets_packs_command == "list":
                try:
                    payload = _build_preset_pack_list_payload(
                        presets_dir=presets_dir,
                    )
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    for idx, item in enumerate(payload):
                        if idx > 0:
                            print("")
                        print(f"{item.get('pack_id', '')}  {item.get('label', '')}")
                        for preset in item.get("presets", []):
                            if not isinstance(preset, dict):
                                continue
                            print(
                                f"{preset.get('preset_id', '')}"
                                f"  {preset.get('label', '')}"
                            )
                return 0
            if args.presets_packs_command == "show":
                try:
                    payload = _build_preset_pack_payload(
                        presets_dir=presets_dir,
                        pack_id=args.pack_id,
                    )
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    print(f"{payload.get('pack_id', '')}  {payload.get('label', '')}")
                    print(payload.get("description", ""))
                    for preset in payload.get("presets", []):
                        if not isinstance(preset, dict):
                            continue
                        print(
                            f"{preset.get('preset_id', '')}"
                            f"  {preset.get('label', '')}"
                        )
                return 0
            print("Unknown presets packs command.", file=sys.stderr)
            return 2
        print("Unknown presets command.", file=sys.stderr)
        return 2
    if args.command == "help":
        help_registry_path = repo_root / "ontology" / "help.yaml"
        if args.help_command == "list":
            try:
                payload = _build_help_list_payload(
                    help_registry_path=help_registry_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    print(f"{item.get('help_id', '')}  {item.get('title', '')}")
            return 0
        if args.help_command == "show":
            try:
                payload = _build_help_show_payload(
                    help_registry_path=help_registry_path,
                    help_id=args.help_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(payload.get("title", ""))
                print(payload.get("short", ""))
                long_text = payload.get("long")
                if isinstance(long_text, str) and long_text:
                    print("")
                    print(long_text)

                cues = payload.get("cues")
                if isinstance(cues, list) and cues:
                    print("")
                    print("Cues:")
                    for cue in cues:
                        if isinstance(cue, str):
                            print(f"- {cue}")

                watch_out_for = payload.get("watch_out_for")
                if isinstance(watch_out_for, list) and watch_out_for:
                    print("")
                    print("Watch out for:")
                    for item in watch_out_for:
                        if isinstance(item, str):
                            print(f"- {item}")
            return 0
        print("Unknown help command.", file=sys.stderr)
        return 2
    if args.command == "targets":
        render_targets_path = repo_root / "ontology" / "render_targets.yaml"
        if args.targets_command == "list":
            try:
                payload = _build_render_target_list_payload(
                    render_targets_path=render_targets_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                if not args.long:
                    for item in payload:
                        print(
                            f"{item.get('target_id', '')}"
                            f"  {item.get('label', '')}"
                            f"  {item.get('layout_id', '')}"
                        )
                else:
                    for index, item in enumerate(payload):
                        if index > 0:
                            print("")
                        print(
                            f"{item.get('target_id', '')}"
                            f"  {item.get('label', '')}"
                            f"  {item.get('layout_id', '')}"
                        )
                        aliases = item.get("aliases")
                        normalized_aliases = (
                            [
                                alias
                                for alias in aliases
                                if isinstance(alias, str) and alias.strip()
                            ]
                            if isinstance(aliases, list)
                            else []
                        )
                        if normalized_aliases:
                            print(f"aliases: {', '.join(normalized_aliases)}")
                        notes = item.get("notes")
                        normalized_notes = (
                            [note for note in notes if isinstance(note, str) and note.strip()]
                            if isinstance(notes, list)
                            else []
                        )
                        if normalized_notes:
                            print("notes:")
                            for note in normalized_notes:
                                print(f"- {note}")
            return 0
        if args.targets_command == "show":
            try:
                payload = _build_render_target_show_payload(
                    render_targets_path=render_targets_path,
                    target_id=args.target_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_target_text(payload))
            return 0
        if args.targets_command == "recommend":
            try:
                payload = _build_render_target_recommendations_payload(
                    repo_root=repo_root,
                    render_targets_path=render_targets_path,
                    report_input=args.report,
                    scene_input=args.scene,
                    max_results=args.max_results,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_target_recommendations_text(payload))
            return 0
        print("Unknown targets command.", file=sys.stderr)
        return 2
    if args.command == "roles":
        roles_path = repo_root / "ontology" / "roles.yaml"
        if args.roles_command == "list":
            try:
                payload = _build_role_list_payload(roles_path=roles_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for role_id in payload:
                    print(role_id)
            return 0
        if args.roles_command == "show":
            try:
                payload = _build_role_show_payload(
                    roles_path=roles_path,
                    role_id=args.role_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_role_text(payload))
            return 0
        print("Unknown roles command.", file=sys.stderr)
        return 2
    if args.command == "translation":
        translation_profiles_path = repo_root / "ontology" / "translation_profiles.yaml"
        if args.translation_command == "list":
            try:
                payload = _build_translation_profile_list_payload(
                    translation_profiles_path=translation_profiles_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    print(
                        f"{item.get('profile_id', '')}"
                        f"  {item.get('label', '')}"
                        f"  {item.get('intent', '')}"
                    )
            return 0
        if args.translation_command == "show":
            try:
                payload = _build_translation_profile_show_payload(
                    translation_profiles_path=translation_profiles_path,
                    profile_id=args.profile_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_translation_profile_text(payload))
            return 0
        if args.translation_command == "run":
            report_in_raw = args.report_in if isinstance(args.report_in, str) else ""
            report_out_raw = args.report_out if isinstance(args.report_out, str) else ""
            report_in_value = report_in_raw.strip()
            report_out_value = report_out_raw.strip()
            if bool(report_in_value) != bool(report_out_value):
                print(
                    "translation run requires both --report-in and --report-out when patching a report.",
                    file=sys.stderr,
                )
                return 1
            try:
                profile_ids = _parse_translation_profile_ids_csv(
                    args.profiles,
                    translation_profiles_path=translation_profiles_path,
                )
                payload = _build_translation_run_payload(
                    translation_profiles_path=translation_profiles_path,
                    audio_path=Path(args.audio),
                    profile_ids=profile_ids,
                    cache_dir=Path(args.cache_dir) if args.cache_dir else None,
                    use_cache=not bool(getattr(args, "no_cache", False)),
                )
                profiles = load_translation_profiles(translation_profiles_path)
                if isinstance(args.out, str) and args.out.strip():
                    _write_translation_results_json(Path(args.out), payload)
                if report_in_value and report_out_value:
                    _write_report_with_translation_results(
                        report_in_path=Path(report_in_value),
                        report_out_path=Path(report_out_value),
                        translation_results=payload,
                        repo_root=repo_root,
                        profiles=profiles,
                    )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_translation_results_text(payload))
            return 0
        if args.translation_command == "compare":
            try:
                profile_ids = _parse_translation_profile_ids_csv(
                    args.profiles,
                    translation_profiles_path=translation_profiles_path,
                )
                audio_paths = _resolve_translation_compare_audio_paths(
                    raw_audio=getattr(args, "audio", None),
                    in_dir_value=getattr(args, "in_dir", None),
                    glob_pattern=getattr(args, "glob", None),
                )
                payload = _build_translation_compare_payload(
                    translation_profiles_path=translation_profiles_path,
                    audio_paths=audio_paths,
                    profile_ids=profile_ids,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_translation_compare_text(payload))
            return 0
        if args.translation_command == "audition":
            try:
                profile_ids = _parse_translation_profile_ids_csv(
                    args.profiles,
                    translation_profiles_path=translation_profiles_path,
                )
                out_root_dir = Path(args.out_dir)
                audition_out_dir = out_root_dir / "translation_auditions"
                payload = _build_translation_audition_payload(
                    translation_profiles_path=translation_profiles_path,
                    audio_path=Path(args.audio),
                    out_dir=audition_out_dir,
                    profile_ids=profile_ids,
                    segment_s=args.segment,
                    cache_dir=Path(args.cache_dir) if args.cache_dir else None,
                    use_cache=not bool(getattr(args, "no_cache", False)),
                )
                _write_translation_audition_manifest(
                    audition_out_dir / "manifest.json",
                    payload,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(
                _render_translation_audition_text(
                    payload=payload,
                    root_out_dir=out_root_dir,
                    audition_out_dir=audition_out_dir,
                )
            )
            return 0
        print("Unknown translation command.", file=sys.stderr)
        return 2
    if args.command == "locks":
        scene_locks_path = repo_root / "ontology" / "scene_locks.yaml"
        if args.locks_command == "list":
            try:
                payload = _build_scene_lock_list_payload(
                    scene_locks_path=scene_locks_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    print(
                        f"{item.get('lock_id', '')}"
                        f"  {item.get('label', '')}"
                        f"  {item.get('severity', '')}"
                    )
            return 0
        if args.locks_command == "show":
            try:
                payload = _build_scene_lock_show_payload(
                    scene_locks_path=scene_locks_path,
                    lock_id=args.lock_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_scene_lock_text(payload))
            return 0
        print("Unknown locks command.", file=sys.stderr)
        return 2
    if args.command == "ui-copy":
        ui_copy_registry_path = repo_root / "ontology" / "ui_copy.yaml"
        if args.ui_copy_command == "list":
            try:
                payload = _build_ui_copy_list_payload(
                    ui_copy_registry_path=ui_copy_registry_path,
                    locale=args.locale,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"locale: {payload.get('locale', '')}")
                for item in payload.get("entries", []):
                    if not isinstance(item, dict):
                        continue
                    print(f"{item.get('copy_id', '')}  {item.get('text', '')}")
            return 0
        if args.ui_copy_command == "show":
            try:
                payload = _build_ui_copy_show_payload(
                    ui_copy_registry_path=ui_copy_registry_path,
                    locale=args.locale,
                    copy_id=args.copy_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(payload.get("copy_id", ""))
                print(payload.get("text", ""))
                tooltip = payload.get("tooltip")
                if isinstance(tooltip, str) and tooltip:
                    print("")
                    print(f"Tooltip: {tooltip}")
                long_text = payload.get("long")
                if isinstance(long_text, str) and long_text:
                    print("")
                    print(long_text)
                kind = payload.get("kind")
                if isinstance(kind, str) and kind:
                    print("")
                    print(f"Kind: {kind}")
                locale_value = payload.get("locale")
                if isinstance(locale_value, str) and locale_value:
                    print("")
                    print(f"Locale: {locale_value}")
            return 0
        print("Unknown ui-copy command.", file=sys.stderr)
        return 2
    if args.command == "ui-examples":
        ui_examples_dir = repo_root / "examples" / "ui_screens"
        if args.ui_examples_command == "list":
            try:
                payload = _build_ui_examples_list_payload(
                    ui_examples_dir=ui_examples_dir,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    print(
                        f"{item.get('filename', '')}"
                        f"  {item.get('screen_id', '')}"
                        f"  {item.get('mode', '')}"
                        f"  {item.get('title', '')}"
                    )
            return 0
        if args.ui_examples_command == "show":
            try:
                payload = _build_ui_examples_show_payload(
                    ui_examples_dir=ui_examples_dir,
                    filename=args.filename,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"screen_id: {payload.get('screen_id', '')}")
                print(f"mode: {payload.get('mode', '')}")
                print(f"title: {payload.get('title', '')}")
                print(f"description: {payload.get('description', '')}")
            return 0
        print("Unknown ui-examples command.", file=sys.stderr)
        return 2
    if args.command == "lock":
        from mmo.core.lockfile import build_lockfile, verify_lockfile  # noqa: WPS433

        schema_path = repo_root / "schemas" / "lockfile.schema.json"
        stems_dir = Path(args.stems_dir)

        if args.lock_command == "write":
            exclude_rel_paths: set[str] = set()
            out_rel_path = _rel_path_if_under_root(stems_dir, Path(args.out))
            if out_rel_path:
                exclude_rel_paths.add(out_rel_path)
            try:
                lock_payload = build_lockfile(
                    stems_dir,
                    exclude_rel_paths=exclude_rel_paths,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            try:
                _validate_json_payload(
                    lock_payload,
                    schema_path=schema_path,
                    payload_name="Lockfile",
                )
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            _write_json_file(Path(args.out), lock_payload)
            return 0

        if args.lock_command == "verify":
            exclude_rel_paths: set[str] = set()
            lock_rel_path = _rel_path_if_under_root(stems_dir, Path(args.lock))
            if lock_rel_path:
                exclude_rel_paths.add(lock_rel_path)
            if args.out:
                out_rel_path = _rel_path_if_under_root(stems_dir, Path(args.out))
                if out_rel_path:
                    exclude_rel_paths.add(out_rel_path)
            try:
                lock_payload = _load_json_object(Path(args.lock), label="Lockfile")
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            try:
                _validate_json_payload(
                    lock_payload,
                    schema_path=schema_path,
                    payload_name="Lockfile",
                )
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            try:
                verify_result = verify_lockfile(
                    stems_dir,
                    lock_payload,
                    exclude_rel_paths=exclude_rel_paths,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            _print_lock_verify_summary(verify_result)
            if args.out:
                _write_json_file(Path(args.out), verify_result)
            return 0 if verify_result.get("ok") else 1

        print("Unknown lock command.", file=sys.stderr)
        return 2
    if args.command == "scene":
        if args.scene_command == "build":
            try:
                template_ids: list[str] = []
                if isinstance(args.templates, str) and args.templates.strip():
                    template_ids = _parse_scene_template_ids_csv(args.templates)
                return _run_scene_build_command(
                    repo_root=repo_root,
                    report_path=Path(args.report),
                    out_path=Path(args.out),
                    timeline_path=Path(args.timeline) if args.timeline else None,
                    template_ids=template_ids,
                    force_templates=bool(args.force_templates),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.scene_command == "locks":
            try:
                return _run_scene_locks_edit_command(
                    repo_root=repo_root,
                    scene_path=Path(args.scene),
                    out_path=Path(args.out),
                    operation=args.scene_locks_command,
                    scope=args.scope,
                    target_id=args.id,
                    lock_id=args.lock,
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.scene_command == "intent":
            if args.scene_intent_command == "set":
                try:
                    return _run_scene_intent_set_command(
                        repo_root=repo_root,
                        scene_path=Path(args.scene),
                        out_path=Path(args.out),
                        scope=args.scope,
                        target_id=args.id,
                        key=args.key,
                        value=args.value,
                    )
                except (RuntimeError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                except SystemExit as exc:
                    return int(exc.code) if isinstance(exc.code, int) else 1
            if args.scene_intent_command == "show":
                try:
                    scene_payload = _load_json_object(Path(args.scene), label="Scene")
                    _validate_scene_schema(repo_root=repo_root, scene_payload=scene_payload)
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                except SystemExit as exc:
                    return int(exc.code) if isinstance(exc.code, int) else 1

                payload = _build_scene_intent_show_payload(scene_payload)
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    print(_render_scene_intent_text(payload))
                return 0
            print("Unknown scene intent command.", file=sys.stderr)
            return 2

        if args.scene_command == "template":
            scene_templates_path = repo_root / "ontology" / "scene_templates.yaml"
            if args.scene_template_command == "list":
                try:
                    payload = _build_scene_template_list_payload(
                        scene_templates_path=scene_templates_path,
                    )
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    for item in payload:
                        print(
                            f"{item.get('template_id', '')}"
                            f"  {item.get('label', '')}"
                        )
                return 0
            if args.scene_template_command == "show":
                try:
                    payload = _build_scene_template_show_payload(
                        scene_templates_path=scene_templates_path,
                        template_ids=args.template_ids,
                    )
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    for index, item in enumerate(payload):
                        if index > 0:
                            print("")
                        print(_render_scene_template_text(item))
                return 0
            if args.scene_template_command == "apply":
                try:
                    return _run_scene_template_apply_command(
                        repo_root=repo_root,
                        scene_path=Path(args.scene),
                        out_path=Path(args.out),
                        template_ids=args.template_ids,
                        force=bool(args.force),
                    )
                except (RuntimeError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                except SystemExit as exc:
                    return int(exc.code) if isinstance(exc.code, int) else 1
            if args.scene_template_command == "preview":
                try:
                    return _run_scene_template_preview_command(
                        repo_root=repo_root,
                        scene_path=Path(args.scene),
                        template_ids=args.template_ids,
                        force=bool(args.force),
                        output_format=args.format,
                    )
                except (RuntimeError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                except SystemExit as exc:
                    return int(exc.code) if isinstance(exc.code, int) else 1
            print("Unknown scene template command.", file=sys.stderr)
            return 2

        if args.scene_command in {"validate", "show"}:
            try:
                scene_payload = _load_json_object(Path(args.scene), label="Scene")
                _validate_scene_schema(repo_root=repo_root, scene_payload=scene_payload)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            if args.scene_command == "validate":
                print("Scene is valid.")
                return 0
            if args.format == "json":
                print(json.dumps(scene_payload, indent=2, sort_keys=True))
            else:
                print(_render_scene_text(scene_payload))
            return 0

        print("Unknown scene command.", file=sys.stderr)
        return 2
    if args.command == "render-plan":
        if args.render_plan_command == "build":
            try:
                target_ids = _parse_target_ids_csv(
                    args.targets,
                    render_targets_path=repo_root / "ontology" / "render_targets.yaml",
                )
                output_formats = _parse_output_formats_csv(args.output_formats)
                contexts = (
                    list(args.context)
                    if isinstance(args.context, list) and args.context
                    else ["render"]
                )
                return _run_render_plan_build_command(
                    repo_root=repo_root,
                    scene_path=Path(args.scene),
                    target_ids=target_ids,
                    out_path=Path(args.out),
                    routing_plan_path=(
                        Path(args.routing_plan) if args.routing_plan else None
                    ),
                    output_formats=output_formats,
                    contexts=contexts,
                    policy_id=args.policy_id,
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.render_plan_command == "to-variants":
            try:
                return _run_render_plan_to_variants_command(
                    repo_root=repo_root,
                    presets_dir=presets_dir,
                    render_plan_path=Path(args.render_plan),
                    scene_path=Path(args.scene),
                    out_path=Path(args.out),
                    out_dir=Path(args.out_dir),
                    run=args.run,
                    listen_pack=args.listen_pack,
                    deliverables_index=args.deliverables_index,
                    cache_enabled=args.cache == "on",
                    cache_dir=Path(args.cache_dir) if args.cache_dir else None,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.render_plan_command == "plan":
            try:
                return _run_render_plan_from_request_command(
                    repo_root=repo_root,
                    request_path=Path(args.request),
                    scene_path=Path(args.scene),
                    routing_plan_path=(
                        Path(args.routing_plan) if args.routing_plan else None
                    ),
                    out_path=Path(args.out),
                    force=bool(getattr(args, "force", False)),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.render_plan_command not in {"validate", "show"}:
            print("Unknown render-plan command.", file=sys.stderr)
            return 2

        try:
            render_plan_payload = _load_json_object(
                Path(args.render_plan),
                label="Render plan",
            )
            _validate_json_payload(
                render_plan_payload,
                schema_path=repo_root / "schemas" / "render_plan.schema.json",
                payload_name="Render plan",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

        if args.render_plan_command == "validate":
            print("Render plan is valid.")
            return 0
        if args.format == "json":
            print(json.dumps(render_plan_payload, indent=2, sort_keys=True))
        else:
            print(_render_render_plan_text(render_plan_payload))
        return 0
    if args.command == "render-report":
        out_path = Path(args.out)
        if out_path.exists() and not args.force:
            print(
                f"File exists (use --force to overwrite): {out_path.as_posix()}",
                file=sys.stderr,
            )
            return 1
        try:
            plan_payload = _load_json_object(
                Path(args.plan),
                label="Render plan",
            )
            _validate_json_payload(
                plan_payload,
                schema_path=repo_root / "schemas" / "render_plan.schema.json",
                payload_name="Render plan",
            )
            from mmo.core.render_reporting import build_render_report_from_plan  # noqa: WPS433

            report_payload = build_render_report_from_plan(plan_payload)
            _validate_json_payload(
                report_payload,
                schema_path=repo_root / "schemas" / "render_report.schema.json",
                payload_name="Render report",
            )
            _write_json_file(out_path, report_payload)
            return 0
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
    if args.command == "render-run":
        try:
            return _run_render_run_command(
                repo_root=repo_root,
                request_path=Path(args.request),
                scene_path=Path(args.scene),
                routing_plan_path=(
                    Path(args.routing_plan) if args.routing_plan else None
                ),
                plan_out_path=Path(args.plan_out),
                report_out_path=Path(args.report_out),
                force=bool(getattr(args, "force", False)),
            )
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
    if args.command == "timeline":
        if args.timeline_command not in {"validate", "show"}:
            print("Unknown timeline command.", file=sys.stderr)
            return 2
        try:
            timeline_payload = load_timeline(Path(args.timeline))
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.timeline_command == "validate":
            print("Timeline is valid.")
            return 0

        if args.format == "json":
            print(json.dumps(timeline_payload, indent=2, sort_keys=True))
        else:
            print(_render_timeline_text(timeline_payload))
        return 0
    if args.command == "gui-state":
        if args.gui_state_command == "validate":
            try:
                validate_gui_state(Path(args.in_path))
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print("GUI state is valid.")
            return 0
        if args.gui_state_command == "default":
            _write_json_file(Path(args.out), default_gui_state())
            return 0
        print("Unknown gui-state command.", file=sys.stderr)
        return 2
    if args.command == "routing":
        from mmo.core.session import build_session_from_stems_dir  # noqa: WPS433

        if args.routing_command != "show":
            print("Unknown routing command.", file=sys.stderr)
            return 2

        try:
            session = build_session_from_stems_dir(Path(args.stems))
            routing_plan = build_routing_plan(
                session,
                source_layout_id=args.source_layout,
                target_layout_id=args.target_layout,
            )
            _validate_json_payload(
                routing_plan,
                schema_path=repo_root / "schemas" / "routing_plan.schema.json",
                payload_name="Routing plan",
            )
            output = render_routing_plan(routing_plan, output_format=args.format)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

        print(output, end="")
        return 0
    if args.command == "downmix":
        from mmo.dsp.downmix import (  # noqa: WPS433
            load_layouts,
            render_matrix,
            resolve_downmix_matrix,
        )
        from mmo.core.downmix_qa import run_downmix_qa  # noqa: WPS433
        from mmo.core.downmix_inventory import build_downmix_list_payload  # noqa: WPS433
        from mmo.exporters.downmix_qa_csv import (  # noqa: WPS433
            export_downmix_qa_csv,
            render_downmix_qa_csv,
        )
        from mmo.exporters.downmix_qa_pdf import export_downmix_qa_pdf  # noqa: WPS433

        if args.downmix_command == "qa":
            downmix_qa_overrides: dict[str, Any] = {}
            if _flag_present(raw_argv, "--profile"):
                downmix_qa_overrides["profile_id"] = args.profile
            if _flag_present(raw_argv, "--meters"):
                downmix_qa_overrides["meters"] = args.meters
            if _flag_present(raw_argv, "--max-seconds"):
                downmix_qa_overrides["max_seconds"] = args.max_seconds
            if _flag_present(raw_argv, "--truncate-values"):
                downmix_qa_overrides["truncate_values"] = args.truncate_values
            if _flag_present(raw_argv, "--source-layout"):
                _set_nested(
                    ["downmix", "source_layout_id"],
                    downmix_qa_overrides,
                    args.source_layout,
                )
            if _flag_present(raw_argv, "--target-layout"):
                _set_nested(
                    ["downmix", "target_layout_id"],
                    downmix_qa_overrides,
                    args.target_layout,
                )
            if _flag_present(raw_argv, "--policy"):
                _set_nested(
                    ["downmix", "policy_id"],
                    downmix_qa_overrides,
                    args.policy,
                )
            try:
                merged_run_config = _load_and_merge_run_config(
                    args.config,
                    downmix_qa_overrides,
                    preset_id=args.preset,
                    presets_dir=presets_dir,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            effective_profile = _config_string(merged_run_config, "profile_id", args.profile)
            effective_meters = _config_string(merged_run_config, "meters", args.meters)
            effective_preset_id = _config_optional_string(merged_run_config, "preset_id", None)
            effective_max_seconds = _config_float(
                merged_run_config,
                "max_seconds",
                args.max_seconds,
            )
            effective_truncate_values = _config_int(
                merged_run_config,
                "truncate_values",
                args.truncate_values,
            )
            effective_source_layout = _config_nested_optional_string(
                merged_run_config,
                "downmix",
                "source_layout_id",
                args.source_layout,
            )
            effective_target_layout = _config_nested_optional_string(
                merged_run_config,
                "downmix",
                "target_layout_id",
                args.target_layout,
            )
            if not effective_target_layout:
                effective_target_layout = args.target_layout
            effective_policy = _config_nested_optional_string(
                merged_run_config,
                "downmix",
                "policy_id",
                args.policy,
            )

            if not effective_source_layout:
                print(
                    "Missing source layout. Provide --source-layout or set downmix.source_layout_id in --config.",
                    file=sys.stderr,
                )
                return 1
            layouts_path = repo_root / "ontology" / "layouts.yaml"
            try:
                layouts = load_layouts(layouts_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if effective_source_layout not in layouts:
                print(f"Unknown source layout: {effective_source_layout}", file=sys.stderr)
                return 1
            if effective_target_layout not in layouts:
                print(f"Unknown target layout: {effective_target_layout}", file=sys.stderr)
                return 1
            try:
                report = run_downmix_qa(
                    Path(args.src),
                    Path(args.ref),
                    source_layout_id=effective_source_layout,
                    target_layout_id=effective_target_layout,
                    policy_id=effective_policy,
                    tolerance_lufs=args.tolerance_lufs,
                    tolerance_true_peak_db=args.tolerance_true_peak,
                    tolerance_corr=args.tolerance_corr,
                    repo_root=repo_root,
                    meters=effective_meters,
                    max_seconds=effective_max_seconds,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.emit_report:
                from mmo.core.report_builders import (  # noqa: WPS433
                    build_minimal_report_for_downmix_qa,
                )

                report_payload = build_minimal_report_for_downmix_qa(
                    repo_root=repo_root,
                    qa_payload=report,
                    profile_id=effective_profile,
                    profiles_path=repo_root / "ontology" / "policies" / "authority_profiles.yaml",
                )
                report_payload["run_config"] = _downmix_qa_run_config(
                    profile_id=effective_profile,
                    meters=effective_meters,
                    max_seconds=effective_max_seconds,
                    truncate_values=effective_truncate_values,
                    source_layout_id=effective_source_layout,
                    target_layout_id=effective_target_layout,
                    policy_id=effective_policy,
                    preset_id=effective_preset_id,
                    base_run_config=merged_run_config,
                )
                apply_routing_plan_to_report(report_payload, report_payload["run_config"])
                out_path = Path(args.emit_report)
                _write_json_file(out_path, report_payload)

            if args.format == "json":
                output = json.dumps(report, indent=2, sort_keys=True) + "\n"
                if args.out:
                    out_path = Path(args.out)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(output, encoding="utf-8")
                else:
                    print(output, end="")
            elif args.format == "csv":
                if args.out:
                    export_downmix_qa_csv(report, Path(args.out))
                else:
                    print(render_downmix_qa_csv(report), end="")
            elif args.format == "pdf":
                out_path = Path(args.out) if args.out else Path.cwd() / "downmix_qa.pdf"
                export_downmix_qa_pdf(
                    report,
                    out_path,
                    truncate_values=effective_truncate_values,
                )
            else:
                print(f"Unsupported format: {args.format}", file=sys.stderr)
                return 2

            issues = report.get("downmix_qa", {}).get("issues", [])
            has_error = any(
                isinstance(issue, dict) and issue.get("severity", 0) >= 80
                for issue in issues
            )
            return 1 if has_error else 0

        if args.downmix_command == "list":
            want_layouts = args.layouts
            want_policies = args.policies
            want_conversions = args.conversions
            if not (want_layouts or want_policies or want_conversions):
                want_layouts = True
                want_policies = True
                want_conversions = True

            try:
                payload = build_downmix_list_payload(
                    repo_root=repo_root,
                    include_layouts=want_layouts,
                    include_policies=want_policies,
                    include_conversions=want_conversions,
                )
            except (ValueError, RuntimeError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
                print(output, end="")
            else:
                lines: list[str] = []
                if want_layouts:
                    lines.append("Layouts")
                    for row in payload.get("layouts", []):
                        line = f"{row.get('id')}"
                        name = row.get("name")
                        if isinstance(name, str) and name:
                            line += f"  {name}"
                        channels = row.get("channels")
                        if isinstance(channels, int):
                            line += f"  channels={channels}"
                        speakers = row.get("speakers")
                        if isinstance(speakers, list) and speakers:
                            line += f"  speakers={','.join(str(item) for item in speakers)}"
                        lines.append(line)
                    if want_policies or want_conversions:
                        lines.append("")
                if want_policies:
                    lines.append("Policies")
                    for row in payload.get("policies", []):
                        line = f"{row.get('id')}"
                        description = row.get("description")
                        if isinstance(description, str) and description:
                            line += f"  {description}"
                        lines.append(line)
                    if want_conversions:
                        lines.append("")
                if want_conversions:
                    lines.append("Conversions")
                    for row in payload.get("conversions", []):
                        source = row.get("source_layout_id")
                        target = row.get("target_layout_id")
                        policy_ids = row.get("policy_ids_available") or []
                        policy_text = ",".join(str(item) for item in policy_ids)
                        lines.append(f"{source} -> {target}  policies={policy_text}")
                print("\n".join(lines))
            return 0

        if args.downmix_command == "render":
            downmix_render_overrides: dict[str, Any] = {}
            if _flag_present(raw_argv, "--profile"):
                downmix_render_overrides["profile_id"] = args.profile
            if _flag_present(raw_argv, "--out-dir"):
                _set_nested(["render", "out_dir"], downmix_render_overrides, args.out_dir)
            try:
                merged_run_config = _load_and_merge_run_config(
                    args.config,
                    downmix_render_overrides,
                    preset_id=args.preset,
                    presets_dir=presets_dir,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            profile_id = _config_string(merged_run_config, "profile_id", args.profile)
            out_dir = _config_nested_optional_string(
                merged_run_config,
                "render",
                "out_dir",
                args.out_dir,
            )
            try:
                return _run_downmix_render(
                    repo_root=repo_root,
                    report_path=Path(args.report),
                    plugins_dir=Path(args.plugins),
                    out_manifest_path=Path(args.out_manifest),
                    out_dir=Path(out_dir) if out_dir else None,
                    profile_id=profile_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

        if args.downmix_command != "show":
            print("Unknown downmix command.", file=sys.stderr)
            return 2

        layouts_path = repo_root / "ontology" / "layouts.yaml"
        registry_path = repo_root / "ontology" / "policies" / "downmix.yaml"
        try:
            matrix = resolve_downmix_matrix(
                repo_root=repo_root,
                source_layout_id=args.source,
                target_layout_id=args.target,
                policy_id=args.policy,
                layouts_path=layouts_path,
                registry_path=registry_path,
            )
            output = render_matrix(matrix, output_format=args.format)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0

    if args.command == "role-lexicon":
        if args.role_lexicon_command == "merge-suggestions":
            try:
                from mmo.core.role_lexicon import _load_yaml_object  # noqa: WPS433

                suggestions_payload = _load_yaml_object(
                    Path(args.suggestions), label="Suggestions"
                )

                base_payload: dict[str, Any] | None = None
                if isinstance(getattr(args, "base", None), str) and args.base.strip():
                    base_payload = _load_yaml_object(
                        Path(args.base), label="Base role lexicon"
                    )

                deny: frozenset[str] | None = None
                if isinstance(getattr(args, "deny", None), str) and args.deny.strip():
                    deny = frozenset(
                        t.strip().lower()
                        for t in args.deny.split(",")
                        if t.strip()
                    )

                allow: frozenset[str] | None = None
                if isinstance(getattr(args, "allow", None), str) and args.allow.strip():
                    allow = frozenset(
                        t.strip().lower()
                        for t in args.allow.split(",")
                        if t.strip()
                    )

                result = merge_suggestions_into_lexicon(
                    suggestions_payload,
                    base=base_payload,
                    deny=deny,
                    allow=allow,
                    max_per_role=args.max_per_role,
                )

                out_path = Path(args.out)
                if not getattr(args, "dry_run", False):
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    yaml_text = render_role_lexicon_yaml(result["merged"])
                    out_path.write_text(yaml_text, encoding="utf-8")

            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            # Build skip counts.
            skip_counts: dict[str, int] = {}
            for reason, tokens in sorted(result["keywords_skipped"].items()):
                skip_counts[reason] = len(tokens)

            fmt = getattr(args, "format", "json")
            if fmt == "json":
                summary: dict[str, Any] = {
                    "ok": True,
                    "out_path": out_path.as_posix(),
                    "dry_run": bool(getattr(args, "dry_run", False)),
                    "roles_added_count": result["roles_added_count"],
                    "keywords_added_count": result["keywords_added_count"],
                    "keywords_skipped_count": skip_counts,
                    "max_per_role_applied": result["max_per_role_applied"],
                }
                print(json.dumps(summary, indent=2, sort_keys=True))
            else:
                if getattr(args, "dry_run", False):
                    print("Dry run — no file written.")
                else:
                    print(f"Merged lexicon written to: {out_path.as_posix()}")
                print(f"Roles with new keywords: {result['roles_added_count']}")
                print(f"Keywords added: {result['keywords_added_count']}")
                if skip_counts:
                    for reason, count in sorted(skip_counts.items()):
                        print(f"  Skipped ({reason}): {count}")
                if result["max_per_role_applied"]:
                    print(f"Max-per-role cap ({args.max_per_role}) was applied.")

            return 0

        print("Unknown role-lexicon command.", file=sys.stderr)
        return 2

    return 0


# Backward-compatible re-exports for tests that import private symbols directly.
from mmo.cli_commands._helpers import _parse_output_formats_csv  # noqa: F811,F401
from mmo.cli_commands._workflows import _run_ui_workflow  # noqa: F811,F401
