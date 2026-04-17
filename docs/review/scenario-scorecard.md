# Scenario Stress-Test Scorecard

<!-- markdownlint-disable-file MD013 -->

Scale:

- `0` = current docs miss or mis-handle the scenario
- `1` = current docs partly catch it, but the boundary is still ambiguous
- `2` = current docs catch it cleanly

| Scenario | Repo-fit detection | Hidden-entrypoint capture | Control-plane capture | Approval safety | Evidence discipline | Coverage honesty | Exact change to raise low scores |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Quiet support script mutates repo or packaged state | `2` | `1` | `1` | `1` | `2` | `1` | Keep support scripts with delete or sync side effects in a dedicated control-plane slice and tie them back to AGENTS approval language. |
| Helper entrypoint changes trusted review evidence | `2` | `1` | `1` | `1` | `2` | `1` | Name direct render, benchmark, and screenshot helpers as evidence control planes, not only as tooling or examples. |
| Release control plane outruns the runtime story | `2` | `2` | `1` | `1` | `1` | `1` | Keep the out-of-repo release boundary explicit in the map and require sanitized release receipts before claiming this path is well understood. |
| Public docs deploy becomes shipped behavior | `2` | `1` | `0` | `1` | `2` | `0` | Separate `site/` and `pages.yml` from generic examples so docs publish is treated as a public control plane. |
| Product output escapes into telemetry | `2` | `2` | `1` | `1` | `1` | `0` | Add a ledger note for machine-readable product output and local traces that can escape into CI, support, or issue threads. |
| Shared plugin contracts hide bundled implementation behavior | `2` | `1` | `1` | `1` | `2` | `1` | Keep bundled plugin implementations and packaged plugin data separate from the shared contract and authoring rows. |
| Steering-file drift through mirrored paths | `2` | `1` | `1` | `2` | `2` | `1` | Keep mirrored workspace copies and generated or vendored paths labeled as non-authoritative in steering docs and review outputs. |
