"""Safe renderer: approval-gate audit pass.

Does NOT write audio.  Instead it inspects every eligible recommendation and
categorises it by authority level, producing a machine-readable audit trail in
the manifest so downstream tooling can see exactly which recommendations were
auto-approved, which require explicit user approval, and which exceed the
configured risk budget.

Outputs list: always empty (no audio files written).
Skipped list: every recommendation that arrived, tagged with one of:

  safe_auto_approved   — risk=low, requires_approval=False, within policy
  requires_approval    — requires_approval=True (any risk level)
  risk_exceeds_limit   — risk is "high" (never auto-applied)
  invalid_rec          — malformed recommendation dict

Because the safe_renderer itself changes nothing in the audio, its behaviour
contract (true-peak delta ≈ 0, loudness delta ≈ 0) is satisfied trivially.
The renderer is intended to run alongside DSP renderers so that every render
pass has an explicit approval audit receipt attached to the manifest.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin

_PLUGIN_ID = "PLUGIN.RENDERER.SAFE"

_REASON_AUTO_APPROVED = "safe_auto_approved"
_REASON_REQUIRES_APPROVAL = "requires_approval"
_REASON_RISK_EXCEEDS_LIMIT = "risk_exceeds_limit"
_REASON_INVALID_REC = "invalid_rec"

_HIGH_RISK_VALUES = {"high"}
_MEDIUM_RISK_VALUES = {"medium"}
_LOW_RISK_VALUES = {"low"}


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _gate_summary_for_rec(rec: Dict[str, Any]) -> str:
    """Build a brief human-readable gate summary from the recommendation."""
    risk = _coerce_str(rec.get("risk")) or "unknown"
    req_approval = rec.get("requires_approval")
    req_str = "requires_approval=True" if req_approval is True else "requires_approval=False"
    return f"risk={risk} {req_str}"


def _classify_rec(rec: Dict[str, Any]) -> str:
    """Return the reason string for categorising this recommendation."""
    if not isinstance(rec, dict):
        return _REASON_INVALID_REC

    risk = _coerce_str(rec.get("risk")).strip().lower()
    requires_approval = rec.get("requires_approval")

    if risk in _HIGH_RISK_VALUES:
        return _REASON_RISK_EXCEEDS_LIMIT
    if requires_approval is True:
        return _REASON_REQUIRES_APPROVAL
    if risk in _LOW_RISK_VALUES and requires_approval is False:
        return _REASON_AUTO_APPROVED
    if risk in _MEDIUM_RISK_VALUES and requires_approval is False:
        # Medium risk with no explicit approval needed: treat as conditional
        # auto-approved; the gate policy already admitted it as eligible.
        return _REASON_AUTO_APPROVED
    # Anything remaining (approval status unclear or risk unrecognised)
    return _REASON_REQUIRES_APPROVAL


class SafeRenderer(RendererPlugin):
    """Approval-gate audit renderer.

    Writes no audio.  Emits every recommendation to the skipped list with a
    reason tag so callers have a machine-readable record of the approval
    disposition for every recommendation that reached this renderer.
    """

    plugin_id = _PLUGIN_ID

    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
        output_dir: Any = None,
    ) -> RenderManifest:
        skipped: List[Dict[str, Any]] = []

        for rec in recommendations:
            if not isinstance(rec, dict):
                skipped.append({
                    "recommendation_id": "",
                    "action_id": "",
                    "reason": _REASON_INVALID_REC,
                    "gate_summary": "",
                })
                continue

            rec_id = _coerce_str(rec.get("recommendation_id"))
            action_id = _coerce_str(rec.get("action_id"))
            reason = _classify_rec(rec)
            gate_summary = _gate_summary_for_rec(rec)

            skipped.append({
                "recommendation_id": rec_id,
                "action_id": action_id,
                "reason": reason,
                "gate_summary": gate_summary,
            })

        skipped.sort(key=lambda s: (
            s.get("reason", ""),
            s.get("recommendation_id", ""),
            s.get("action_id", ""),
        ))

        return {
            "renderer_id": self.plugin_id,
            "outputs": [],
            "skipped": skipped,
        }
