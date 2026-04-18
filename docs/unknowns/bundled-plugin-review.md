<!-- markdownlint-disable-file MD013 -->

# Bundled Plugin Review Unknowns

This file records the confidence gaps left after the bundled-plugin read-only
review.

| Area or file | Concern | Why it matters | Evidence found so far | Likely owner if known | Next best check | Risk level |
| --- | --- | --- | --- | --- | --- | --- |
| `plugins/examples/*`, `src/mmo/core/plugin_loader.py`, and `docs/13-plugin-authoring.md` | Example plugin manifests are documented as authoring material, but the checkout loader still discovers them as runtime plugins | Checkout behavior can expose plugin metadata and choices that the packaged fallback does not ship | `docs/review/bundled-plugin-review.md`; `src/mmo/core/plugin_loader.py`; repo counts from `plugins/` versus `src/mmo/data/plugins/`; `docs/13-plugin-authoring.md` | plugin or docs maintainers | Decide whether examples should stay checkout-visible, move behind a narrower root, or keep the current split with a clearer authority note | High |
| `src/mmo/data/plugin_market/assets/plugins/*`, `src/mmo/data/ontology/plugin_index.yaml`, and `src/mmo/plugins/*` | The offline market asset tree is a separate shipped authority, but parity with shipped runtime modules is not fully proven | Drift here can change installed plugin behavior even when the smaller packaged fallback root stays stable | `docs/review/bundled-plugin-review.md`; `src/mmo/core/plugin_market.py`; `src/mmo/data/ontology/plugin_index.yaml`; spot checks showed packaged market modules are not always byte-identical to `src/mmo/plugins/*` | plugin or release maintainers | Run a bounded parity audit on one plugin family at a time before planning any hardening change | High |
