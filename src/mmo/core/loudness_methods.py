from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LOUDNESS_METHOD_ID = "BS.1770-5"


@dataclass(frozen=True)
class LoudnessMethod:
    method_id: str
    label: str
    implemented: bool
    notes: str


_LOUDNESS_METHODS: dict[str, LoudnessMethod] = {
    "BS.1770-5": LoudnessMethod(
        method_id="BS.1770-5",
        label="ITU-R BS.1770-5 Program Loudness",
        implemented=True,
        notes=(
            "Position-aware Gi weighting with LFE exclusion for mono through "
            "advanced sound system layouts."
        ),
    ),
    "BS.1770-5-DIALOG-GATED": LoudnessMethod(
        method_id="BS.1770-5-DIALOG-GATED",
        label="BS.1770-5 Dialog-Gated Loudness (placeholder)",
        implemented=False,
        notes="Reserved for future dialog-gated workflows.",
    ),
    "BS.1770-5-DIALOG-ANCHOR": LoudnessMethod(
        method_id="BS.1770-5-DIALOG-ANCHOR",
        label="BS.1770-5 Dialog-Anchor Loudness (placeholder)",
        implemented=False,
        notes="Reserved for future dialog-anchor workflows.",
    ),
}


def list_loudness_method_ids() -> list[str]:
    return sorted(_LOUDNESS_METHODS.keys())


def get_loudness_method(method_id: str | None) -> LoudnessMethod:
    normalized = str(method_id or "").strip()
    if not normalized:
        normalized = DEFAULT_LOUDNESS_METHOD_ID

    method = _LOUDNESS_METHODS.get(normalized)
    if method is None:
        known = ", ".join(list_loudness_method_ids())
        raise ValueError(
            f"Unknown loudness method_id: {normalized!r}. Known method_ids: {known}"
        )
    return method


def require_implemented_loudness_method(method_id: str | None) -> str:
    method = get_loudness_method(method_id)
    if method.implemented:
        return method.method_id
    raise NotImplementedError(
        (
            f"Loudness method {method.method_id!r} is registered but not implemented. "
            f"Use {DEFAULT_LOUDNESS_METHOD_ID!r} for now."
        )
    )
