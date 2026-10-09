# MITER — Bounding Analysis: where the DSL ends, and why it ends there

*Empirical. Every claim below was probed against the running tool on 2026-10-05 (parser, compiler, and engine), not deduced from the README.*

**v0.2.0, shipped 2026-10-05: candidate extensions 1 (aggregates) and 3 (NOTICE) are BUILT and tested — 44 tests green.** The boundaries below were re-verified against the running tool after the change.

---

## The envelope in one sentence

MITER evaluates **numeric-field thresholds on independent, stateless rows, under deterministic perturbations, plus named transition checks between fields of the same subject** — and nothing else.

## Verified boundaries

| Can express | Cannot express |
|---|---|
| Numeric thresholds (`<`, `<=`, `>`, `>=`, `==`, `!=`) on a field | Categorical / string equality (`FIELD category == "urgent"` → parse error) |
| Numeric perturbations (`SCALE`, `OFFSET`, `SET`) | Aggregates (`AVG(coverage)`, `COUNT(...)` → parse error) |
| Named transition checks (`MATCH a TO b`, `TOLERANCE`, `BUDGET`, `TIME`) | Conditional / control flow (`IF … THEN …` → parse error) |
| Dot-path fields (`nested_get`: `foo.bar`) | Rolling / windowed rules (≥2 failures in 30 days → silently collapsed, see §5) |
| Missing field → `NA` (not a failure) | Cross-row statistics or joins |
| Error vs warn severity (error fails the verdict, warn reports) | Multi-subject transitions — an interface is a **within-row** check (`engine._evaluate_flat`: `i.check(row)`) |
| Per-row verdict plus PASS/FAIL rollup | Semantic / LLM-judged fields (no hook) |
| Byte-deterministic output with a spec hash | Sequencing / ordering / state across rows (engine is stateless per row) |

---

## Use case → gap analysis

### 1. Route feasibility — *the canonical case, native*
**Spec:** depot capacity ≤ 0.95, driver hours ≤ 14, volume ≤ 1.0 (warn), two variations (peak volume, driver exhaustion), two interfaces (expressway merge, offramp exit).
**Verdicts:** correct per row; variations fire; interfaces match within tolerance; failing rows exit non-zero.
**Bounding lesson:** this is what the DSL was shaped for. One subject, numeric fields, strictness hierarchy (error/warn), edge cases as perturbations, transitions as field matches.

### 2. AI response QC — *categorical and semantic fields*
**Intent:** "the reply must be classified URGENT when sentiment is hostile; tone must be professional; latency under 2s."
**Probe:** `FIELD category == "urgent"` → **parse error (exit 2).**
**Gap:** categories, strings, and anything semantic are unexpressible. No string operator, no enum, no hook for an LLM-judge adapter.
**Bounding condition:** **criteria are numeric-normalised** — `model.Criterion.evaluate` coerces via `float(value)`, and unmatched values become `NA`, not failures.

### 3. Dispatch handoff between two vehicles — *a true exchange*
**Intent:** "when vehicle A hands a load to vehicle B at the hub, B's capacity must absorb it within 15 minutes."
**Probe:** interface must name `FROM`/`TO`, but both fields resolve inside **one row** — `engine` calls `i.check(row)`.
**Gap:** the transition is modelled as *fields of the same subject* (velocity TO lane_velocity — one row). An actual exchange **between two subjects** (A's load, B's capacity) cannot be written.
**Bounding condition:** **interfaces are intra-subject, not inter-subject.** The ghost car has a lane to join but only inside its own trajectory.

### 4. Batch QC at scale — *aggregate coverage*
**Intent:** "≥90% of clusters classified; unclassified revenue ≤ 5%."
**Probe:** `FIELD AVG(coverage) >= 0.9` → **parse error.**
**Gap:** the engine *rolls up* (PASS/FAIL counts per `evaluate_all`) but the **spec language cannot name an aggregate.** Row-level summaries exist; dataset-level constraints don't.
**Bounding condition:** **no cross-row statistics in the language.** This is the widest practical gap for its actual domain (983K-lot classification QC).

### 5. Temporal / rolling-window rule — *the silent collapse*
**Intent:** "no more than two missed deliveries in any thirty days."
**Probe:** `miter compile "no more than two missed deliveries in thirty days"` compiled successfully… to:

```text
INPUTS no_more_than_two_missed_deliveries_in_thirty_days
CRITERION criterion_1
    FIELD no_more_than_two_missed_deliveries_in_thirty_days <= 0.0
    SEVERITY warn
    NOTE threshold not stated in source text; edit this bound
```

**Gap (the important one):** the temporal structure was **silently dropped**. The sentence's subject became a *field name* — the compiler didn't say "windowed semantics aren't supported"; it produced a plausible-looking field check plus a warn note about the *bound*. An operator could compile this, see a warn, fix the bound, and believe the rule was captured.
**Bounding condition:** **the NL compiler degrades unrecognized structure to a field check instead of refusing it.** It is honest about the missing threshold but silent about the missing semantics.

### 6. Conditional escalation — *control flow*
**Intent:** "if severity = error and load in band, route to human review."
**Probe:** `IF driver_hours > 14 THEN count_ok == 0` → **parse error.** NL compile "if driver hours exceed 14 then flag the trip" → same silent collapse as §5 (`value <= 0.0` warn).
**Bounding condition:** **no branching.** Failures are flat; escalation (which failures matter, in which combination) is not expressible.

---

## What this says about the design

1. **Determinism is doing the bounding.** Every gap above is the *same* constraint at a different place: the engine must be byte-deterministic, so the DSL refuses anything requiring state, randomness, or external judgment. That's the right trade. The extension path is: find deterministic encodings, not "loosen determinism."
2. **The model's honesty rule is real but partial.** The compiler refuses to invent thresholds (good) but does not refuse to invent field names (bad — §5). Fix: when a phrase contains structure the compiler can't represent, emit `SEVERITY warn` **and a NOTICE naming the lost structure** — e.g. *"windowed semantics not supported; compiled as a plain field check."*
3. **The intra-subject interface is a simplification of the ghost car.** Real handoffs are exchanges between entities. The within-row match is a *phase check*; a full transition check needs two legs (FROM-row leg, TO-row leg) or a `JOIN` on a key.
4. **The verdict rollup exists but isn't spec-addressable.** `evaluate_all` already sums PASS/FAIL — the missing step is letting a spec say "≥90% of rows PASS" as a criterion. Aggregate operators are the single highest-value addition.

## Candidate extensions (all determinism-preserving)

1. ~~**Aggregate criteria**~~ **DONE in v0.2.0** — `AVG/SUM/MIN/MAX/COUNT` implemented (`FIELD AVG(x) >= t`); `PCT(...)` still open.
2. ~~**Categorical equality**~~ **DONE in v0.3.0** — `FIELD tag == \"urgent\"`, `==`/`!=` only; compiler closed phrasings (`tagged as X`, `status must be X`) emit it directly.
3. ~~**A `NOTICE` verb**~~ **DONE in v0.2.0** — compiler emits `NOTICE <category> semantics not supported...` lines; CLI prints them.
4. ~~**Two-leg interfaces**~~ **DONE in v0.4.0** — `JOIN <key>` pairs rows 1:1 (no counterpart -> NA, >2 -> non-unique MISMATCHED); budget on entity-side TIME; dataset-level like aggregates.
6. ~~**NL compiler catch-up**~~ **DONE in v0.6.0** — windowed + aggregate phrasings compile into real specs (drafts with warn + NOTE), NOTICE retires for them.

5. ~~**Window clause**~~ **DONE in v0.5.0** — `WITHIN <duration>` + `TIME <field>` + `LIMIT <n>`; dataset-level rolling rule; NA on missing time; O(n^2) deterministic scan (batches, not fleets).

7. **PLANE — spatial module (proposed)** — lift evaluation off the per-row verdict onto a *declared* grid of subjects: express cross-subject coverage (`FIELD coverage >= 0.9` rolled over a named plane), adjacency / clearance (`no two <subject> within <radius>`), and lane map (`every <subject> has a lane`). **Bounding condition:** the plane and its edges are **declared in the spec** (edge list or bounded radius) — never computed from the data — so no implicit cross-product fan-out (the §2 two-leg manacle, refused). Deterministic: O(n`·m) over declared cells; aggregate rollup reuses the v0.2 aggregator.

8. **LINEAGE — temporal module (proposed)** — extend the two-leg interface from a single jump to an **input-carried ancestry chain**: `JOIN` a row to its predecessor up to `DEPTH n`, then fold criteria across the lineage (drift / monotone / cycle detection: `no two <subject> share an ancestor`, `field must not regress across generations`). **Bounding condition:** ancestry is **carried in the input** (each row declares its parent ref) — pure function of the row set, no runtime state, no mutation mid-eval. Deterministic: n-leg generalization of the §4 `check_pair` (1:1, NA on missing parent, non-unique -> MISMATCHED); the bounded-analysis "stateful sequences" refusal holds — the *state* is caller-carried input, not module-owned.

This is the natural capstone pair: **PLANE answers *where* (space), LINEAGE answers *when* (time)** — alongside the existing *what* (criteria/variations) and *who* (two-leg interfaces). All four stay byte-deterministic.

## Explicitly refuse (keep the boundary)

- **LLM-as-judge inside the spec** — a semantic criterion would break byte-determinism. Keep the LLM *outside* as a producer of fields ("sentiment: hostile"), never as the verdict authority.
- **Random sampling** — any `SAMPLE`/`RANDOM` clause.
- **External calls** — no I/O inside evaluation.
- **Stateful sequences** — workflows as memory, beyond the deterministic window proposed in (5). If evaluation needs state, the state belongs to the caller, given to MITER as input fields.