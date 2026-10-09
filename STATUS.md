# MITER status

Status as of **2026-10-07** — maintained by the integrator after every verified milestone. Agents
read this FIRST.

## At a glance

| Question | Answer |
|---|---|
| What is it | A deterministic workflow-evaluation DSL with a natural-language compiler — checks TRANSITIONS, not states (fail-at-transitions). |
| How far to alpha | Working core (compiler + criteria engine + examples + CI badge) — alpha shipped; gaps are breadth, not skeleton. |
| Biggest single gap | No benchmark against a real lane dataset — proven on examples/, not yet on real workflow data |

## Milestone checklist

| Milestone | State | Notes |
|---|---|---|
| Scaffold + git identity | done | |
| Core DSL: EVALUATION/SUBJECT/INPUTS/CRITERION | done | README-documented, examples/ present |
| Natural-language compiler | done (minor gaps) | claims vs measured on real workflows not yet benchmarked |
| CI (gh badge: tests) | done | badge fixed to ci.yml 2026-10-06; PyPI-verified metadata; matrix 3.11–3.13 |
| Asset provenance gate | done | ATTRIBUTION.md added 2026-10-07 |

## Notes for the next agent session

- The transition-first semantics are the load-bearing idea — any new criterion type must express a
  lane-crossing check, not just a field threshold (ADR-0000).
- Confirm/repair the GH remote + CI badge claim before marketing the repo publicly.
