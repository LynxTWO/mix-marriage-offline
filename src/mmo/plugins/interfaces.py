from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, TypedDict


PLUGIN_SUPPORTED_CONTEXTS = ("suggest", "auto_apply", "render")


@dataclass(frozen=True)
class PluginCapabilities:
    max_channels: int | None = None
    supported_layout_ids: tuple[str, ...] | None = None
    supported_contexts: tuple[str, ...] | None = None
    notes: tuple[str, ...] | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if isinstance(self.max_channels, int):
            payload["max_channels"] = self.max_channels
        if self.supported_layout_ids is not None:
            payload["supported_layout_ids"] = list(self.supported_layout_ids)
        if self.supported_contexts is not None:
            payload["supported_contexts"] = list(self.supported_contexts)
        if self.notes is not None:
            payload["notes"] = list(self.notes)
        return payload


class Issue(TypedDict, total=False):
    issue_id: str
    severity: int
    confidence: float
    message: str
    target: Dict[str, Any]
    evidence: List[Dict[str, Any]]


class Recommendation(TypedDict, total=False):
    recommendation_id: str
    issue_id: str
    action_id: str
    risk: str
    requires_approval: bool
    target: Dict[str, Any]
    params: List[Dict[str, Any]]
    notes: str
    evidence: List[Dict[str, Any]]


class RenderOutput(TypedDict, total=False):
    output_id: str
    file_path: str
    action_id: str
    recommendation_id: str
    target_stem_id: str
    target_bus_id: str
    layout_id: str
    format: str
    codec: str
    sample_rate_hz: int
    bit_depth: int
    channel_count: int
    sha256: str
    notes: str
    metadata: Dict[str, Any]


class RenderSkipped(TypedDict, total=False):
    recommendation_id: str
    action_id: str
    reason: str
    gate_summary: str
    details: Dict[str, Any]


class RenderManifest(TypedDict, total=False):
    renderer_id: str
    outputs: List[RenderOutput]
    notes: str
    received_recommendation_ids: List[str]
    skipped: List[RenderSkipped]


class DetectorPlugin(ABC):
    plugin_id: str

    @abstractmethod
    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        raise NotImplementedError


class ResolverPlugin(ABC):
    plugin_id: str

    @abstractmethod
    def resolve(
        self,
        session: Dict[str, Any],
        features: Dict[str, Any],
        issues: List[Issue],
    ) -> List[Recommendation]:
        raise NotImplementedError


class RendererPlugin(ABC):
    plugin_id: str

    @abstractmethod
    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
    ) -> RenderManifest:
        raise NotImplementedError
