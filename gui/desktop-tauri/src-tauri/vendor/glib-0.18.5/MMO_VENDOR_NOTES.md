# MMO vendored glib 0.18.5 notes

Base source:
- crates.io `glib 0.18.5`
- upstream `gtk-rs-core` tag/branch `0.18.5` / `0.18`
- upstream source commit `42b9caf98e03ded086362d9653ca58fe94dc8658`

Why this override exists:
- `tauri 2.10.3` on Linux still resolves through `gtk 0.18.2 -> glib 0.18.5`.
- The published `gtk-rs` `0.18` line has no newer `glib` release today, so we
  cannot remove the override by a normal `cargo update`.

Local backports kept in this vendor tree:
- `src/variant_iter.rs`: the `VariantStrIter::impl_get` pointer fix for
  `GHSA-wrw7-89jp-8q8g`.
- Rust 1.94 compile-clean signature updates: lifetime/type syntax cleanups that
  newer `gtk-rs-core` `glib` sources already use, so `-D warnings` Linux
  package builds do not fail on `unused_parens` or
  `mismatched_lifetime_syntaxes`.

Refresh recipe:
1. Start from the crates.io `glib 0.18.5` source or the matching Cargo registry
   checkout.
2. Reapply the `src/variant_iter.rs` security fix.
3. Reapply the warning-clean signature updates from this vendor diff or the
   equivalent newer upstream `gtk-rs-core` `glib` sources.
4. Keep generated `Cargo.lock` and `target/` content out of the vendor tree.

Exit path:
- Remove the `[patch.crates-io]` override once published Tauri/Wry/WebKitGTK
  dependencies can resolve to a published `glib` release newer than `0.18.5`.
