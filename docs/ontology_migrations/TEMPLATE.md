# Ontology Migration: <X.Y.Z>

Date: YYYY-MM-DD

## Version Change

- Previous ontology version: `<OLD_VERSION>`
- New ontology version: `<NEW_VERSION>`
- Change type: `major` | `minor` | `patch`

## Why This Migration Exists

Briefly explain why additive-only policy was insufficient.

## Removed or Renamed IDs

List every removed/renamed ID.

| Old ID | New ID (or `N/A`) | Notes |
| --- | --- | --- |
| `EXAMPLE.OLD.ID` | `EXAMPLE.NEW.ID` | Reason and compatibility guidance |

## Deprecations

If IDs remain present but are deprecated, list them with `replaced_by`.

| Deprecated ID | replaced_by | Notes |
| --- | --- | --- |
| `EXAMPLE.DEPRECATED.ID` | `EXAMPLE.REPLACEMENT.ID` | Sunset plan |

## Upgrade Guidance

Document concrete migration steps for fixtures, schemas, plugins, and reports.
