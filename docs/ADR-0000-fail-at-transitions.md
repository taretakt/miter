# ADR-0000: Fail at transitions, not states

Status: accepted
Date: 2026-10-07 (codified from the repo README's opening claim)

## Context

Most evaluation tools check *states*: is this field under its threshold? MITER's claim is that
workflows are sequences of connected segments, and the transition is where work actually fails —
an entity crossing into a new lane must meet the receiving lane's conditions, inside a tolerance
and a time budget. MITER makes that constraint checkable instead of metaphorical.

## Decision

The DSL's load-bearing construct is the **lane-crossing check**: every CRITERION must be
expressible as a transition (origin → receiving lane, inside tolerance + time budget), never a
bare field threshold. A criterion that cannot name its transition is a state check and does not
belong in MITER's core.

## Consequences

- New criterion types get rejected unless they carry origin/receiving semantics.
- Benchmarks measure failed transitions against real workflow data, not pass/fail on fields.
- The compiler's natural-language front must resolve "into/out of/across" phrasings into
  transition objects, or it fails the parse (deterministic, fail-at-transitions).
