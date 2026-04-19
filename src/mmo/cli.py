from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from mmo import __version_display__ as _MMO_VERSION

# ── Transcode constants (stdlib-only dep, always safe) ──────────────────────
try:
    from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS
except Exception:  # pragma: no cover - should never fail (stdlib only)
    LOSSLESS_OUTPUT_FORMATS = ("wav", "flac", "wv", "aiff", "alac")  # type: ignore[assignment]

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
    "perspective",
    "confidence",
)
_DEFAULT_RENDER_MANY_TRANSLATION_PROFILE_IDS: tuple[str, ...] = (
    "TRANS.MONO.COLLAPSE",
    "TRANS.DEVICE.PHONE",
    "TRANS.DEVICE.SMALL_SPEAKER",
)
_DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S = 30.0

# ── Heavy mmo imports — deferred so `--help` never raises on import failure ─
# All names are populated on success; _MMO_IMPORT_ERROR is set on failure.
# Command handlers check _MMO_IMPORT_ERROR after parse_args so that
# `python -m mmo --help` always exits 0 regardless of the environment.
_MMO_IMPORT_ERROR: Exception | None = None
try:
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
    from mmo.core.bus_plan import build_bus_plan
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
    from mmo.core.event_log import new_event_id, validate_event_log_jsonl, write_event_log
    from mmo.core.env_doctor import build_env_doctor_report, render_env_doctor_text
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
    from mmo.core.watch_folder import (
        DEFAULT_WATCH_TARGET_IDS,
        WatchFolderConfig,
        WatchQueueSnapshot,
        parse_watch_targets_csv,
        render_watch_queue_snapshot,
        run_watch_folder,
    )
    from mmo.core.timeline import load_timeline
    from mmo.core.variants import build_variant_plan, run_variant_plan
    from mmo.ui.tui import choose_from_list, multi_toggle, render_header, yes_no

    # ── Subcommand handlers (extracted to cli_commands/) ──
    from mmo.cli_commands._helpers import *  # noqa: F401,F403
    from mmo.cli_commands._analysis import *  # noqa: F401,F403
    from mmo.cli_commands._renderers import *  # noqa: F401,F403
    from mmo.cli_commands._stems import *  # noqa: F401,F403
    from mmo.cli_commands._scene import *  # noqa: F401,F403
    from mmo.cli_commands._registries import *  # noqa: F401,F403
    from mmo.cli_commands._workflows import *  # noqa: F401,F403
    from mmo.cli_commands._project import *  # noqa: F401,F403
    from mmo.cli_commands._gui_rpc import *  # noqa: F401,F403
    from mmo.cli_commands._utilities import *  # noqa: F401,F403
except Exception as _exc:  # pragma: no cover - import guard for --help safety
    _MMO_IMPORT_ERROR = _exc


def _normalize_cli_path_arg(path_text: str) -> str:
    """Treat backslashes as separators so POSIX runners can parse Windows-style input."""
    return path_text.replace("\\", "/")


def _resolve_user_profile_arg(
    profile_id_raw: str | None,
    profiles_path: Path,
) -> "dict[str, Any] | None":
    """Load a user style/safety profile by ID, or return None if no ID provided.

    Returns None (not an error) when ``profile_id_raw`` is empty/None so that
    callers that do not specify ``--user-profile`` get silent pass-through.
    Raises ``ValueError`` if the ID is non-empty but not found.
    """
    if not isinstance(profile_id_raw, str) or not profile_id_raw.strip():
        return None
    from mmo.core.profiles import get_profile  # noqa: WPS433
    return get_profile(profile_id_raw.strip(), profiles_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MMO command-line tools.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_MMO_VERSION}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan stems and write a report JSON.")
    scan_parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
    scan_parser.add_argument("--out", required=False, default=None, help="Path to output report JSON.")
    scan_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat lossy/unsupported formats as high-severity issues.",
    )
    scan_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Run the scan but do not write the output file; print the summary to stdout.",
    )
    scan_parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a human-readable summary of the scan to stdout.",
    )
    scan_parser.add_argument(
        "--format",
        choices=["json", "json-shared"],
        default="json-shared",
        help=(
            "Output format for stdout JSON. "
            "'json-shared' drops machine-local path anchors, hashes, and "
            "source tags for shell use. "
            "File output under --out stays on the full local report contract."
        ),
    )
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
        help="Optional preset ID from ontology/presets/index.json.",
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
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
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
    stems_bus_plan_parser = stems_subparsers.add_parser(
        "bus-plan",
        help="Build a deterministic bus_plan artifact from an existing stems_map JSON.",
    )
    stems_bus_plan_parser.add_argument(
        "--map",
        required=True,
        help="Path to an existing stems_map JSON.",
    )
    stems_bus_plan_parser.add_argument(
        "--out",
        required=True,
        help="Path to output bus_plan JSON.",
    )
    stems_bus_plan_parser.add_argument(
        "--csv",
        default=None,
        help="Optional path to write bus_plan assignment CSV.",
    )
    stems_bus_plan_parser.add_argument(
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
        help="Stem rel_path or stem_id to explain.",
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

    stems_roles_parser = stems_subparsers.add_parser(
        "roles",
        help="Show inferred roles for stems in a directory, with optional override writing.",
    )
    stems_roles_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    stems_roles_parser.add_argument(
        "--overrides",
        default=None,
        help="Optional path to a role overrides YAML to apply before display.",
    )
    stems_roles_parser.add_argument(
        "--write-overrides",
        default=None,
        dest="write_overrides",
        help="Write a role overrides YAML template to this path (pre-filled with inferred roles).",
    )
    stems_roles_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text table).",
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
        help="Optional preset ID from ontology/presets/index.json. May be provided multiple times.",
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
        "--role-overrides",
        default=None,
        dest="role_overrides",
        help="Path to a role overrides YAML (from 'mmo stems roles --write-overrides') applied before scene building.",
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
            "Comma-separated target tokens for --render-many "
            "(TARGET.*, LAYOUT.*, or shorthands like "
            "stereo/2.1/3.0/3.1/4.0/4.1/5.1/7.1/7.1.4/quad/lcr/binaural; "
            "default: TARGET.STEREO.2_0)."
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

    watch_parser = subparsers.add_parser(
        "watch",
        help=(
            "Watch a folder for new/updated stems and automatically run "
            "deterministic render-many batches."
        ),
    )
    watch_parser.add_argument(
        "folder",
        help="Folder to monitor for stem sets.",
    )
    watch_parser.add_argument(
        "--out",
        default=None,
        help=(
            "Output root for watch batches "
            "(default: <folder>/_mmo_watch_out)."
        ),
    )
    watch_parser.add_argument(
        "--targets",
        default=",".join(DEFAULT_WATCH_TARGET_IDS),
        help=(
            "Comma-separated render-many target tokens "
            "(TARGET.*, LAYOUT.*, or shorthands like "
            "stereo/2.1/3.0/3.1/4.0/4.1/5.1/7.1/7.1.4/quad/lcr/binaural; "
            "default: TARGET.STEREO.2_0,TARGET.SURROUND.5_1,TARGET.SURROUND.7_1)."
        ),
    )
    watch_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for render-many runs (default: PROFILE.ASSIST).",
    )
    watch_parser.add_argument(
        "--settle-seconds",
        type=float,
        default=3.0,
        help=(
            "Debounce window in seconds before processing changed stem sets "
            "(default: 3.0)."
        ),
    )
    watch_parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Watch loop poll interval in seconds (default: 0.5).",
    )
    watch_parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Process current stem sets once and exit (no long-running watch loop).",
    )
    watch_parser.add_argument(
        "--no-existing",
        action="store_true",
        default=False,
        help="Skip processing stem sets already present when the command starts.",
    )
    watch_parser.add_argument(
        "--visual-queue",
        action="store_true",
        default=False,
        help="Print an ASCII watch queue snapshot after each batch-state change.",
    )
    watch_parser.add_argument(
        "--cinematic-progress",
        action="store_true",
        default=False,
        help="Use cinematic mood labels in visual queue output.",
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

    report_parser = subparsers.add_parser(
        "report",
        help=(
            "Validate and export a report: emit JSON, PDF, and/or issue-centric recall sheet."
        ),
    )
    report_parser.add_argument("--report", required=True, help="Path to input report JSON.")
    report_parser.add_argument(
        "--json",
        dest="out_json",
        default=None,
        help="Output path for validated report JSON. Omit to skip.",
    )
    report_parser.add_argument(
        "--pdf",
        dest="out_pdf",
        default=None,
        help="Output path for report PDF (requires reportlab).",
    )
    report_parser.add_argument(
        "--recall",
        dest="out_recall",
        default=None,
        help="Output path for issue-centric recall sheet CSV.",
    )
    report_parser.add_argument(
        "--no-measurements",
        action="store_true",
        help="Omit Measurements section from PDF output.",
    )
    report_parser.add_argument(
        "--no-gates",
        action="store_true",
        help="Omit gate fields from PDF output.",
    )
    report_parser.add_argument(
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

    review_parser = subparsers.add_parser(
        "review",
        help=(
            "Show pending-approval recommendations from a report in human-readable form. "
            "Prints rec IDs and the --approve-rec flags needed for safe-render."
        ),
    )
    review_parser.add_argument(
        "report",
        help="Path to report JSON, or a directory containing report.json.",
    )
    review_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    review_parser.add_argument(
        "--risk",
        choices=["low", "medium", "high"],
        default=None,
        help="Filter to recommendations of this risk level only.",
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
        help="Optional preset ID from ontology/presets/index.json.",
    )
    render_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    render_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
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

    try:
        safe_render_parser = subparsers.add_parser(
            "safe-render",
            help=(
                "Full plugin-chain render: detect -> resolve -> gate -> render. "
                "Bounded authority: low-impact auto-applied, medium/high require explicit approval. "
                "Produces safe-run receipt + optional QA report with spectral slopes."
            ),
        )
    except Exception as e:
        print(f"DEBUG CLI PARSER safe-render: {e}")
        raise
    safe_render_parser.add_argument(
        "--report",
        required=False,
        default=None,
        help=(
            "Path to report JSON (from mmo analyze or equivalent). "
            "Required unless --demo is used."
        ),
    )
    safe_render_parser.add_argument(
        "--scene",
        default=None,
        help=(
            "Optional explicit scene JSON to use for placement rendering. "
            "When provided, this scene is preferred over auto-built scene data."
        ),
    )
    safe_render_parser.add_argument(
        "--scene-locks",
        default=None,
        dest="scene_locks",
        help=(
            "Optional scene build lock overrides file (YAML or JSON). "
            "Applied before placement policy."
        ),
    )
    safe_render_parser.add_argument(
        "--scene-strict",
        action="store_true",
        default=False,
        dest="scene_strict",
        help=(
            "When --scene is provided, fail on scene-lint errors. Also fail when "
            "the selected scene references missing session stems or unknown role IDs."
        ),
    )
    safe_render_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory (default: plugins).",
    )
    safe_render_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
    )
    safe_render_parser.add_argument(
        "--target",
        default="stereo",
        help=(
            "Render target token (TARGET.*, LAYOUT.*, or shorthand like "
            "stereo/2.1/3.0/3.1/4.0/4.1/5.1/7.1/7.1.4/quad/lcr/binaural). "
            "Default: stereo."
        ),
    )
    safe_render_parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for rendered audio files (required for full render).",
    )
    safe_render_parser.add_argument(
        "--out-manifest",
        default=None,
        help="Optional path to output render manifest JSON.",
    )
    safe_render_parser.add_argument(
        "--receipt-out",
        default=None,
        help="Path to write safe-run receipt JSON.",
    )
    safe_render_parser.add_argument(
        "--qa-out",
        default=None,
        help="Path to write render QA report JSON (with spectral slope metrics).",
    )
    safe_render_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Plan only: show what would be rendered without writing audio.",
    )
    safe_render_parser.add_argument(
        "--approve",
        default=None,
        help=(
            "Legacy approval override for blocked recommendations. "
            "Prefer --approve-rec / --approve-file. "
            "Use 'all' to approve every approval-blocked recommendation, 'none' "
            "to approve nothing, or a comma-separated list of recommendation_id / issue_id values."
        ),
    )
    safe_render_parser.add_argument(
        "--approve-rec",
        action="append",
        dest="approve_rec_ids",
        default=None,
        help=(
            "Explicitly approve one recommendation_id for render. "
            "Repeat the flag to approve multiple recommendations."
        ),
    )
    safe_render_parser.add_argument(
        "--approve-file",
        default=None,
        help=(
            "Path to a JSON file containing a list of approved recommendation_id values."
        ),
    )
    safe_render_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for render gating (default: PROFILE.ASSIST).",
    )
    safe_render_parser.add_argument(
        "--user-profile",
        default=None,
        dest="user_profile_id",
        help="Optional user style/safety profile ID (e.g. PROFILE.USER.CONSERVATIVE).",
    )
    safe_render_parser.add_argument(
        "--output-formats",
        default=None,
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    safe_render_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    safe_render_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from ontology/presets/index.json.",
    )
    safe_render_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files.",
    )
    safe_render_parser.add_argument(
        "--render-many",
        action="store_true",
        dest="render_many",
        help=(
            "Render to multiple targets in one pass (mix-once, render-many). "
            "Default targets: stereo, 5.1, 7.1.4. Use --render-many-targets to override."
        ),
    )
    safe_render_parser.add_argument(
        "--render-many-targets",
        default=None,
        dest="render_many_targets",
        help=(
            "Comma-separated target tokens for --render-many "
            "(TARGET.*, LAYOUT.*, or shorthands like "
            "stereo/2.1/3.0/3.1/4.0/4.1/5.1/7.1/7.1.4/quad/lcr/binaural) "
            "(default: stereo,5.1,7.1.4)."
        ),
    )
    safe_render_parser.add_argument(
        "--layout-standard",
        default="SMPTE",
        dest="layout_standard",
        choices=["SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF"],
        help=(
            "Channel ordering standard for render I/O: "
            "SMPTE (default, WAV/FLAC/FFmpeg/broadcast order), "
            "FILM (Pro Tools/cinema), LOGIC_PRO (Apple/DTS), "
            "VST3 (Cubase/Nuendo 7.1+), or AAF (metadata-driven)."
        ),
    )
    safe_render_parser.add_argument(
        "--preview-headphones",
        action="store_true",
        default=False,
        help=(
            "Render additional deterministic stereo headphone preview WAV files "
            "using conservative binaural virtualization."
        ),
    )
    safe_render_parser.add_argument(
        "--allow-empty-outputs",
        action="store_true",
        default=False,
        help=(
            "Allow exit code 0 when renderer stage emits zero outputs. "
            "Default behavior is to fail and emit ISSUE.RENDER.NO_OUTPUTS."
        ),
    )
    safe_render_parser.add_argument(
        "--export-stems",
        action="store_true",
        default=False,
        help=(
            "Export deterministic stem copy artifacts for inspection "
            "(written under out-dir/stems/)."
        ),
    )
    safe_render_parser.add_argument(
        "--export-buses",
        action="store_true",
        default=False,
        help=(
            "Export scene-aware subbus WAV artifacts (Drums/Bass/Music/Vox/FX) "
            "alongside each layout master."
        ),
    )
    safe_render_parser.add_argument(
        "--export-master",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Enable or disable master WAV export per layout "
            "(default: --export-master)."
        ),
    )
    safe_render_parser.add_argument(
        "--export-layouts",
        default=None,
        help=(
            "Optional comma-separated target/layout tokens limiting which layout "
            "artifacts are exported (for example: stereo,5.1,LAYOUT.7_1_4)."
        ),
    )
    safe_render_parser.add_argument(
        "--live-progress",
        action="store_true",
        default=False,
        help=(
            "Emit real-time explainable progress logs to stderr "
            "(what/why/where/confidence + progress + ETA)."
        ),
    )
    safe_render_parser.add_argument(
        "--cancel-file",
        default=None,
        help=(
            "Optional cancellation sentinel path. If the file exists during "
            "safe-render execution, the run exits with code 130."
        ),
    )
    safe_render_parser.add_argument(
        "--demo",
        action="store_true",
        default=False,
        help=(
            "Run the render-many-standards demo: load the built-in 7.1.4 "
            "SMPTE+FILM fixture from fixtures/immersive/ and render to all "
            "5 channel-ordering standards (SMPTE, FILM, LOGIC_PRO, VST3, AAF) "
            "in parallel. Implies --dry-run. Use --out-dir to set the output root."
        ),
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
        help="Optional preset ID from ontology/presets/index.json.",
    )
    apply_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    apply_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
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
        "--include-plugins",
        action="store_true",
        help="Embed plugin config schema pointers/hashes in ui_bundle.json.",
    )
    bundle_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory used by --include-plugins.",
    )
    bundle_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
    )
    bundle_parser.add_argument(
        "--include-plugin-layouts",
        action="store_true",
        help=(
            "When used with --include-plugins, also include ui_layout path/hash metadata "
            "for each plugin."
        ),
    )
    bundle_parser.add_argument(
        "--include-plugin-ui-hints",
        action="store_true",
        help=(
            "When used with --include-plugins, also include ui_hints extracted "
            "from each plugin config_schema."
        ),
    )
    bundle_parser.add_argument(
        "--include-plugin-layout-snapshots",
        action="store_true",
        help=(
            "When used with --include-plugin-layouts, also generate deterministic "
            "ui_layout_snapshot metadata (path/hash/violations_count)."
        ),
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
        "--render-execute",
        default=None,
        help="Optional path to render_execute JSON artifact.",
    )
    bundle_parser.add_argument(
        "--render-preflight",
        default=None,
        help="Optional path to render_preflight JSON artifact.",
    )
    bundle_parser.add_argument(
        "--event-log",
        default=None,
        help="Optional path to event log JSONL artifact.",
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

    plugin_parser = subparsers.add_parser(
        "plugin",
        help="Offline plugin marketplace and discovery tools.",
    )
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_list_parser = plugin_subparsers.add_parser(
        "list",
        help="List entries from the bundled offline plugin marketplace index.",
    )
    plugin_list_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory used to mark installed plugins.",
    )
    plugin_list_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
    )
    plugin_list_parser.add_argument(
        "--index",
        default=None,
        help="Optional path to plugin index YAML (defaults to bundled ontology/plugin_index.yaml).",
    )
    plugin_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for plugin marketplace list.",
    )
    plugin_update_parser = plugin_subparsers.add_parser(
        "update",
        help="Write a deterministic local snapshot of the offline marketplace index.",
    )
    plugin_update_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path for the snapshot JSON.",
    )
    plugin_update_parser.add_argument(
        "--index",
        default=None,
        help="Optional path to plugin index YAML (defaults to bundled ontology/plugin_index.yaml).",
    )
    plugin_update_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for plugin marketplace update receipt.",
    )
    plugin_install_parser = plugin_subparsers.add_parser(
        "install",
        help="Install one plugin from the bundled offline marketplace index.",
    )
    plugin_install_parser.add_argument(
        "plugin_id",
        help="Marketplace plugin_id to install.",
    )
    plugin_install_parser.add_argument(
        "--plugins",
        default=None,
        help=(
            "Optional plugin root for installation "
            "(default: user plugin root ~/.mmo/plugins)."
        ),
    )
    plugin_install_parser.add_argument(
        "--index",
        default=None,
        help="Optional path to plugin index YAML (defaults to bundled ontology/plugin_index.yaml).",
    )
    plugin_install_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for plugin marketplace install receipt.",
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
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
    )
    plugins_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the plugin list.",
    )
    plugins_validate_parser = plugins_subparsers.add_parser(
        "validate",
        help="Validate a plugin root or the bundled plugin set.",
    )
    plugins_validate_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    plugins_validate_parser.add_argument(
        "--bundled-only",
        action="store_true",
        help="Validate only the packaged built-in plugin directory.",
    )
    plugins_validate_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for plugin validation.",
    )
    plugins_ui_lint_parser = plugins_subparsers.add_parser(
        "ui-lint",
        help="Lint plugin ui_layout and x_mmo_ui contracts together.",
    )
    plugins_ui_lint_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    plugins_ui_lint_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
    )
    plugins_ui_lint_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for plugin UI contract linting.",
    )
    plugins_show_parser = plugins_subparsers.add_parser(
        "show",
        help="Show one plugin record and config schema metadata.",
    )
    plugins_show_parser.add_argument(
        "plugin_id",
        nargs="?",
        default=None,
        help=(
            "Optional plugin ID (e.g., PLUGIN.RENDERER.SAFE). "
            "When omitted, selects the first plugin with config_schema + ui_layout."
        ),
    )
    plugins_show_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    plugins_show_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
    )
    plugins_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for plugin details.",
    )
    plugins_show_parser.add_argument(
        "--include-ui-layout-snapshot",
        action="store_true",
        help=(
            "Generate and include deterministic ui_layout_snapshot metadata "
            "(path/hash/violations_count) when ui_layout is present."
        ),
    )
    plugins_show_parser.add_argument(
        "--include-ui-hints",
        action="store_true",
        help=(
            "Extract and include ui_hints metadata from plugin config_schema "
            "(pointer/hash/hint_count/hints)."
        ),
    )
    plugins_self_test_parser = plugins_subparsers.add_parser(
        "self-test",
        help="Run a deterministic plugin-chain self-test and emit artifacts.",
    )
    plugins_self_test_parser.add_argument(
        "plugin_id",
        help="Plugin stage ID (for example: gain_v0, tilt_eq_v0).",
    )
    plugins_self_test_parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for input/output WAV and JSON artifacts.",
    )
    plugins_self_test_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing self-test output files in --out-dir.",
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
        "--report",
        default=None,
        help=(
            "Optional analyzed report JSON used to derive bounded preview-only "
            "feature initialization and loudness safety context."
        ),
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
        help="Show extended fields and notes in text output.",
    )
    targets_show_parser = targets_subparsers.add_parser("show", help="Show one render target.")
    targets_show_parser.add_argument(
        "target_id",
        help="Render target ID (e.g., TARGET.STEREO.2_0).",
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

    ontology_parser = subparsers.add_parser(
        "ontology",
        help="Ontology integrity tools.",
    )
    ontology_subparsers = ontology_parser.add_subparsers(
        dest="ontology_command",
        required=True,
    )
    ontology_validate_parser = ontology_subparsers.add_parser(
        "validate",
        help=(
            "Load all ontology YAML files and report schema compliance. "
            "Checks required fields, ID-prefix conventions, and file presence."
        ),
    )
    ontology_validate_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for validation results.",
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

    try:
        profile_parser = subparsers.add_parser(
            "profile",
            help="User style/safety profile tools (DoD 4.7).",
        )
        profile_subparsers = profile_parser.add_subparsers(
            dest="profile_command",
            required=True,
        )
        profile_list_parser = profile_subparsers.add_parser(
            "list",
            help="List user style/safety profiles.",
        )
        profile_list_parser.add_argument(
            "--format",
            choices=["json", "text"],
            default="text",
            help="Output format for profile list.",
        )
        profile_show_parser = profile_subparsers.add_parser(
            "show",
            help="Show one user style/safety profile.",
        )
        profile_show_parser.add_argument(
            "profile_id",
            help="Profile ID (e.g., PROFILE.USER.CONSERVATIVE).",
        )
        profile_show_parser.add_argument(
            "--format",
            choices=["json", "text"],
            default="text",
            help="Output format for profile details.",
        )
        profile_apply_parser = profile_subparsers.add_parser(
            "apply",
            help="Apply a profile to a scene and emit updated preflight options.",
        )
        profile_apply_parser.add_argument(
            "profile_id",
            help="Profile ID to apply (e.g., PROFILE.USER.BROADCAST).",
        )
        profile_apply_parser.add_argument(
            "--scene",
            default=None,
            help="Optional path to a scene/report JSON to validate against the profile.",
        )
        profile_apply_parser.add_argument(
            "--format",
            choices=["json", "text"],
            default="json",
            help="Output format for apply result.",
        )
    except Exception as e:
        print(f"DEBUG CLI PARSER profile: {e}")
        raise

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

    ui_hints_parser = subparsers.add_parser(
        "ui-hints",
        help="Plugin config schema UI hint tools.",
    )
    ui_hints_subparsers = ui_hints_parser.add_subparsers(
        dest="ui_hints_command",
        required=True,
    )
    ui_hints_lint_parser = ui_hints_subparsers.add_parser(
        "lint",
        help="Lint x_mmo_ui blocks inside a plugin config schema.",
    )
    ui_hints_lint_parser.add_argument(
        "--schema",
        required=True,
        help="Path to plugin config schema JSON.",
    )
    ui_hints_lint_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for lint results.",
    )
    ui_hints_extract_parser = ui_hints_subparsers.add_parser(
        "extract",
        help="Extract x_mmo_ui blocks into a deterministic JSON artifact.",
    )
    ui_hints_extract_parser.add_argument(
        "--schema",
        required=True,
        help="Path to plugin config schema JSON.",
    )
    ui_hints_extract_parser.add_argument(
        "--out",
        required=True,
        help="Path to output ui_hints JSON.",
    )
    ui_hints_extract_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists.",
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
        help="Show deterministic, allowlisted project artifact metadata.",
    )
    project_show_parser.add_argument(
        "project_dir",
        nargs="?",
        help="Path to the project directory.",
    )
    project_show_parser.add_argument(
        "--format",
        choices=["json", "json-shared", "text"],
        default="json-shared",
        help=(
            "Output format for project show output. "
            "'json-shared' drops machine-local path fields for shell use. "
            "Use 'json' when local tooling needs the full GUI or RPC path contract."
        ),
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
        help="Optional preset ID from ontology/presets/index.json. May be provided multiple times.",
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
            "Comma-separated target tokens for --render-many "
            "(TARGET.*, LAYOUT.*, or shorthands like "
            "stereo/2.1/3.0/3.1/4.0/4.1/5.1/7.1/7.1.4/quad/lcr/binaural; "
            "default: TARGET.STEREO.2_0)."
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

    project_save_parser = project_subparsers.add_parser(
        "save",
        help="Save project session JSON (scene + history + receipts).",
    )
    project_save_parser.add_argument(
        "project_dir",
        help="Path to the project scaffold directory.",
    )
    project_save_parser.add_argument(
        "--session",
        default=None,
        help="Output path for project session JSON (default: <project_dir>/project_session.json).",
    )
    project_save_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing session JSON.",
    )
    project_save_parser.add_argument(
        "--format",
        choices=["json", "json-shared"],
        default="json-shared",
        help=(
            "Output format for project save output. "
            "'json-shared' narrows path fields for shared logs. "
            "Use 'json' when local tooling needs full machine-local paths."
        ),
    )

    project_load_parser = project_subparsers.add_parser(
        "load",
        help="Load project session JSON into scene/history/receipt artifacts.",
    )
    project_load_parser.add_argument(
        "project_dir",
        help="Path to the project scaffold directory.",
    )
    project_load_parser.add_argument(
        "--session",
        default=None,
        help="Input path for project session JSON (default: <project_dir>/project_session.json).",
    )
    project_load_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing scene/history/receipt files.",
    )
    project_load_parser.add_argument(
        "--format",
        choices=["json", "json-shared"],
        default="json-shared",
        help=(
            "Output format for project load output. "
            "'json-shared' narrows path fields for shared logs. "
            "Use 'json' when local tooling needs full machine-local paths."
        ),
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
    project_validate_parser.add_argument(
        "--render-compat",
        action="store_true",
        help=(
            "Also validate render_request/render_plan/render_report compatibility "
            "when corresponding files exist."
        ),
    )

    project_bundle_parser = project_subparsers.add_parser(
        "bundle",
        help="Build ui_bundle.json from allowlisted project artifacts.",
    )
    project_bundle_parser.add_argument(
        "project_dir",
        help="Path to the project scaffold directory.",
    )
    project_bundle_parser.add_argument(
        "--out",
        required=True,
        help="Path to output ui_bundle.json.",
    )
    project_bundle_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output bundle.",
    )
    project_bundle_parser.add_argument(
        "--include-plugins",
        action="store_true",
        help="Embed plugin config schema pointers/hashes in ui_bundle.json.",
    )
    project_bundle_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory used by --include-plugins.",
    )
    project_bundle_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
    )
    project_bundle_parser.add_argument(
        "--include-plugin-layouts",
        action="store_true",
        help=(
            "When used with --include-plugins, also include ui_layout path/hash metadata "
            "for each plugin."
        ),
    )
    project_bundle_parser.add_argument(
        "--include-plugin-ui-hints",
        action="store_true",
        help=(
            "When used with --include-plugins, also include ui_hints extracted "
            "from each plugin config_schema."
        ),
    )
    project_bundle_parser.add_argument(
        "--include-plugin-layout-snapshots",
        action="store_true",
        help=(
            "When used with --include-plugin-layouts, also generate deterministic "
            "ui_layout_snapshot metadata (path/hash/violations_count)."
        ),
    )
    project_bundle_parser.add_argument(
        "--render-preflight",
        default=None,
        help="Optional path to render_preflight JSON artifact.",
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

    project_build_gui_parser = project_subparsers.add_parser(
        "build-gui",
        help="Run deterministic GUI build pipeline for an existing project.",
    )
    project_build_gui_parser.add_argument(
        "project_dir",
        help="Path to the project scaffold directory.",
    )
    project_build_gui_parser.add_argument(
        "--pack-out",
        required=True,
        help="Path to output project zip.",
    )
    project_build_gui_parser.add_argument(
        "--scan",
        action="store_true",
        help="Run scan step before render/bundle/validate.",
    )
    project_build_gui_parser.add_argument(
        "--scan-stems",
        default=None,
        help="Path to stems directory used by --scan.",
    )
    project_build_gui_parser.add_argument(
        "--scan-out",
        default=None,
        help="Report output path for --scan (must be <project_dir>/report.json).",
    )
    project_build_gui_parser.add_argument(
        "--event-log",
        action="store_true",
        help="Also write renders/event_log.jsonl during render-run step.",
    )
    project_build_gui_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite force-guarded outputs for this pipeline.",
    )
    project_build_gui_parser.add_argument(
        "--event-log-force",
        action="store_true",
        help="Overwrite renders/event_log.jsonl when --event-log is used.",
    )
    project_build_gui_parser.add_argument(
        "--include-plugins",
        action="store_true",
        help="Embed plugin config schema pointers/hashes in ui_bundle.json.",
    )
    project_build_gui_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory used by --include-plugins.",
    )
    project_build_gui_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
    )
    project_build_gui_parser.add_argument(
        "--include-plugin-layouts",
        action="store_true",
        help=(
            "When used with --include-plugins, also include ui_layout path/hash metadata "
            "for each plugin."
        ),
    )
    project_build_gui_parser.add_argument(
        "--include-plugin-ui-hints",
        action="store_true",
        help=(
            "When used with --include-plugins, also include ui_hints extracted "
            "from each plugin config_schema."
        ),
    )
    project_build_gui_parser.add_argument(
        "--include-plugin-layout-snapshots",
        action="store_true",
        help=(
            "When used with --include-plugin-layouts, also generate deterministic "
            "ui_layout_snapshot metadata (path/hash/violations_count)."
        ),
    )

    project_render_init_parser = project_subparsers.add_parser(
        "render-init",
        help="Create a render scaffold inside an existing project.",
    )
    project_render_init_parser.add_argument(
        "project_dir",
        help="Path to the project scaffold directory.",
    )
    project_render_init_parser.add_argument(
        "--target-layout",
        default=None,
        help="Target layout ID (e.g. LAYOUT.5_1). Mutually exclusive with --target-layouts.",
    )
    project_render_init_parser.add_argument(
        "--target-layouts",
        default=None,
        help="Comma-separated target layout IDs (e.g. LAYOUT.2_0,LAYOUT.5_1). Mutually exclusive with --target-layout.",
    )
    project_render_init_parser.add_argument(
        "--target-ids",
        default=None,
        help=(
            "Optional comma-separated target tokens for options.target_ids "
            "(TARGET.*, LAYOUT.*, or shorthands; e.g. TARGET.STEREO.2_0,LAYOUT.BINAURAL,binaural)."
        ),
    )
    project_render_init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing renders/render_request.json.",
    )

    project_write_render_request_parser = project_subparsers.add_parser(
        "write-render-request",
        help="Safely edit allowlisted fields in renders/render_request.json.",
    )
    project_write_render_request_parser.add_argument(
        "project_dir",
        help="Path to the project scaffold directory.",
    )
    project_write_render_request_parser.add_argument(
        "--set",
        dest="set_entries",
        action="append",
        default=[],
        metavar="key=value",
        help=(
            "Editable fields only: dry_run, max_theoretical_quality, target_ids, "
            "target_layout_ids, plugin_chain, policies. "
            "Repeat --set for multiple updates."
        ),
    )

    project_render_run_parser = project_subparsers.add_parser(
        "render-run",
        help="Run render plan+report using project-standard paths.",
    )
    project_render_run_parser.add_argument(
        "project_dir",
        help="Path to the project scaffold directory.",
    )
    project_render_run_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing renders/render_plan.json and renders/render_report.json.",
    )
    project_render_run_parser.add_argument(
        "--event-log",
        action="store_true",
        help="Also write renders/event_log.jsonl.",
    )
    project_render_run_parser.add_argument(
        "--execute",
        action="store_true",
        help="Also write renders/render_execute.json.",
    )
    project_render_run_parser.add_argument(
        "--execute-out",
        default=None,
        help="Optional path to render_execute JSON (implies execute artifact).",
    )
    project_render_run_parser.add_argument(
        "--preflight",
        action="store_true",
        help="Also write renders/render_preflight.json.",
    )
    project_render_run_parser.add_argument(
        "--preflight-force",
        action="store_true",
        help="Overwrite existing renders/render_preflight.json when --preflight is used.",
    )
    project_render_run_parser.add_argument(
        "--event-log-force",
        action="store_true",
        help="Overwrite existing renders/event_log.jsonl when --event-log is used.",
    )
    project_render_run_parser.add_argument(
        "--execute-force",
        action="store_true",
        help=(
            "Overwrite existing render_execute output when --execute or "
            "--execute-out is used."
        ),
    )
    project_render_run_parser.add_argument(
        "--qa",
        action="store_true",
        help="Also write renders/render_qa.json.",
    )
    project_render_run_parser.add_argument(
        "--qa-out",
        default=None,
        help="Optional path to render_qa JSON (implies QA artifact).",
    )
    project_render_run_parser.add_argument(
        "--qa-force",
        action="store_true",
        help="Overwrite existing render_qa output when --qa or --qa-out is used.",
    )
    project_render_run_parser.add_argument(
        "--qa-enforce",
        action="store_true",
        help=(
            "Return exit code 2 when render QA has severity=error issues "
            "(requires --qa or --qa-out)."
        ),
    )
    project_render_run_parser.add_argument(
        "--recall-sheet",
        action="store_true",
        help="Also write renders/recall_sheet.csv with scene/preflight/profile context.",
    )
    project_render_run_parser.add_argument(
        "--recall-sheet-force",
        action="store_true",
        help="Overwrite existing renders/recall_sheet.csv (requires --recall-sheet).",
    )

    gates_parser = subparsers.add_parser("gates", help="Gates policy registry tools.")
    gates_subparsers = gates_parser.add_subparsers(dest="gates_command", required=True)
    gates_list_parser = gates_subparsers.add_parser("list", help="List gates policy IDs.")
    gates_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the gates policy list.",
    )
    gates_show_parser = gates_subparsers.add_parser("show", help="Show one gates policy.")
    gates_show_parser.add_argument("policy_id", help="Policy ID (e.g., POLICY.GATES.CORE_V0).")
    gates_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for gates policy details.",
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
        help="Optional preset ID from ontology/presets/index.json.",
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
        help="Optional preset ID from ontology/presets/index.json.",
    )
    downmix_render_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    downmix_render_parser.add_argument(
        "--plugin-dir",
        default=None,
        help="Optional external plugins directory (default: ~/.mmo/plugins).",
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
        help="Build a deterministic scene JSON from report or stems map + bus plan inputs.",
    )
    scene_build_parser.add_argument(
        "--report",
        default=None,
        help="Path to report JSON.",
    )
    scene_build_parser.add_argument(
        "--map",
        default=None,
        help="Path to stems_map JSON (for bus-plan-driven scene intent scaffolding).",
    )
    scene_build_parser.add_argument(
        "--bus",
        default=None,
        help="Path to bus_plan JSON (for bus-plan-driven scene intent scaffolding).",
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
    scene_build_parser.add_argument(
        "--locks",
        default=None,
        help="Optional path to scene build locks/overrides YAML.",
    )
    scene_build_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID recorded in scene metadata for map+bus build mode.",
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
    scene_lint_parser = scene_subparsers.add_parser(
        "lint",
        help="Lint a scene JSON for common QA issues before render.",
    )
    scene_lint_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_lint_parser.add_argument(
        "--scene-locks",
        default=None,
        dest="scene_locks",
        help="Optional path to scene build locks/overrides YAML or JSON.",
    )
    scene_lint_parser.add_argument(
        "--locks",
        default=None,
        dest="scene_locks",
        help=argparse.SUPPRESS,
    )
    scene_lint_parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write lint report JSON.",
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
            "Comma-separated target tokens "
            "(TARGET.*, LAYOUT.*, or shorthands; "
            "e.g., TARGET.STEREO.2_0,LAYOUT.BINAURAL,binaural)."
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

    render_request_parser = subparsers.add_parser(
        "render-request",
        help="Render request artifact tools.",
    )
    render_request_subparsers = render_request_parser.add_subparsers(
        dest="render_request_command",
        required=True,
    )
    render_request_template_parser = render_request_subparsers.add_parser(
        "template",
        help="Generate a minimal, schema-valid render_request.json template.",
    )
    render_request_template_parser.add_argument(
        "--target-layout",
        default=None,
        help="Target layout ID (e.g. LAYOUT.5_1). Mutually exclusive with --target-layouts.",
    )
    render_request_template_parser.add_argument(
        "--target-layouts",
        default=None,
        help="Comma-separated target layout IDs (e.g. LAYOUT.2_0,LAYOUT.5_1). Mutually exclusive with --target-layout.",
    )
    render_request_template_parser.add_argument(
        "--scene",
        default=None,
        help="Optional path to scene JSON (POSIX-normalized in output).",
    )
    render_request_template_parser.add_argument(
        "--routing-plan",
        default=None,
        help="Optional path to routing plan JSON (POSIX-normalized in output).",
    )
    render_request_template_parser.add_argument(
        "--out",
        required=True,
        help="Path to output render_request JSON.",
    )
    render_request_template_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )

    try:
        render_preflight_parser = subparsers.add_parser(
            "render-preflight",
            help="Run deterministic preflight checks against render_plan job inputs.",
        )
        render_preflight_parser.add_argument(
            "--plan",
            required=True,
            help="Path to render_plan JSON.",
        )
        render_preflight_parser.add_argument(
            "--out",
            required=True,
            help="Path to output render_preflight JSON.",
        )
        render_preflight_parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite output file if it already exists.",
        )
    except Exception as e:
        print(f"DEBUG CLI PARSER render-preflight: {e}")
        raise

    ui_layout_snapshot_parser = subparsers.add_parser(
        "ui-layout-snapshot",
        help=(
            "Build a deterministic UI layout snapshot with computed widget bounds "
            "and layout violations."
        ),
    )
    ui_layout_snapshot_parser.add_argument(
        "--layout",
        required=True,
        help="Path to ui_layout JSON.",
    )
    ui_layout_snapshot_parser.add_argument(
        "--viewport",
        required=True,
        help="Viewport in WxH form (for example: 1280x720).",
    )
    ui_layout_snapshot_parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Viewport scale multiplier (default: 1.0).",
    )
    ui_layout_snapshot_parser.add_argument(
        "--out",
        required=True,
        help="Path to output ui_layout_snapshot JSON.",
    )
    ui_layout_snapshot_parser.add_argument(
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

    render_compat_parser = subparsers.add_parser(
        "render-compat",
        help="Validate deterministic compatibility across render request/plan/report artifacts.",
    )
    render_compat_parser.add_argument(
        "--request",
        required=True,
        help="Path to render_request JSON.",
    )
    render_compat_parser.add_argument(
        "--plan",
        required=True,
        help="Path to render_plan JSON.",
    )
    render_compat_parser.add_argument(
        "--report",
        default=None,
        help="Optional path to render_report JSON.",
    )
    render_compat_parser.add_argument(
        "--out",
        default=None,
        help="Optional path to output render compatibility JSON.",
    )
    render_compat_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )

    try:
        render_run_parser = subparsers.add_parser(
            "render-run",
            help=(
                "Build a render plan from a render_request + scene, "
                "then execute render-run (or dry-run) and write a render report."
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
            "--preflight-out",
            default=None,
            help="Optional path to output render_preflight JSON.",
        )
        render_run_parser.add_argument(
            "--preflight-force",
            action="store_true",
            help="Overwrite preflight output file if it already exists.",
        )
        render_run_parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite output files if they already exist.",
        )
        render_run_parser.add_argument(
            "--event-log-out",
            default=None,
            help="Optional path to output event log JSONL.",
        )
        render_run_parser.add_argument(
            "--event-log-force",
            action="store_true",
            help="Overwrite event log output file if it already exists.",
        )
        render_run_parser.add_argument(
            "--execute-out",
            default=None,
            help=(
                "Optional path to output render_execute JSON "
                "(requires request options dry_run=false)."
            ),
        )
        render_run_parser.add_argument(
            "--execute-force",
            action="store_true",
            help="Overwrite execute output file if it already exists.",
        )
        render_run_parser.add_argument(
            "--qa-out",
            default=None,
            help=(
                "Optional path to output render_qa JSON "
                "(requires request options dry_run=false)."
            ),
        )
        render_run_parser.add_argument(
            "--qa-force",
            action="store_true",
            help="Overwrite QA output file if it already exists.",
        )
        render_run_parser.add_argument(
            "--qa-enforce",
            action="store_true",
            help="Return exit code 2 when render QA contains any severity=error issue.",
        )
    except Exception as e:
        print(f"DEBUG CLI PARSER render-run: {e}")
        raise

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

    env_parser = subparsers.add_parser("env", help="Environment diagnostic tools.")
    env_subparsers = env_parser.add_subparsers(
        dest="env_command",
        required=True,
    )
    env_doctor_parser = env_subparsers.add_parser(
        "doctor",
        help="Print a deterministic environment diagnostics report.",
    )
    env_doctor_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json).",
    )

    gui_parser = subparsers.add_parser(
        "gui",
        help="Framework-agnostic GUI bridge tools.",
    )
    gui_subparsers = gui_parser.add_subparsers(
        dest="gui_command",
        required=True,
    )
    gui_subparsers.add_parser(
        "rpc",
        help="Run newline-delimited JSON RPC over stdin/stdout.",
    )

    event_log_parser = subparsers.add_parser("event-log", help="Event log artifact tools.")
    event_log_subparsers = event_log_parser.add_subparsers(
        dest="event_log_command",
        required=True,
    )
    event_log_demo_parser = event_log_subparsers.add_parser(
        "demo",
        help="Write a deterministic demo event log JSONL.",
    )
    event_log_demo_parser.add_argument(
        "--out",
        required=True,
        help="Path to output event log JSONL.",
    )
    event_log_demo_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )
    event_log_validate_parser = event_log_subparsers.add_parser(
        "validate",
        help="Validate an event log JSONL file.",
    )
    event_log_validate_parser.add_argument(
        "--in",
        dest="in_path",
        required=True,
        help="Path to event log JSONL input.",
    )
    event_log_validate_parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write validation report JSON.",
    )
    event_log_validate_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite validation output if it already exists.",
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
    if len(raw_argv) >= 2 and raw_argv[0] == "ui" and raw_argv[1] == "layout-snapshot":
        raw_argv = ["ui-layout-snapshot", *raw_argv[2:]]
    if len(raw_argv) >= 2 and raw_argv[0] == "ui" and raw_argv[1] == "hints":
        raw_argv = ["ui-hints", *raw_argv[2:]]
    args = parser.parse_args(raw_argv)
    if _MMO_IMPORT_ERROR is not None:
        print(
            f"MMO failed to load required modules: {_MMO_IMPORT_ERROR}",
            file=sys.stderr,
        )
        print(
            "Try: pip install 'mix-marriage-offline[dev,truth,pdf]'",
            file=sys.stderr,
        )
        return 1

    plugin_dir_override = getattr(args, "plugin_dir", None)
    if isinstance(plugin_dir_override, str) and plugin_dir_override.strip():
        os.environ["MMO_PLUGIN_DIR"] = plugin_dir_override.strip()

    from mmo.resources import (
        _repo_checkout_root,
        ontology_dir,
        presets_dir as _presets_dir_fn,
        schemas_dir,
    )
    _checkout_root = _repo_checkout_root()
    tools_dir = _checkout_root / "tools" if _checkout_root is not None else Path("tools")
    presets_dir = _presets_dir_fn()
    schemas = schemas_dir()
    ontology = ontology_dir()

    if args.command == "scan":
        out_path = Path(args.out) if args.out else None
        return _run_scan(
            tools_dir,
            Path(args.stems_dir),
            out_path,
            args.meters,
            args.peak,
            args.format,
            strict=args.strict,
            dry_run=args.dry_run,
            summary=args.summary,
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
                    schema_path=schemas /"stems_index.schema.json",
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
            roles_path = ontology /"roles.yaml"
            try:
                stems_index_payload, stems_index_ref = _load_stems_index_for_classification(
                    repo_root=None,
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
                    schema_path=schemas /"stems_map.schema.json",
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

        if args.stems_command == "bus-plan":
            roles_path = ontology / "roles.yaml"
            try:
                stems_map_payload = _load_stems_map(
                    repo_root=None,
                    map_path=Path(args.map),
                )
                roles_payload = load_roles(roles_path)
                bus_plan_payload = build_bus_plan(stems_map_payload, roles_payload)
                source_payload = bus_plan_payload.get("source")
                if isinstance(source_payload, dict):
                    source_payload["stems_map_ref"] = _path_ref(args.map)
                    source_payload["roles_ref"] = "ontology/roles.yaml"
                _validate_json_payload(
                    bus_plan_payload,
                    schema_path=schemas / "bus_plan.schema.json",
                    payload_name="Bus plan",
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            _write_json_file(Path(args.out), bus_plan_payload)
            if isinstance(getattr(args, "csv", None), str) and args.csv.strip():
                _write_bus_plan_csv(Path(args.csv), bus_plan_payload)

            if args.format == "json":
                print(json.dumps(bus_plan_payload, indent=2, sort_keys=True))
            else:
                print(_render_bus_plan_text(bus_plan_payload))
            return 0

        if args.stems_command == "explain":
            roles_path = ontology /"roles.yaml"
            try:
                stems_index_payload, stems_index_ref = _load_stems_index_for_classification(
                    repo_root=None,
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
                    schema_path=schemas /"stems_map.schema.json",
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
                    repo_root=None,
                    map_path=Path(args.map),
                )
                overrides_payload = load_stems_overrides(Path(args.overrides))
                payload = apply_overrides(stems_map_payload, overrides_payload)
                _validate_json_payload(
                    payload,
                    schema_path=schemas /"stems_map.schema.json",
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
                    repo_root=None,
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

            roles_path = ontology /"roles.yaml"
            try:
                stems_index_payload = build_stems_index(
                    Path(args.root),
                    root_dir=args.root,
                )
                _validate_json_payload(
                    stems_index_payload,
                    schema_path=schemas /"stems_index.schema.json",
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
                    schema_path=schemas /"stems_map.schema.json",
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
                    repo_root=None,
                    map_path=Path(args.stems_map),
                )
                scene_payload = build_draft_scene(
                    stems_map_payload,
                    stems_dir=args.stems_dir,
                )
                routing_payload = build_draft_routing_plan(stems_map_payload)

                _validate_json_payload(
                    scene_payload,
                    schema_path=schemas /"scene.schema.json",
                    payload_name="Draft scene",
                )
                _validate_json_payload(
                    routing_payload,
                    schema_path=schemas /"routing_plan.schema.json",
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
                    repo_root=None,
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

        if args.stems_command == "roles":
            stems_dir_path = Path(args.stems)
            if not stems_dir_path.is_dir():
                print(f"Stems directory not found: {stems_dir_path}", file=sys.stderr)
                return 1
            roles_path = ontology / "roles.yaml"
            try:
                stems_index_payload, stems_index_ref = _load_stems_index_for_classification(
                    repo_root=None,
                    index_path=None,
                    root_path=str(stems_dir_path),
                )
                roles_payload = load_roles(roles_path)
                stems_map_payload, explanations = classify_stems_with_evidence(
                    stems_index_payload,
                    roles_payload,
                    role_lexicon=None,
                    use_common_role_lexicon=True,
                    stems_index_ref=stems_index_ref,
                    roles_ref="ontology/roles.yaml",
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            # Apply an existing role overrides YAML if provided
            overrides_path = getattr(args, "overrides", None)
            role_override_map: dict[str, str] = {}
            if isinstance(overrides_path, str) and overrides_path.strip():
                try:
                    import yaml as _yaml
                    with open(overrides_path, encoding="utf-8") as _f:
                        _ov = _yaml.safe_load(_f)
                    if isinstance(_ov, dict) and isinstance(_ov.get("role_overrides"), dict):
                        role_override_map = {
                            str(k).strip(): str(v).strip()
                            for k, v in _ov["role_overrides"].items()
                            if k and v
                        }
                except Exception as exc:
                    print(f"Failed to load role overrides: {exc}", file=sys.stderr)
                    return 1

            stem_entries = stems_map_payload.get("assignments", [])
            if not isinstance(stem_entries, list):
                stem_entries = []

            fmt = getattr(args, "format", "text")
            if fmt == "json":
                out_rows = []
                for entry in stem_entries:
                    stem_id = entry.get("stem_id", "")
                    inferred = entry.get("role_id", "ROLE.OTHER.UNKNOWN")
                    effective = role_override_map.get(stem_id, inferred)
                    out_rows.append({
                        "stem_id": stem_id,
                        "label": entry.get("label", entry.get("rel_path", "")),
                        "role_id": effective,
                        "inferred_role_id": inferred,
                        "overridden": stem_id in role_override_map,
                        "confidence": entry.get("confidence", 0.0),
                    })
                print(json.dumps(sorted(out_rows, key=lambda r: r["stem_id"]), indent=2, sort_keys=True))
            else:
                col_id = max((len(e.get("stem_id", "")) for e in stem_entries), default=8)
                col_role = 36
                header = f"{'STEM_ID':<{col_id}}  {'ROLE':<{col_role}}  CONF  NOTE"
                print(header)
                print("-" * len(header))
                for entry in sorted(stem_entries, key=lambda e: e.get("stem_id", "")):
                    stem_id = entry.get("stem_id", "")
                    inferred = entry.get("role_id", "ROLE.OTHER.UNKNOWN")
                    effective = role_override_map.get(stem_id, inferred)
                    conf = entry.get("confidence", 0.0)
                    note = " [overridden]" if stem_id in role_override_map else ""
                    print(f"{stem_id:<{col_id}}  {effective:<{col_role}}  {conf:.2f}{note}")

            write_overrides_path = getattr(args, "write_overrides", None)
            if isinstance(write_overrides_path, str) and write_overrides_path.strip():
                try:
                    import yaml as _yaml
                    rows: dict[str, str] = {}
                    for entry in sorted(stem_entries, key=lambda e: e.get("stem_id", "")):
                        stem_id = entry.get("stem_id", "")
                        effective = role_override_map.get(
                            stem_id, entry.get("role_id", "ROLE.OTHER.UNKNOWN")
                        )
                        if stem_id:
                            rows[stem_id] = effective
                    out_doc = {"role_overrides": rows}
                    Path(write_overrides_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(write_overrides_path, "w", encoding="utf-8") as _f:
                        _yaml.dump(out_doc, _f, default_flow_style=False, sort_keys=True, allow_unicode=True)
                    print(f"\nRole overrides template written to: {write_overrides_path}")
                except Exception as exc:
                    print(f"Failed to write role overrides: {exc}", file=sys.stderr)
                    return 1

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
            project_dir_arg = getattr(args, "project_dir", None)
            has_project_dir = (
                isinstance(project_dir_arg, str)
                and bool(project_dir_arg.strip())
            )
            if not has_project_dir:
                print(
                    (
                        "Missing project directory. Usage: "
                        "mmo project show <project_dir> "
                        "[--format json|json-shared|text]."
                    ),
                    file=sys.stderr,
                )
                return 1
            return _run_project_show(
                project_dir=Path(project_dir_arg),
                output_format=args.format,
            )

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
                repo_root=None,
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
                    schema_path=schemas /"stems_index.schema.json",
                    payload_name="Stems index",
                )
                _write_json_file(index_path, stems_index_payload)

                roles_path = ontology /"roles.yaml"
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
                    schema_path=schemas /"stems_map.schema.json",
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
                    schema_path=schemas /"scene.schema.json",
                    payload_name="Draft scene",
                )
                _validate_json_payload(
                    routing_payload,
                    schema_path=schemas /"routing_plan.schema.json",
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
                    schema_path=schemas /"stems_index.schema.json",
                    payload_name="Stems index",
                )
                _write_json_file(index_path, stems_index_payload)

                roles_path = ontology /"roles.yaml"
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
                    schema_path=schemas /"stems_map.schema.json",
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
                    schema_path=schemas /"scene.schema.json",
                    payload_name="Draft scene",
                )
                _validate_json_payload(
                    routing_payload,
                    schema_path=schemas /"routing_plan.schema.json",
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

        if args.project_command == "save":
            return _run_project_save(
                project_dir=Path(args.project_dir),
                session_path=(
                    Path(args.session)
                    if isinstance(getattr(args, "session", None), str)
                    and args.session.strip()
                    else None
                ),
                force=bool(getattr(args, "force", False)),
                output_format=str(getattr(args, "format", "json")),
            )

        if args.project_command == "load":
            return _run_project_load(
                project_dir=Path(args.project_dir),
                session_path=(
                    Path(args.session)
                    if isinstance(getattr(args, "session", None), str)
                    and args.session.strip()
                    else None
                ),
                force=bool(getattr(args, "force", False)),
                output_format=str(getattr(args, "format", "json")),
            )

        if args.project_command == "validate":
            return _run_project_validate(
                project_dir=Path(args.project_dir),
                out_path=Path(args.out) if args.out else None,
                repo_root=None,
                render_compat=bool(getattr(args, "render_compat", False)),
            )

        if args.project_command == "bundle":
            try:
                return _run_project_bundle(
                    project_dir=Path(args.project_dir),
                    out_path=Path(args.out),
                    force=bool(getattr(args, "force", False)),
                    include_plugins=bool(getattr(args, "include_plugins", False)),
                    include_plugin_layouts=bool(
                        getattr(args, "include_plugin_layouts", False)
                    ),
                    include_plugin_layout_snapshots=bool(
                        getattr(args, "include_plugin_layout_snapshots", False)
                    ),
                    include_plugin_ui_hints=bool(
                        getattr(args, "include_plugin_ui_hints", False)
                    ),
                    plugins_dir=(
                        Path(args.plugins)
                        if bool(getattr(args, "include_plugins", False))
                        else None
                    ),
                    render_preflight_path=(
                        Path(args.render_preflight)
                        if isinstance(getattr(args, "render_preflight", None), str)
                        and args.render_preflight.strip()
                        else None
                    ),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.project_command == "pack":
            return _run_project_pack(
                project_dir=Path(args.project_dir),
                out_path=Path(args.out),
                include_wavs=bool(getattr(args, "include_wavs", False)),
                force=bool(getattr(args, "force", False)),
            )

        if args.project_command == "build-gui":
            try:
                return _run_project_build_gui(
                    project_dir=Path(args.project_dir),
                    pack_out_path=Path(args.pack_out),
                    force=bool(getattr(args, "force", False)),
                    scan=bool(getattr(args, "scan", False)),
                    scan_stems_dir=(
                        Path(args.scan_stems)
                        if isinstance(getattr(args, "scan_stems", None), str)
                        and args.scan_stems.strip()
                        else None
                    ),
                    scan_out_path=(
                        Path(args.scan_out)
                        if isinstance(getattr(args, "scan_out", None), str)
                        and args.scan_out.strip()
                        else None
                    ),
                    event_log=bool(getattr(args, "event_log", False)),
                    event_log_force=bool(getattr(args, "event_log_force", False)),
                    include_plugins=bool(getattr(args, "include_plugins", False)),
                    include_plugin_layouts=bool(
                        getattr(args, "include_plugin_layouts", False)
                    ),
                    include_plugin_layout_snapshots=bool(
                        getattr(args, "include_plugin_layout_snapshots", False)
                    ),
                    include_plugin_ui_hints=bool(
                        getattr(args, "include_plugin_ui_hints", False)
                    ),
                    plugins_dir=(
                        Path(args.plugins)
                        if bool(getattr(args, "include_plugins", False))
                        else None
                    ),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.project_command == "render-init":
            has_single = args.target_layout is not None
            has_multi = args.target_layouts is not None
            if has_single == has_multi:
                print(
                    "Specify exactly one of --target-layout or --target-layouts.",
                    file=sys.stderr,
                )
                return 1
            return _run_project_render_init(
                project_dir=Path(args.project_dir),
                target_layout=args.target_layout,
                target_layouts=args.target_layouts,
                target_ids=args.target_ids,
                force=bool(getattr(args, "force", False)),
            )

        if args.project_command == "write-render-request":
            try:
                return _run_project_write_render_request(
                    project_dir=Path(args.project_dir),
                    set_entries=list(getattr(args, "set_entries", [])),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.project_command == "render-run":
            try:
                return _run_project_render_run(
                    project_dir=Path(args.project_dir),
                    force=bool(getattr(args, "force", False)),
                    event_log=bool(getattr(args, "event_log", False)),
                    preflight=bool(getattr(args, "preflight", False)),
                    preflight_force=bool(getattr(args, "preflight_force", False)),
                    event_log_force=bool(getattr(args, "event_log_force", False)),
                    execute=bool(getattr(args, "execute", False)),
                    execute_out_path=(
                        Path(args.execute_out)
                        if isinstance(getattr(args, "execute_out", None), str)
                        and args.execute_out.strip()
                        else None
                    ),
                    execute_force=bool(getattr(args, "execute_force", False)),
                    qa=bool(getattr(args, "qa", False)),
                    qa_out_path=(
                        Path(args.qa_out)
                        if isinstance(getattr(args, "qa_out", None), str)
                        and args.qa_out.strip()
                        else None
                    ),
                    qa_force=bool(getattr(args, "qa_force", False)),
                    qa_enforce=bool(getattr(args, "qa_enforce", False)),
                    recall_sheet=bool(getattr(args, "recall_sheet", False)),
                    recall_sheet_force=bool(getattr(args, "recall_sheet_force", False)),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        print("Unknown project command.", file=sys.stderr)
        return 2
    if args.command == "ui":
        return _run_ui_workflow(
            repo_root=None,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=Path(args.stems),
            out_dir=Path(args.out),
            project_path=Path(args.project) if args.project else None,
            nerd=args.nerd,
        )
    if args.command == "run":
        exit_code, _ = _run_workflow_from_run_args(
            repo_root=None,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=Path(args.stems),
            out_dir=Path(args.out),
            args=args,
        )
        return exit_code
    if args.command == "watch":
        try:
            target_ids = parse_watch_targets_csv(args.targets)
            watch_config = WatchFolderConfig(
                watch_dir=Path(args.folder),
                out_dir=Path(args.out) if args.out else None,
                target_ids=target_ids,
                profile_id=args.profile,
                settle_seconds=float(args.settle_seconds),
                poll_interval_seconds=float(args.poll_interval),
                include_existing=not bool(args.no_existing),
                once=bool(args.once),
            )
            queue_listener: Callable[[WatchQueueSnapshot], None] | None = None
            if bool(args.visual_queue):
                queue_listener = (
                    lambda snapshot: print(
                        render_watch_queue_snapshot(
                            snapshot,
                            cinematic=bool(args.cinematic_progress),
                        )
                    )
                )
            return run_watch_folder(
                watch_config,
                queue_listener=queue_listener,
            )
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
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
        report_schema_path = schemas /"report.schema.json"
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
    if args.command == "report":
        try:
            report_payload = _load_report(Path(args.report))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        try:
            _validate_json_payload(
                report_payload,
                schema_path=schemas / "report.schema.json",
                payload_name="Report",
            )
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        if args.out_json:
            _write_json_file(Path(args.out_json), report_payload)
        if args.out_recall:
            from mmo.exporters.recall_sheet import export_recall_sheet  # noqa: WPS433

            export_recall_sheet(report_payload, Path(args.out_recall))
        if args.out_pdf:
            from mmo.exporters.pdf_report import export_report_pdf  # noqa: WPS433

            try:
                export_report_pdf(
                    report_payload,
                    Path(args.out_pdf),
                    include_measurements=not args.no_measurements,
                    include_gates=not args.no_gates,
                    truncate_values=args.truncate_values,
                )
            except RuntimeError:
                print(
                    "PDF export requires reportlab. Install extras: pip install .[pdf]",
                    file=sys.stderr,
                )
                return 2
        return 0
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
                schema_path=schemas /"compare_report.schema.json",
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
    if args.command == "review":
        try:
            report_payload, _ = load_report_from_path_or_dir(Path(args.report))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        recs = report_payload.get("recommendations")
        if not isinstance(recs, list):
            print("report has no recommendations list", file=sys.stderr)
            return 1
        pending = [
            r for r in recs
            if isinstance(r, dict) and r.get("requires_approval") is True
        ]
        if args.risk:
            pending = [r for r in pending if r.get("risk") == args.risk]
        if args.format == "json":
            print(json.dumps(
                {"pending_approvals": pending, "count": len(pending)},
                indent=2,
                sort_keys=True,
            ))
            return 0
        print(_render_review_text(pending, report_path=args.report))
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
                repo_root=None,
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
    if args.command == "safe-render":
        if not getattr(args, "demo", False) and not getattr(args, "report", None):
            print(
                "safe-render: --report is required unless --demo is used.",
                file=sys.stderr,
            )
            return 1
        safe_render_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--output-formats"):
            try:
                safe_render_formats = _parse_output_formats_csv(args.output_formats)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _set_nested(
                ["render", "output_formats"],
                safe_render_overrides,
                safe_render_formats,
            )
        _safe_render_layout_standard = (
            str(getattr(args, "layout_standard", "SMPTE")).strip().upper() or "SMPTE"
        )
        _all_layout_standards = ("SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF")
        if _safe_render_layout_standard not in _all_layout_standards:
            _safe_render_layout_standard = "SMPTE"
        if _flag_present(raw_argv, "--layout-standard"):
            _set_nested(
                ["render", "layout_standard"],
                safe_render_overrides,
                _safe_render_layout_standard,
            )
        try:
            merged_run_config = _load_and_merge_run_config(
                args.config,
                safe_render_overrides,
                preset_id=args.preset,
                presets_dir=presets_dir,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        safe_render_formats = _config_nested_output_formats(
            merged_run_config,
            "render",
            ["wav"],
        )
        _demo_flag = bool(getattr(args, "demo", False))
        if _demo_flag:
            from mmo.cli_commands._renderers import (  # noqa: WPS433
                _run_safe_render_demo,
            )
            # Locate fixture relative to the repo root (or CWD for installed)
            _demo_fixture = Path("fixtures/immersive/report.7_1_4.json")
            if not _demo_fixture.exists():
                # Fall back to path relative to this file (installed package)
                _demo_fixture = (
                    Path(__file__).resolve().parent.parent.parent
                    / "fixtures" / "immersive" / "report.7_1_4.json"
                )
            try:
                return _run_safe_render_demo(
                    fixture_path=_demo_fixture,
                    plugins_dir=Path(getattr(args, "plugins", "plugins")),
                    out_dir=(
                        Path(args.out_dir) if getattr(args, "out_dir", None) else None
                    ),
                    profile_id=getattr(args, "profile", "PROFILE.ASSIST"),
                    run_config=merged_run_config,
                    force=bool(getattr(args, "force", False)),
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        _render_many_flag = bool(getattr(args, "render_many", False))
        _render_many_targets_raw = getattr(args, "render_many_targets", None)
        _render_many_targets: list[str] | None = None
        if _render_many_flag:
            if _render_many_targets_raw:
                _render_many_targets = [
                    t.strip()
                    for t in _render_many_targets_raw.split(",")
                    if t.strip()
                ]
            else:
                from mmo.cli_commands._renderers import (  # noqa: WPS433
                    _RENDER_MANY_DEFAULT_TARGETS,
                )
                _render_many_targets = list(_RENDER_MANY_DEFAULT_TARGETS)
        _export_layouts_raw = getattr(args, "export_layouts", None)
        _export_layouts: list[str] | None = None
        if isinstance(_export_layouts_raw, str) and _export_layouts_raw.strip():
            _export_layouts = [
                token.strip()
                for token in _export_layouts_raw.split(",")
                if token.strip()
            ]
        try:
            return _run_safe_render_command(
                repo_root=None,
                report_path=Path(args.report),
                plugins_dir=Path(args.plugins),
                out_dir=Path(args.out_dir) if getattr(args, "out_dir", None) else None,
                out_manifest_path=(
                    Path(args.out_manifest)
                    if getattr(args, "out_manifest", None)
                    else None
                ),
                receipt_out_path=(
                    Path(args.receipt_out)
                    if getattr(args, "receipt_out", None)
                    else None
                ),
                qa_out_path=(
                    Path(args.qa_out)
                    if getattr(args, "qa_out", None)
                    else None
                ),
                profile_id=getattr(args, "profile", "PROFILE.ASSIST"),
                target=getattr(args, "target", "stereo"),
                dry_run=bool(getattr(args, "dry_run", False)),
                approve=getattr(args, "approve", None),
                approve_rec_ids=getattr(args, "approve_rec_ids", None),
                approve_file=(
                    Path(args.approve_file)
                    if getattr(args, "approve_file", None)
                    else None
                ),
                output_formats=safe_render_formats,
                run_config=merged_run_config,
                force=bool(getattr(args, "force", False)),
                user_profile=_resolve_user_profile_arg(
                    getattr(args, "user_profile_id", None),
                    ontology / "profiles.yaml",
                ),
                render_many_targets=_render_many_targets,
                layout_standard=_safe_render_layout_standard,
                preview_headphones=bool(getattr(args, "preview_headphones", False)),
                allow_empty_outputs=bool(getattr(args, "allow_empty_outputs", False)),
                export_stems=bool(getattr(args, "export_stems", False)),
                export_buses=bool(getattr(args, "export_buses", False)),
                export_master=bool(getattr(args, "export_master", True)),
                export_layouts=_export_layouts,
                live_progress=bool(getattr(args, "live_progress", False)),
                cancel_file=(
                    Path(args.cancel_file)
                    if getattr(args, "cancel_file", None)
                    else None
                ),
                scene_path=(
                    Path(args.scene)
                    if getattr(args, "scene", None)
                    else None
                ),
                scene_locks_path=(
                    Path(args.scene_locks)
                    if getattr(args, "scene_locks", None)
                    else None
                ),
                scene_strict=bool(getattr(args, "scene_strict", False)),
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
                repo_root=None,
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
                repo_root=None,
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
                include_plugins=bool(getattr(args, "include_plugins", False)),
                include_plugin_layouts=bool(
                    getattr(args, "include_plugin_layouts", False)
                ),
                include_plugin_layout_snapshots=bool(
                    getattr(args, "include_plugin_layout_snapshots", False)
                ),
                include_plugin_ui_hints=bool(
                    getattr(args, "include_plugin_ui_hints", False)
                ),
                plugins_dir=(
                    Path(args.plugins)
                    if bool(getattr(args, "include_plugins", False))
                    else None
                ),
                render_request_path=(
                    Path(args.render_request) if getattr(args, "render_request", None) else None
                ),
                render_execute_path=(
                    Path(args.render_execute)
                    if getattr(args, "render_execute", None)
                    else None
                ),
                render_report_path=(
                    Path(args.render_report) if getattr(args, "render_report", None) else None
                ),
                event_log_path=(
                    Path(args.event_log) if getattr(args, "event_log", None) else None
                ),
                render_preflight_path=(
                    Path(args.render_preflight)
                    if getattr(args, "render_preflight", None)
                    else None
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
            repo_root=None,
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
                repo_root=None,
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
            repo_root=None,
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
    if args.command == "plugin":
        if args.plugin_command == "list":
            try:
                payload = _build_plugin_market_list_payload(
                    plugins_dir=Path(args.plugins),
                    plugin_dir=(
                        Path(args.plugin_dir)
                        if isinstance(args.plugin_dir, str) and args.plugin_dir.strip()
                        else None
                    ),
                    index_path=(
                        Path(args.index)
                        if isinstance(args.index, str) and args.index.strip()
                        else None
                    ),
                )
            except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_plugin_market_list_text(payload))
            return 0

        if args.plugin_command == "update":
            try:
                payload = _build_plugin_market_update_payload(
                    out_path=(
                        Path(args.out)
                        if isinstance(args.out, str) and args.out.strip()
                        else None
                    ),
                    index_path=(
                        Path(args.index)
                        if isinstance(args.index, str) and args.index.strip()
                        else None
                    ),
                )
            except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_plugin_market_update_text(payload))
            return 0

        if args.plugin_command == "install":
            try:
                payload = _build_plugin_market_install_payload(
                    plugin_id=args.plugin_id,
                    plugins_dir=(
                        Path(args.plugins)
                        if isinstance(args.plugins, str) and args.plugins.strip()
                        else None
                    ),
                    index_path=(
                        Path(args.index)
                        if isinstance(args.index, str) and args.index.strip()
                        else None
                    ),
                )
            except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_plugin_market_install_text(payload))
            return 0

        print("Unknown plugin command.", file=sys.stderr)
        return 2
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

        if args.plugins_command == "validate":
            try:
                payload = _build_plugins_validate_payload(
                    plugins_dir=(
                        None
                        if bool(getattr(args, "bundled_only", False))
                        else Path(args.plugins)
                    ),
                    bundled_only=bool(getattr(args, "bundled_only", False)),
                )
            except (RuntimeError, ValueError, AttributeError, ImportError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_plugins_validate_text(payload))
            return 2 if _plugins_validate_has_errors(payload) else 0

        if args.plugins_command == "ui-lint":
            try:
                payload = _build_plugins_ui_lint_payload(plugins_dir=Path(args.plugins))
            except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_plugins_ui_lint_text(payload))
            return 2 if _plugins_ui_lint_has_errors(payload) else 0

        if args.plugins_command == "show":
            try:
                payload = _build_plugins_show_payload(
                    plugins_dir=Path(args.plugins),
                    plugin_id=args.plugin_id,
                    include_ui_layout_snapshot=bool(
                        getattr(args, "include_ui_layout_snapshot", False)
                    ),
                    include_ui_hints=bool(getattr(args, "include_ui_hints", False)),
                )
            except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_plugins_show_text(payload))
            return 0

        if args.plugins_command == "self-test":
            try:
                payload = _build_plugins_self_test_payload(
                    plugin_id=args.plugin_id,
                    out_dir=Path(args.out_dir),
                    force=bool(args.force),
                )
            except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            print(json.dumps(payload, indent=2, sort_keys=True))
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
                    repo_root=None,
                    presets_dir=presets_dir,
                    preset_id=args.preset_id,
                    config_path=args.config,
                    report_path=args.report,
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
        help_registry_path = ontology /"help.yaml"
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
        render_targets_path = ontology /"render_targets.yaml"
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
                            f"  {item.get('layout_id', '')}"
                            f"  {item.get('container', '')}"
                        )
                else:
                    for index, item in enumerate(payload):
                        if index > 0:
                            print("")
                        print(
                            f"{item.get('target_id', '')}"
                            f"  {item.get('layout_id', '')}"
                            f"  {item.get('container', '')}"
                        )
                        channel_order_layout_id = item.get("channel_order_layout_id")
                        if (
                            isinstance(channel_order_layout_id, str)
                            and channel_order_layout_id.strip()
                        ):
                            print(f"channel_order_layout_id: {channel_order_layout_id}")
                        channel_order = item.get("channel_order")
                        normalized_channel_order = (
                            [
                                channel
                                for channel in channel_order
                                if isinstance(channel, str) and channel.strip()
                            ]
                            if isinstance(channel_order, list)
                            else []
                        )
                        if normalized_channel_order:
                            print(f"channel_order: {', '.join(normalized_channel_order)}")
                        filename_template = item.get("filename_template")
                        if isinstance(filename_template, str) and filename_template.strip():
                            print(f"filename_template: {filename_template}")
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
                    repo_root=None,
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

    if args.command == "ontology":
        from mmo.core.ontology_validator import validate_ontology  # noqa: WPS433

        if args.ontology_command == "validate":
            result = validate_ontology(ontology)
            if args.format == "json":
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                ok_label = "OK" if result.get("ok") else "FAIL"
                print(
                    f"ontology validate: {ok_label}"
                    f" | version={result.get('ontology_version', '')}"
                    f" | categories={result.get('categories_checked', 0)}"
                    f" | entries={result.get('entries_checked', 0)}"
                    f" | errors={result.get('error_count', 0)}"
                    f" | warnings={result.get('warn_count', 0)}"
                )
                for iss in result.get("issues", []):
                    severity = iss.get("severity", "")
                    category = iss.get("category", "")
                    file_label = iss.get("file", "")
                    entry_id = iss.get("entry_id") or "-"
                    message = iss.get("message", "")
                    print(
                        f"  [{severity.upper()}] {category} / {file_label}"
                        f" ({entry_id}): {message}"
                    )
            if not result.get("ok"):
                return 1
            return 0
        print(f"Unknown ontology command: {args.ontology_command}", file=sys.stderr)
        return 2

    if args.command == "roles":
        roles_path = ontology /"roles.yaml"
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
        translation_profiles_path = ontology /"translation_profiles.yaml"
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
                        repo_root=None,
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
    if args.command == "profile":
        from mmo.core.profiles import apply_to_gates, get_profile, list_profiles
        profiles_path = ontology / "profiles.yaml"
        if args.profile_command == "list":
            try:
                rows = list_profiles(profiles_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(rows, indent=2, sort_keys=True))
            else:
                for row in rows:
                    intents = ", ".join(row.get("style_intent") or [])
                    print(
                        f"{row.get('profile_id', '')}"
                        f"  {row.get('label', '')}"
                        f"  [{intents}]"
                    )
            return 0
        if args.profile_command == "show":
            try:
                payload = get_profile(args.profile_id, profiles_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"Profile ID : {payload.get('profile_id', '')}")
                print(f"Label      : {payload.get('label', '')}")
                print(f"Description: {str(payload.get('description', '')).strip()}")
                intents = ", ".join(payload.get("style_intent") or [])
                print(f"Style      : {intents}")
                overrides = payload.get("gate_overrides") or {}
                if overrides:
                    print("Gate overrides:")
                    for k, v in sorted(overrides.items()):
                        print(f"  {k}: {v}")
                bounds = payload.get("param_bounds") or {}
                if bounds:
                    print("Param bounds:")
                    for param, bound in sorted(bounds.items()):
                        if isinstance(bound, dict):
                            print(f"  {param}: min={bound.get('min')} max={bound.get('max')} {bound.get('unit_id', '')}")
                notes = payload.get("safety_notes") or []
                if notes:
                    print("Safety notes:")
                    for note in notes:
                        print(f"  - {note}")
            return 0
        if args.profile_command == "apply":
            try:
                profile = get_profile(args.profile_id, profiles_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            gate_options = apply_to_gates(profile, {})
            scene_issues: list[dict] = []
            if isinstance(getattr(args, "scene", None), str) and args.scene.strip():
                scene_path = Path(args.scene.strip())
                try:
                    scene_data = _load_json_object(scene_path, label="Scene")
                except (OSError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                from mmo.core.profiles import validate_against_scene
                scene_issues = validate_against_scene(profile, scene_data)
            result: dict[str, Any] = {
                "profile_id": profile.get("profile_id", ""),
                "label": profile.get("label", ""),
                "gate_options": gate_options,
                "param_bounds": profile.get("param_bounds", {}),
                "scene_issues": scene_issues,
            }
            if args.format == "json":
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Profile: {result['profile_id']}  ({result['label']})")
                print("Gate options applied:")
                for k, v in sorted(result["gate_options"].items()):
                    print(f"  {k}: {v}")
                if scene_issues:
                    print("Scene compatibility issues:")
                    for iss in scene_issues:
                        print(f"  [{iss.get('severity','?')}] {iss.get('code','')}: {iss.get('message','')}")
                else:
                    print("Scene compatibility: OK")
            return 0
        print("Unknown profile command.", file=sys.stderr)
        return 2
    if args.command == "locks":
        scene_locks_path = ontology /"scene_locks.yaml"
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
    if args.command == "ui-hints":
        from mmo.core.ui_hints import (  # noqa: WPS433
            build_ui_hints_extract_payload,
            build_ui_hints_lint_payload,
            ui_hints_has_errors,
        )

        schema_path = Path(_normalize_cli_path_arg(args.schema))
        try:
            config_schema = _load_json_object(schema_path, label="Config schema")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.ui_hints_command == "lint":
            try:
                lint_payload = build_ui_hints_lint_payload(
                    config_schema=config_schema,
                    schema_path=schema_path,
                )
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(lint_payload, indent=2, sort_keys=True))
            else:
                hint_count = lint_payload.get("hint_count", 0)
                error_count = lint_payload.get("error_count", 0)
                if lint_payload.get("ok"):
                    print(f"UI hints lint OK ({hint_count} hint(s) checked).")
                else:
                    print(
                        "UI hints lint failed "
                        f"({error_count} error(s) across {hint_count} hint(s))."
                    )
                    for error in lint_payload.get("errors", []):
                        if not isinstance(error, dict):
                            continue
                        pointer = error.get("json_pointer", "")
                        path = error.get("path", "")
                        message = error.get("message", "")
                        if path == "/":
                            print(f"- {pointer}: {message}")
                        else:
                            print(f"- {pointer}{path}: {message}")
            return 2 if ui_hints_has_errors(lint_payload) else 0

        if args.ui_hints_command == "extract":
            out_path = Path(args.out)
            if out_path.exists() and not args.force:
                print(
                    f"File exists (use --force to overwrite): {out_path.as_posix()}",
                    file=sys.stderr,
                )
                return 1
            extract_payload = build_ui_hints_extract_payload(
                config_schema=config_schema,
                schema_path=schema_path,
            )
            _write_json_file(out_path, extract_payload)
            return 0

        print("Unknown ui-hints command.", file=sys.stderr)
        return 2
    if args.command == "ui-copy":
        ui_copy_registry_path = ontology /"ui_copy.yaml"
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
        ui_examples_dir = (_checkout_root / "examples" / "ui_screens") if _checkout_root is not None else Path("examples") / "ui_screens"
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

        schema_path = schemas /"lockfile.schema.json"
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
                has_report = isinstance(args.report, str) and bool(args.report.strip())
                has_map = isinstance(args.map, str) and bool(args.map.strip())
                has_bus = isinstance(args.bus, str) and bool(args.bus.strip())

                if has_report and (has_map or has_bus):
                    raise ValueError(
                        "scene build accepts either --report or --map/--bus inputs, not both.",
                    )

                if has_report:
                    template_ids: list[str] = []
                    if isinstance(args.templates, str) and args.templates.strip():
                        template_ids = _parse_scene_template_ids_csv(args.templates)
                    return _run_scene_build_command(
                        repo_root=None,
                        report_path=Path(args.report),
                        out_path=Path(args.out),
                        timeline_path=Path(args.timeline) if args.timeline else None,
                        template_ids=template_ids,
                        force_templates=bool(args.force_templates),
                        locks_path=Path(args.locks) if args.locks else None,
                    )

                if has_map or has_bus:
                    if not (has_map and has_bus):
                        raise ValueError(
                            "scene build from stems artifacts requires both --map and --bus.",
                        )
                    if isinstance(args.timeline, str) and args.timeline.strip():
                        raise ValueError("--timeline is only supported with --report.")
                    if isinstance(args.templates, str) and args.templates.strip():
                        raise ValueError("--templates is only supported with --report.")
                    if bool(args.force_templates):
                        raise ValueError("--force-templates is only supported with --report.")
                    return _run_scene_build_from_bus_plan_command(
                        repo_root=None,
                        stems_map_path=Path(args.map),
                        bus_plan_path=Path(args.bus),
                        out_path=Path(args.out),
                        profile_id=args.profile,
                        locks_path=Path(args.locks) if args.locks else None,
                    )

                raise ValueError(
                    "scene build requires either --report or --map with --bus.",
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.scene_command == "lint":
            try:
                return _run_scene_lint_command(
                    repo_root=None,
                    scene_path=Path(args.scene),
                    locks_path=Path(args.scene_locks) if args.scene_locks else None,
                    out_path=Path(args.out) if args.out else None,
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.scene_command == "locks":
            try:
                return _run_scene_locks_edit_command(
                    repo_root=None,
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
                        repo_root=None,
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
                    _validate_scene_schema(repo_root=None, scene_payload=scene_payload)
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
            scene_templates_path = ontology /"scene_templates.yaml"
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
                        repo_root=None,
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
                        repo_root=None,
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
                _validate_scene_schema(repo_root=None, scene_payload=scene_payload)
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
                    render_targets_path=ontology /"render_targets.yaml",
                )
                output_formats = _parse_output_formats_csv(args.output_formats)
                contexts = (
                    list(args.context)
                    if isinstance(args.context, list) and args.context
                    else ["render"]
                )
                return _run_render_plan_build_command(
                    repo_root=None,
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
                    repo_root=None,
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
                    repo_root=None,
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
                schema_path=schemas /"render_plan.schema.json",
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
    if args.command == "render-request":
        if args.render_request_command == "template":
            out_path = Path(args.out)
            if out_path.exists() and not args.force:
                print(
                    f"File exists (use --force to overwrite): {out_path.as_posix()}",
                    file=sys.stderr,
                )
                return 1
            has_single = args.target_layout is not None
            has_multi = args.target_layouts is not None
            if has_single == has_multi:
                print(
                    "Specify exactly one of --target-layout or --target-layouts.",
                    file=sys.stderr,
                )
                return 1
            try:
                if has_multi:
                    from mmo.core.render_request_template import (  # noqa: WPS433
                        build_multi_render_request_template,
                    )

                    raw_ids = [
                        tid.strip()
                        for tid in args.target_layouts.split(",")
                        if tid.strip()
                    ]
                    payload = build_multi_render_request_template(
                        raw_ids,
                        scene_path=args.scene,
                        routing_plan_path=args.routing_plan,
                    )
                else:
                    from mmo.core.render_request_template import (  # noqa: WPS433
                        build_render_request_template,
                    )

                    payload = build_render_request_template(
                        args.target_layout,
                        scene_path=args.scene,
                        routing_plan_path=args.routing_plan,
                    )
                _validate_json_payload(
                    payload,
                    schema_path=schemas / "render_request.schema.json",
                    payload_name="Render request template",
                )
                _write_json_file(out_path, payload)
                return 0
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
        print("Unknown render-request command.", file=sys.stderr)
        return 2
    if args.command == "render-preflight":
        out_path = Path(args.out)
        if out_path.exists() and not args.force:
            print(
                f"File exists (use --force to overwrite): {out_path.as_posix()}",
                file=sys.stderr,
            )
            return 1
        try:
            plan_path = Path(args.plan)
            plan_payload = _load_json_object(
                plan_path,
                label="Render plan",
            )
            _validate_json_payload(
                plan_payload,
                schema_path=schemas / "render_plan.schema.json",
                payload_name="Render plan",
            )

            from mmo.core.render_preflight import (  # noqa: WPS433
                build_render_preflight_payload,
                preflight_has_error_issues,
            )

            preflight_payload = build_render_preflight_payload(
                plan_payload,
                plan_path=plan_path,
            )
            _validate_json_payload(
                preflight_payload,
                schema_path=schemas / "render_preflight.schema.json",
                payload_name="Render preflight",
            )
            _write_json_file(out_path, preflight_payload)
            return 2 if preflight_has_error_issues(preflight_payload) else 0
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
    if args.command == "ui-layout-snapshot":
        out_path = Path(args.out)
        if out_path.exists() and not args.force:
            print(
                f"File exists (use --force to overwrite): {out_path.as_posix()}",
                file=sys.stderr,
            )
            return 1
        try:
            layout_path = Path(args.layout)
            layout_payload = _load_json_object(layout_path, label="UI layout")
            _validate_json_payload(
                layout_payload,
                schema_path=schemas / "ui_layout.schema.json",
                payload_name="UI layout",
            )
            from mmo.core.ui_layout import (  # noqa: WPS433
                build_ui_layout_snapshot,
                parse_viewport_spec,
                snapshot_has_violations,
            )

            viewport_width_px, viewport_height_px = parse_viewport_spec(args.viewport)
            snapshot_payload = build_ui_layout_snapshot(
                layout_payload,
                layout_path=layout_path,
                viewport_width_px=viewport_width_px,
                viewport_height_px=viewport_height_px,
                scale=float(args.scale),
            )
            _validate_json_payload(
                snapshot_payload,
                schema_path=schemas / "ui_layout_snapshot.schema.json",
                payload_name="UI layout snapshot",
            )
            _write_json_file(out_path, snapshot_payload)
            return 2 if snapshot_has_violations(snapshot_payload) else 0
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
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
                schema_path=schemas /"render_plan.schema.json",
                payload_name="Render plan",
            )
            from mmo.core.render_reporting import build_render_report_from_plan  # noqa: WPS433

            report_payload = build_render_report_from_plan(plan_payload)
            _validate_json_payload(
                report_payload,
                schema_path=schemas /"render_report.schema.json",
                payload_name="Render report",
            )
            _write_json_file(out_path, report_payload)
            return 0
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
    if args.command == "render-compat":
        out_path = Path(args.out) if getattr(args, "out", None) else None
        if out_path is not None and out_path.exists() and not args.force:
            print(
                f"File exists (use --force to overwrite): {out_path.as_posix()}",
                file=sys.stderr,
            )
            return 1
        try:
            request_payload = _load_json_object(
                Path(args.request),
                label="Render request",
            )
            _validate_json_payload(
                request_payload,
                schema_path=schemas /"render_request.schema.json",
                payload_name="Render request",
            )

            plan_payload = _load_json_object(
                Path(args.plan),
                label="Render plan",
            )
            _validate_json_payload(
                plan_payload,
                schema_path=schemas /"render_plan.schema.json",
                payload_name="Render plan",
            )

            report_payload: dict[str, Any] | None = None
            if args.report:
                report_payload = _load_json_object(
                    Path(args.report),
                    label="Render report",
                )
                _validate_json_payload(
                    report_payload,
                    schema_path=schemas /"render_report.schema.json",
                    payload_name="Render report",
                )

            from mmo.core.render_compat import (  # noqa: WPS433
                validate_plan_report_compat,
                validate_request_plan_compat,
            )

            issues = validate_request_plan_compat(request_payload, plan_payload)
            if report_payload is not None:
                issues.extend(validate_plan_report_compat(plan_payload, report_payload))
            issues.sort(
                key=lambda item: (
                    _coerce_str(item.get("severity")).strip(),
                    _coerce_str(item.get("issue_id")).strip(),
                    _coerce_str(item.get("message")).strip(),
                )
            )

            payload = {"issues": issues}
            if out_path is None:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                _write_json_file(out_path, payload)

            has_errors = any(
                _coerce_str(item.get("severity")).strip() == "error"
                for item in issues
                if isinstance(item, dict)
            )
            return 2 if has_errors else 0
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
    if args.command == "render-run":
        try:
            return _run_render_run_command(
                repo_root=None,
                request_path=Path(args.request),
                scene_path=Path(args.scene),
                routing_plan_path=(
                    Path(args.routing_plan) if args.routing_plan else None
                ),
                plan_out_path=Path(args.plan_out),
                report_out_path=Path(args.report_out),
                force=bool(getattr(args, "force", False)),
                event_log_out_path=(
                    Path(args.event_log_out)
                    if getattr(args, "event_log_out", None)
                    else None
                ),
                event_log_force=bool(getattr(args, "event_log_force", False)),
                preflight_out_path=(
                    Path(args.preflight_out)
                    if getattr(args, "preflight_out", None)
                    else None
                ),
                preflight_force=bool(getattr(args, "preflight_force", False)),
                execute_out_path=(
                    Path(args.execute_out)
                    if getattr(args, "execute_out", None)
                    else None
                ),
                execute_force=bool(getattr(args, "execute_force", False)),
                qa_out_path=(
                    Path(args.qa_out)
                    if getattr(args, "qa_out", None)
                    else None
                ),
                qa_force=bool(getattr(args, "qa_force", False)),
                qa_enforce=bool(getattr(args, "qa_enforce", False)),
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
    if args.command == "env":
        if args.env_command != "doctor":
            print("Unknown env command.", file=sys.stderr)
            return 2
        try:
            payload = build_env_doctor_report()
        except (RuntimeError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.format == "json":
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(render_env_doctor_text(payload), end="")
        return 0
    if args.command == "gui":
        if args.gui_command != "rpc":
            print("Unknown gui command.", file=sys.stderr)
            return 2
        return _run_gui_rpc()
    if args.command == "event-log":
        if args.event_log_command == "validate":
            out_path = Path(args.out) if getattr(args, "out", None) else None
            if out_path is not None and out_path.exists() and not args.force:
                print(
                    f"File exists (use --force to overwrite): {out_path.as_posix()}",
                    file=sys.stderr,
                )
                return 1

            try:
                result = validate_event_log_jsonl(Path(args.in_path))
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            raw_issues = result.get("issues")
            normalized_issues: list[dict[str, Any]] = []
            if isinstance(raw_issues, list):
                for raw_issue in raw_issues:
                    if not isinstance(raw_issue, dict):
                        continue
                    line = raw_issue.get("line")
                    issue_id = raw_issue.get("issue_id")
                    message = raw_issue.get("message")
                    if not isinstance(line, int):
                        continue
                    if not isinstance(issue_id, str):
                        continue
                    if not isinstance(message, str):
                        continue
                    normalized_issues.append(
                        {
                            "line": line,
                            "issue_id": issue_id.strip(),
                            "message": message.strip(),
                        }
                    )
            normalized_issues.sort(
                key=lambda issue: (
                    issue["line"],
                    issue["issue_id"],
                    issue["message"],
                )
            )
            result["issues"] = normalized_issues

            output_text = json.dumps(result, indent=2, sort_keys=True) + "\n"
            sys.stdout.write(output_text)

            if out_path is not None:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(output_text, encoding="utf-8")

            return 0 if not normalized_issues else 2

        if args.event_log_command != "demo":
            print("Unknown event-log command.", file=sys.stderr)
            return 2

        demo_events: list[dict[str, Any]] = [
            {
                "kind": "info",
                "scope": "stems",
                "what": "Indexed stem inputs",
                "why": "Prepared deterministic source map for routing.",
                "where": ["stems/stems_index.json", "STEMSET.DEMO.A"],
                "evidence": {
                    "codes": ["STEMS.INDEXED"],
                    "ids": ["STEMSET.DEMO.A"],
                    "paths": ["stems/stems_index.json"],
                    "metrics": [{"name": "stem_count", "value": 4}],
                    "notes": ["Indexed by rel_path sort."],
                },
            },
            {
                "kind": "action",
                "scope": "render",
                "what": "Planned stereo dry-run",
                "why": "Validated render graph without writing audio.",
                "where": ["render/render_plan.json", "TARGET.STEREO.2_0"],
                "confidence": 0.99,
                "evidence": {
                    "codes": ["RENDER.PLAN.CREATED"],
                    "ids": ["TARGET.STEREO.2_0"],
                    "paths": ["render/render_plan.json"],
                    "metrics": [{"name": "job_count", "value": 1}],
                    "notes": ["No wall-clock timestamps were captured."],
                },
            },
            {
                "kind": "warn",
                "scope": "qa",
                "what": "Translation checks skipped",
                "why": "Reference audio was not provided.",
                "where": ["qa/translation_summary.json", "TRANS.MONO.COLLAPSE"],
                "confidence": 0.67,
                "evidence": {
                    "codes": ["QA.TRANSLATION.SKIPPED"],
                    "ids": ["TRANS.MONO.COLLAPSE"],
                    "paths": ["qa/translation_summary.json"],
                    "metrics": [{"name": "profiles_checked", "value": 0}],
                    "notes": ["Demo fixture intentionally omits reference audio."],
                },
            },
        ]

        events_with_ids: list[dict[str, Any]] = []
        for event in demo_events:
            event_payload = dict(event)
            event_payload["event_id"] = new_event_id(event_payload)
            events_with_ids.append(event_payload)

        try:
            out_path = Path(args.out)
            write_event_log(events_with_ids, out_path, force=bool(args.force))
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

        print(
            json.dumps(
                {
                    "ok": True,
                    "event_count": len(events_with_ids),
                    "out_path": out_path.resolve().as_posix(),
                },
                indent=2,
                sort_keys=True,
            )
        )
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
                schema_path=schemas /"routing_plan.schema.json",
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
    if args.command == "gates":
        from mmo.core.registries.gates_registry import load_gates_registry  # noqa: WPS433

        gates_path = ontology / "policies" / "gates.yaml"
        if args.gates_command == "list":
            try:
                reg = load_gates_registry(gates_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            policy_ids = reg.get_policy_ids()
            if args.format == "json":
                print(json.dumps(policy_ids, indent=2, sort_keys=True))
            else:
                for pid in policy_ids:
                    print(pid)
            return 0

        if args.gates_command == "show":
            try:
                reg = load_gates_registry(gates_path)
                policy = reg.get_policy(args.policy_id)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(policy, indent=2, sort_keys=True))
            else:
                pid = policy.get("policy_id", "")
                print(pid)
                meta = policy.get("meta")
                if isinstance(meta, dict):
                    version = meta.get("gates_version", "")
                    if version:
                        print(f"version: {version}")
                gates_map = policy.get("gates")
                if isinstance(gates_map, dict):
                    print(f"gates: {len(gates_map)}")
                    for gate_id in sorted(gates_map.keys()):
                        gate = gates_map[gate_id]
                        label = gate.get("label", "") if isinstance(gate, dict) else ""
                        kind = gate.get("kind", "") if isinstance(gate, dict) else ""
                        print(f"  {gate_id}: {label} [{kind}]")
            return 0

        print(f"Unknown gates command: {args.gates_command}", file=sys.stderr)
        return 2

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
            layouts_path = ontology /"layouts.yaml"
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
                    repo_root=None,
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
                    repo_root=None,
                    qa_payload=report,
                    profile_id=effective_profile,
                    profiles_path=ontology /"policies" / "authority_profiles.yaml",
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
                    repo_root=None,
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
                    repo_root=None,
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

        layouts_path = ontology /"layouts.yaml"
        registry_path = ontology /"policies" / "downmix.yaml"
        try:
            matrix = resolve_downmix_matrix(
                repo_root=None,
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
                    print("Dry run - no file written.")
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
