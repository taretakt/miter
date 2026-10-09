# Changelog

All notable changes to MITER, per [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
One extension per version, tests attached.

## [0.6.0] — 2026-10-05

### Added
- NL compiler catches up: windowed and aggregate phrasings compile to real specs
  (draft + `SEVERITY warn` + NOTE on what to review).
- `NOTICE` narrowed to rolling / consecutive / conditional / set structure loss.

## [0.5.0] — 2026-10-03

### Added
- Window clause: `WITHIN` / `TIME` / `LIMIT` rolling rules, deterministic sliding scan.
- Envelope complete: numeric, categorical, aggregate, two-leg, windowed.

## [0.4.0] — 2026-10-02

### Added
- Two-leg interfaces: `JOIN` keys pair rows across subjects (strict 1:1).
- `check_pair(entity, lane)` refactor; dataset-level resolution with verdict refresh.

## [0.3.0] — 2026-10-01

### Added
- Categorical equality: `FIELD tag == "urgent"`.
- Raw-value `nested_get`; compiler closed phrasings; dead-block cleanup.

## [0.2.0] — 2026-09-30

### Added
- Dataset-level aggregates: AVG / SUM / MIN / MAX / COUNT.
- Compiler `NOTICE` for lost structure; CLI exit code covers aggregate verdicts.

## [0.1.0] — 2026-09-29

### Added
- MITER v0.1.0: deterministic workflow-evaluation DSL with a natural-language
  compiler. Numeric criteria, verdicts, exit code covers dataset verdicts.

## Prior

- 2026-10-06 — trust: PyPI-verified build metadata, CI matrix (3.11–3.13),
  README test badge.
- 2026-10-06 — brand: merge-envelope mark, og card, favicon, header glyph.
- 2026-10-06 — site: homepage (signal-layer grammar, live demo output).
- 2026-10-04 — docs: bounding analysis — empirically probed DSL limits and
  extension path.
- 2026-10-03 — docs: positioning — problem framing, thesis, boundaries.