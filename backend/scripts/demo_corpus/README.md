# Demo corpus

A small, purpose-built corpus for the public demo, seeded by
`scripts/seed_demo.py`. It is deliberately committed (unlike the gitignored NIST
eval corpus) so it exists inside the deployed container. Everything here is
fictional — "Project Aurora" is invented — so nothing is a real-world claim.

## Files

- `aurora-overview.md`, `aurora-technical.md` — text documents with specific,
  retrievable facts (capacity, budget, battery size, inverter efficiency). These
  drive `/query`, `/query/stream`, and live `/research`.
- `aurora-quarterly-output.pdf` — a single-page bar chart whose values are
  printed as explicit label-value pairs (`Q3 4.8 GWh`, a totals line, etc.). This
  drives the vision surface (`/vision/*`): the caption model transcribes the
  labelled values at ingest, so the image is findable by content. It carries no
  extractable text, so it contributes an image but zero chunks — by design.

## Provenance (how the non-text assets were made)

- The chart PDF was rendered once with Pillow (a bar chart with value labels,
  saved as a one-page PDF). It is committed as a static asset; there is no need
  to regenerate it.
- `../demo_research_task.json` is the pre-seeded COMPLETED research task. It is
  **real pipeline output**, not hand-authored: the research orchestrator was run
  once over this corpus (`SEARCH_PROVIDER=null`, so knowledge-base only) and the
  resulting `ResearchResponse` was captured verbatim. Its `KBFinding` citations
  carry the chunk/document ids from that capture run; the research UI renders the
  stored result blob directly (it never re-queries those ids), so they are
  cosmetic — the report content is what shows.
