from __future__ import annotations

from typing import Any, Dict, List

from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin


class SafeRenderer(RendererPlugin):
    plugin_id = "PLUGIN.RENDERER.SAFE"

    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
    ) -> RenderManifest:
        return {"renderer_id": self.plugin_id, "outputs": [], "notes": "stub"}
