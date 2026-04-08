"""Masking resolver: maps masking issues → corrective EQ recommendations.

Handles two issue types:

ISSUE.MASKING.KICK_BASS
  The kick and bass are competing in the 60–200 Hz zone.  Strategy: recommend
  a gentle bell cut on the bass in the overlap band (~100 Hz).  The bass is
  cut rather than the kick because bass fundamentals sit longer in that zone
  and a cut there reduces muddiness without removing kick punch.
  risk=medium, requires_approval=True.

ISSUE.MASKING.VOCAL_VS_MUSIC
  The lead vocal is being masked by competing instruments in the 1–4 kHz
  intelligibility band.  Strategy: recommend a gentle bell cut on each
  non-vocal stem in the session at the peak intelligibility frequency (~2 kHz).
  Cut depth scales with masking severity.  Up to _MAX_MUSIC_STEMS competing
  stems are targeted (by stem_id, alphabetically for determinism).
  risk=medium, requires_approval=True.

All recommendations are medium-risk and require approval — these are
cross-stem, taste-dependent decisions that the engineer must sanity-check.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin

_PLUGIN_ID = "PLUGIN.RESOLVER.MASKING"

# ---- Kick/bass constants ----
_KB_CUT_FREQ_HZ = 100.0      # center of kick/bass overlap zone
_KB_CUT_Q = 0.80             # broad enough to cover 60–200 Hz territory
_KB_BASE_CUT_DB = -2.0       # starting point
_KB_MAX_CUT_DB = -4.0        # hard cap for this resolver

# ---- Vocal/music constants ----
_VIM_CUT_FREQ_HZ = 2_000.0   # peak intelligibility frequency
_VIM_CUT_Q = 0.70            # broad — covers the whole 1–4 kHz zone gently
_VIM_BASE_CUT_DB = -1.5
_VIM_MAX_CUT_DB = -3.5
_VIM_MASKING_MILD = 2.5      # ratio thresholds matching the detector
_VIM_MASKING_MODERATE = 4.0
_MAX_MUSIC_STEMS = 4         # cap on how many competing stems we target

# Filename/role tokens for identifying vocal vs non-vocal stems
_VOCAL_ROLE_PREFIXES = ("ROLE.VOCAL.", "ROLE.DIALOGUE.")
_VOCAL_NAME_TOKENS = frozenset(
    ("vox", "vocal", "lead", "ld_vox", "ldvox", "leadv", "voice", "singer")
)


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _make_rec_id(prefix: str, stem_id: str, action_id: str, extra: str = "") -> str:
    name = f"{prefix}:{stem_id}:{action_id}:{extra}"
    return f"REC.{uuid.uuid5(uuid.NAMESPACE_OID, name).hex[:16].upper()}"


# ---------------------------------------------------------------------------
# Kick/bass helpers
# ---------------------------------------------------------------------------

def _kb_stem_ratio(evidence: List[Dict[str, Any]], stem_id: str) -> Optional[float]:
    """Find the band energy ratio evidence entry for a specific stem."""
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") != "EVID.SPECTRAL.BAND_ENERGY_RATIO":
            continue
        where = entry.get("where") or {}
        track_ref = where.get("track_ref") or {}
        if _coerce_str(track_ref.get("track_name")) == stem_id:
            return _coerce_float(entry.get("value"))
    return None


def _kb_cut_depth(ratio: Optional[float]) -> float:
    """Scale cut depth from band ratio."""
    _RATIO_THRESH = 0.20    # detector threshold for both stems having >20% in zone
    _RATIO_CEIL = 0.55
    if ratio is None or ratio <= _RATIO_THRESH:
        return _KB_BASE_CUT_DB
    t = min(1.0, (ratio - _RATIO_THRESH) / (_RATIO_CEIL - _RATIO_THRESH))
    cut = _KB_BASE_CUT_DB + (_KB_MAX_CUT_DB - _KB_BASE_CUT_DB) * t
    return max(_KB_MAX_CUT_DB, min(_KB_BASE_CUT_DB, cut))


def _kick_bass_recommendations(issue: Dict[str, Any]) -> List[Recommendation]:
    target = issue.get("target")
    if not isinstance(target, dict):
        return []

    kick_id = _coerce_str(target.get("stem_id")).strip()
    bass_id = _coerce_str(target.get("secondary_stem_id")).strip()
    if not kick_id or not bass_id:
        return []

    evidence = issue.get("evidence") or []
    bass_ratio = _kb_stem_ratio(evidence, bass_id)
    kick_ratio = _kb_stem_ratio(evidence, kick_id)

    recs: List[Recommendation] = []

    # Primary: cut the bass in the overlap zone — bass fundamentals extend
    # lower and a cut here won't remove kick attack.
    bass_cut = _kb_cut_depth(bass_ratio)
    bass_ratio_str = f"{bass_ratio:.3f}" if bass_ratio is not None else "n/a"
    recs.append({
        "recommendation_id": _make_rec_id("KB.BASS", bass_id, "ACTION.EQ.BELL_CUT", str(_KB_CUT_FREQ_HZ)),
        "issue_id": _coerce_str(issue.get("issue_id")),
        "action_id": "ACTION.EQ.BELL_CUT",
        "impact": "moderate",
        "risk": "medium",
        "requires_approval": True,
        "scope": {"scope": "stem", "stem_id": bass_id},
        "params": [
            {"param_id": "PARAM.EQ.FREQ_HZ", "value": _KB_CUT_FREQ_HZ},
            {"param_id": "PARAM.EQ.Q", "value": _KB_CUT_Q},
            {"param_id": "PARAM.EQ.GAIN_DB", "value": round(bass_cut, 2)},
        ],
        "notes": (
            f"Kick/bass masking: cut bass at {_KB_CUT_FREQ_HZ:.0f} Hz "
            f"({bass_cut:+.2f} dB, Q {_KB_CUT_Q}) to reduce overlap with kick. "
            f"Bass band ratio: {bass_ratio_str}. "
            "Audition in context — bass character may shift."
        ),
        "evidence": evidence,
    })

    # Secondary (if kick also has significant presence in the zone): gentle kick cut too.
    # Only add if kick ratio is substantial (above a moderate threshold).
    _KICK_SECONDARY_THRESH = 0.30
    if kick_ratio is not None and kick_ratio > _KICK_SECONDARY_THRESH:
        kick_cut = round(_kb_cut_depth(kick_ratio) * 0.6, 2)  # shallower cut on kick
        kick_ratio_str = f"{kick_ratio:.3f}"
        recs.append({
            "recommendation_id": _make_rec_id("KB.KICK", kick_id, "ACTION.EQ.BELL_CUT", str(_KB_CUT_FREQ_HZ)),
            "issue_id": _coerce_str(issue.get("issue_id")),
            "action_id": "ACTION.EQ.BELL_CUT",
            "impact": "low",
            "risk": "medium",
            "requires_approval": True,
            "scope": {"scope": "stem", "stem_id": kick_id},
            "params": [
                {"param_id": "PARAM.EQ.FREQ_HZ", "value": _KB_CUT_FREQ_HZ},
                {"param_id": "PARAM.EQ.Q", "value": _KB_CUT_Q},
                {"param_id": "PARAM.EQ.GAIN_DB", "value": kick_cut},
            ],
            "notes": (
                f"Kick/bass masking: secondary trim on kick at {_KB_CUT_FREQ_HZ:.0f} Hz "
                f"({kick_cut:+.2f} dB, Q {_KB_CUT_Q}). "
                f"Kick band ratio: {kick_ratio_str}. "
                "Shallower cut than bass; audition carefully."
            ),
            "evidence": evidence,
        })

    return recs


# ---------------------------------------------------------------------------
# Vocal / music helpers
# ---------------------------------------------------------------------------

def _is_vocal_stem(stem: Dict[str, Any]) -> bool:
    role_id = _coerce_str(stem.get("role_id")).strip()
    if role_id:
        return any(role_id.startswith(p) for p in _VOCAL_ROLE_PREFIXES)
    # Filename heuristic fallback
    stem_id = _coerce_str(stem.get("stem_id")).strip().lower()
    file_path = _coerce_str(stem.get("file_path")).strip().lower()
    label = _coerce_str(stem.get("label")).strip().lower()
    name = stem_id + " " + file_path + " " + label
    return any(tok in name for tok in _VOCAL_NAME_TOKENS)


def _vim_masking_ratio(evidence: List[Dict[str, Any]]) -> Optional[float]:
    """Find the overall masking ratio (the entry WITHOUT a track_ref)."""
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") != "EVID.SPECTRAL.BAND_ENERGY_RATIO":
            continue
        where = entry.get("where") or {}
        if "track_ref" not in where:
            return _coerce_float(entry.get("value"))
    return None


def _vim_cut_depth(masking_ratio: Optional[float]) -> float:
    """Scale cut depth from the music/vocal energy ratio."""
    if masking_ratio is None or masking_ratio <= _VIM_MASKING_MILD:
        return _VIM_BASE_CUT_DB
    if masking_ratio <= _VIM_MASKING_MODERATE:
        t = (masking_ratio - _VIM_MASKING_MILD) / (_VIM_MASKING_MODERATE - _VIM_MASKING_MILD)
        cut = _VIM_BASE_CUT_DB + (_VIM_MAX_CUT_DB - _VIM_BASE_CUT_DB) * t * 0.6
    else:
        cut = _VIM_MAX_CUT_DB
    return max(_VIM_MAX_CUT_DB, min(_VIM_BASE_CUT_DB, cut))


def _vocal_masking_recommendations(
    issue: Dict[str, Any],
    session: Dict[str, Any],
) -> List[Recommendation]:
    target = issue.get("target")
    if not isinstance(target, dict):
        return []

    vocal_id = _coerce_str(target.get("stem_id")).strip()
    if not vocal_id:
        return []

    evidence = issue.get("evidence") or []
    masking_ratio = _vim_masking_ratio(evidence)
    cut_db = _vim_cut_depth(masking_ratio)
    ratio_str = f"{masking_ratio:.2f}" if masking_ratio is not None else "n/a"

    # Find competing non-vocal stems from the session
    all_stems = [s for s in session.get("stems", []) if isinstance(s, dict)]
    competing_stems = [
        s for s in all_stems
        if _coerce_str(s.get("stem_id")).strip() != vocal_id
        and not _is_vocal_stem(s)
        and _coerce_str(s.get("stem_id")).strip()
    ]

    # Sort for determinism; cap at _MAX_MUSIC_STEMS
    competing_stems.sort(key=lambda s: _coerce_str(s.get("stem_id")))
    competing_stems = competing_stems[:_MAX_MUSIC_STEMS]

    recs: List[Recommendation] = []
    for stem in competing_stems:
        stem_id = _coerce_str(stem.get("stem_id")).strip()
        recs.append({
            "recommendation_id": _make_rec_id("VIM", stem_id, "ACTION.EQ.BELL_CUT", vocal_id),
            "issue_id": _coerce_str(issue.get("issue_id")),
            "action_id": "ACTION.EQ.BELL_CUT",
            "impact": "moderate",
            "risk": "medium",
            "requires_approval": True,
            "scope": {"scope": "stem", "stem_id": stem_id},
            "params": [
                {"param_id": "PARAM.EQ.FREQ_HZ", "value": _VIM_CUT_FREQ_HZ},
                {"param_id": "PARAM.EQ.Q", "value": _VIM_CUT_Q},
                {"param_id": "PARAM.EQ.GAIN_DB", "value": round(cut_db, 2)},
            ],
            "notes": (
                f"Vocal intelligibility masking: cut {stem_id} at "
                f"{_VIM_CUT_FREQ_HZ:.0f} Hz ({cut_db:+.2f} dB, Q {_VIM_CUT_Q}) "
                f"to create space for vocal '{vocal_id}'. "
                f"Music/vocal energy ratio: {ratio_str}x. "
                "Audition each stem individually — some may not need cutting."
            ),
            "evidence": evidence,
        })

    return recs


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class MaskingResolver(ResolverPlugin):
    plugin_id = _PLUGIN_ID

    def resolve(
        self,
        session: Dict[str, Any],
        features: Dict[str, Any],
        issues: List[Issue],
    ) -> List[Recommendation]:
        recommendations: List[Recommendation] = []
        # Deduplicate: one kick/bass rec-set per (kick_id, bass_id) pair;
        # one vocal/music rec-set per vocal_id
        kb_pairs_seen: set[tuple[str, str]] = set()
        vim_vocals_seen: set[str] = set()

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_id = _coerce_str(issue.get("issue_id"))

            if issue_id == "ISSUE.MASKING.KICK_BASS":
                target = issue.get("target") or {}
                kick_id = _coerce_str(target.get("stem_id")).strip()
                bass_id = _coerce_str(target.get("secondary_stem_id")).strip()
                pair = (kick_id, bass_id)
                if not kick_id or not bass_id or pair in kb_pairs_seen:
                    continue
                kb_pairs_seen.add(pair)
                recommendations.extend(_kick_bass_recommendations(issue))

            elif issue_id == "ISSUE.MASKING.VOCAL_VS_MUSIC":
                target = issue.get("target") or {}
                vocal_id = _coerce_str(target.get("stem_id")).strip()
                if not vocal_id or vocal_id in vim_vocals_seen:
                    continue
                vim_vocals_seen.add(vocal_id)
                recommendations.extend(_vocal_masking_recommendations(issue, session))

        return recommendations
