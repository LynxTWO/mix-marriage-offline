from __future__ import annotations

from typing import Any, Dict, List

from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin


class ConservativeEqResolver(ResolverPlugin):
    plugin_id = "PLUGIN.RESOLVER.CONSERVATIVE_EQ"

    def resolve(
        self,
        session: Dict[str, Any],
        features: Dict[str, Any],
        issues: List[Issue],
    ) -> List[Recommendation]:
        return []
