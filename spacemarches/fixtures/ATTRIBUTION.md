# Attribution — Eclipse Phase 2e reference data

The files in this directory are derived from the **Bubz43/ep2e** Foundry VTT
system (Unofficial Eclipse Phase 2e system for Foundry VTT, Bubz43 and contributors):

- Repository: https://github.com/Bubz43/ep2e
- Source content: `src/packs/` (per-item JSON for 55 packs, 1042 entries)
- License: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
  (the repository's README states CC BY 4.0). Posthuman Studios SA has
  the underlying Eclipse Phase intellectual property; this derived data keeps
  attribution as required by CC BY 4.0.

Derived here by a lossless-enough converter: each fixture entry stores the
pack's full `system` payload verbatim (including description, reference, and
type-specific fields) plus the pack's top-level `name`, `type`, and `_id`.

This is the 1.0 baseline — the ep2e Foundry system is the earlier Bubz system;
MeshNet (the website rewrite) carries additional niche character options.
Newer sources (gear sheets, later packs, MeshNet data) should be added with
their own `source` attribution, never overwriting bubz-ep2e rows.
