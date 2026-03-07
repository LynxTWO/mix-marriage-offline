# Ontology Migrations

This directory stores versioned migration notes for ontology breaking changes.

Policy:

- Additive ontology changes do not require a migration note.
- If an ontology ID is removed or renamed, bump `ontology.ontology_version` in
  `ontology/ontology.yaml` and add `docs/ontology_migrations/<new_version>.md`.
- Migration notes must list removed IDs and their replacement or retirement
  rationale.

Use `docs/ontology_migrations/TEMPLATE.md` when authoring a new migration note.
