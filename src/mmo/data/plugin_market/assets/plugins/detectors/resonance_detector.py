from __future__ import annotations

from typing import Any, Dict, List

from mmo.plugins.interfaces import DetectorPlugin, Issue


class ResonanceDetector(DetectorPlugin):
    plugin_id = "PLUGIN.DETECTOR.RESONANCE"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        return []
