from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, TypedDict


PLUGIN_SUPPORTED_CONTEXTS = ("suggest", "auto_apply", "render")


@dataclass(frozen=True)
class PluginSceneCapabilities:
    supports_objects: bool | None = None
    supports_beds: bool | None = None
    supports_locks: bool | None = None
    requires_speaker_positions: bool | None = None
    supported_target_ids: tuple[str, ...] | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if isinstance(self.supports_objects, bool):
            payload["supports_objects"] = self.supports_objects
        if isinstance(self.supports_beds, bool):
            payload["supports_beds"] = self.supports_beds
        if isinstance(self.supports_locks, bool):
            payload["supports_locks"] = self.supports_locks
        if isinstance(self.requires_speaker_positions, bool):
            payload["requires_speaker_positions"] = self.requires_speaker_positions
        if self.supported_target_ids is not None:
            payload["supported_target_ids"] = list(self.supported_target_ids)
        return payload


@dataclass(frozen=True)
class PluginPurityContract:
    audio_buffer: str | None = None
    randomness: str | None = None
    wall_clock: str | None = None
    thread_scheduling: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if isinstance(self.audio_buffer, str) and self.audio_buffer:
            payload["audio_buffer"] = self.audio_buffer
        if isinstance(self.randomness, str) and self.randomness:
            payload["randomness"] = self.randomness
        if isinstance(self.wall_clock, str) and self.wall_clock:
            payload["wall_clock"] = self.wall_clock
        if isinstance(self.thread_scheduling, str) and self.thread_scheduling:
            payload["thread_scheduling"] = self.thread_scheduling
        return payload


@dataclass(frozen=True)
class PluginDeclares:
    problem_domains: tuple[str, ...] | None = None
    emits_issue_ids: tuple[str, ...] | None = None
    consumes_issue_ids: tuple[str, ...] | None = None
    suggests_action_ids: tuple[str, ...] | None = None
    related_feature_ids: tuple[str, ...] | None = None
    target_scopes: tuple[str, ...] | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if self.problem_domains is not None:
            payload["problem_domains"] = list(self.problem_domains)
        if self.emits_issue_ids is not None:
            payload["emits_issue_ids"] = list(self.emits_issue_ids)
        if self.consumes_issue_ids is not None:
            payload["consumes_issue_ids"] = list(self.consumes_issue_ids)
        if self.suggests_action_ids is not None:
            payload["suggests_action_ids"] = list(self.suggests_action_ids)
        if self.related_feature_ids is not None:
            payload["related_feature_ids"] = list(self.related_feature_ids)
        if self.target_scopes is not None:
            payload["target_scopes"] = list(self.target_scopes)
        return payload


@dataclass(frozen=True)
class PluginBehaviorContract:
    loudness_behavior: str | None = None
    max_integrated_lufs_delta: float | None = None
    peak_behavior: str | None = None
    max_true_peak_delta_db: float | None = None
    phase_behavior: str | None = None
    stereo_image_behavior: str | None = None
    gain_compensation: str | None = None
    rationale: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if isinstance(self.loudness_behavior, str) and self.loudness_behavior:
            payload["loudness_behavior"] = self.loudness_behavior
        if isinstance(self.max_integrated_lufs_delta, (int, float)):
            payload["max_integrated_lufs_delta"] = float(self.max_integrated_lufs_delta)
        if isinstance(self.peak_behavior, str) and self.peak_behavior:
            payload["peak_behavior"] = self.peak_behavior
        if isinstance(self.max_true_peak_delta_db, (int, float)):
            payload["max_true_peak_delta_db"] = float(self.max_true_peak_delta_db)
        if isinstance(self.phase_behavior, str) and self.phase_behavior:
            payload["phase_behavior"] = self.phase_behavior
        if isinstance(self.stereo_image_behavior, str) and self.stereo_image_behavior:
            payload["stereo_image_behavior"] = self.stereo_image_behavior
        if isinstance(self.gain_compensation, str) and self.gain_compensation:
            payload["gain_compensation"] = self.gain_compensation
        if isinstance(self.rationale, str) and self.rationale:
            payload["rationale"] = self.rationale
        return payload


@dataclass(frozen=True)
class PluginCapabilities:
    max_channels: int | None = None
    channel_mode: str | None = None
    supported_group_sizes: tuple[int, ...] | None = None
    supported_link_groups: tuple[str, ...] | None = None
    bed_only: bool | None = None
    requires_speaker_positions: bool | None = None
    scene_scope: str | None = None
    layout_safety: str | None = None
    deterministic_seed_policy: str | None = None
    purity: PluginPurityContract | None = None
    supported_layout_ids: tuple[str, ...] | None = None
    supported_contexts: tuple[str, ...] | None = None
    scene: PluginSceneCapabilities | None = None
    notes: tuple[str, ...] | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if isinstance(self.max_channels, int):
            payload["max_channels"] = self.max_channels
        if isinstance(self.channel_mode, str) and self.channel_mode:
            payload["channel_mode"] = self.channel_mode
        if self.supported_group_sizes is not None:
            payload["supported_group_sizes"] = list(self.supported_group_sizes)
        if self.supported_link_groups is not None:
            payload["supported_link_groups"] = list(self.supported_link_groups)
        if isinstance(self.bed_only, bool):
            payload["bed_only"] = self.bed_only
        if isinstance(self.requires_speaker_positions, bool):
            payload["requires_speaker_positions"] = self.requires_speaker_positions
        if isinstance(self.scene_scope, str) and self.scene_scope:
            payload["scene_scope"] = self.scene_scope
        if isinstance(self.layout_safety, str) and self.layout_safety:
            payload["layout_safety"] = self.layout_safety
        if isinstance(self.deterministic_seed_policy, str):
            payload["deterministic_seed_policy"] = self.deterministic_seed_policy
        if self.purity is not None:
            purity_payload = self.purity.to_dict()
            if purity_payload:
                payload["purity"] = purity_payload
        if self.supported_layout_ids is not None:
            payload["supported_layout_ids"] = list(self.supported_layout_ids)
        if self.supported_contexts is not None:
            payload["supported_contexts"] = list(self.supported_contexts)
        if self.scene is not None:
            scene_payload = self.scene.to_dict()
            if scene_payload:
                payload["scene"] = scene_payload
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
    impact: str
    risk: str
    requires_approval: bool
    scope: Dict[str, Any]
    params: List[Dict[str, Any]]
    deltas: List[Dict[str, Any]]
    rollback: List[Dict[str, str]]
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
    export_finalization_receipt: Dict[str, Any]
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
