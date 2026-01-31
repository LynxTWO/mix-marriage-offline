# Policy fixtures

This folder contains fixtures for validating **policy YAML integrity** in a deterministic way.

- `fixtures/policies/downmix/` includes downmix registry and policy-pack cases.

These fixtures are meant to back unit tests that load a registry file, validate all referenced packs and matrices, and assert expected `ISSUE.VALIDATION.*` results.
