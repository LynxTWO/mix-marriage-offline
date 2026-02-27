from __future__ import annotations

from typing import Any, Dict, List

from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin


class SafeRenderer(RendererPlugin):
    plugin_id = "PLUGIN.RENDERER.SAFE"

    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
        output_dir: Any = None,
    ) -> RenderManifest:
        received_ids = [
            rec_id
            for rec in recommendations
            if isinstance(rec, dict) and isinstance((rec_id := rec.get("recommendation_id")), str)
        ]
        return {
            "renderer_id": self.plugin_id,
            "outputs": [],
            "notes": "stub",
            "received_recommendation_ids": received_ids,
        }
