# MITER

**A deterministic workflow-evaluation DSL with a natural-language compiler.**

Most evaluation tools check *states*: is this field under its threshold?
MITER's claim is that workflows are sequences of connected segments, and
**the transition is where work actually fails** — an entity crossing into a
new lane must meet the receiving lane's conditions, inside a tolerance and a
time budget. MITER makes that constraint checkable instead of metaphorical.

```text
# route_feasibility.mtr  (see examples/)
EVALUATION route
SUBJECT route
INPUTS stops depot_capacity driver_hours

CRITERION depot_within_capacity
    FIELD depot_capacity <= 0.95
    SEVERITY error
    NOTE depot utilization must stay under 95%

CRITERION driver_within_hours
    FIELD driver_hours <= 14.0
    SEVERITY error

VARIATION peak_volume
    ADJUST depot_capacity SCALE 1.2
    NOTE what happens when volume spikes

INTERFACE merge_onto_expressway
    FROM collector TO expressway
    MATCH velocity TO lane_velocity
    TOLERANCE 0.15
    BUDGET 20m
    TIME merge_t

END
```

## Documentation

- [docs/positioning.md](docs/positioning.md) — the full problem framing: why the transition, why determinism, who it's for
- [docs/bounding-analysis.md](docs/bounding-analysis.md) — empirically probed boundaries: what the DSL can and cannot express, and what to add next

## Dataset-level aggregates (v0.2)

A `FIELD AVG(x) >= t` criterion is evaluated across the row set, not per row:

- `AVG(x)` `SUM(x)` `MIN(x)` `MAX(x)` over non-null values
- `COUNT(*)` or `COUNT(field)` — row count
- Empty pools evaluate to `N/A` (except `COUNT`, which is always defined)
- An error-severity aggregate failure fails the whole evaluation (exit 1)

```text
CRITERION coverage_ok
    FIELD AVG(classification_rate) >= 0.9
    SEVERITY error
```

Deterministic: same spec + same rows -> byte-identical report, aggregates included.

## Categorical equality (v0.3)

Exact string comparisons for fields that carry labels, not numbers:

```text
CRITERION is_urgent
    FIELD tag == "urgent"
    SEVERITY error
```

- `==` and `!=` only (ordering has no meaning for strings; the parser refuses `<`/`>` on quoted values)
- Missing field -> `N/A`, exactly like numeric criteria
- The compiler now emits categorical criteria directly from closed phrasings:
  `<subject> tagged/classified/labeled as <value>` and
  `status/type/category/class must be <value>` — no NOTICE needed for those forms.

## Window clauses (v0.5)

Rolling-limit semantics: a criterion may carry a time window and a burst bound.

```text
CRITERION missed_stop
    FIELD on_time >= 1
    WITHIN 30d
    TIME event_t
    LIMIT 2
    SEVERITY error
END
```

The criterion still evaluates every row. WITHIN adds a dataset-level rule:
rows where the criterion FAILs are events on the timeline; if **any** window
of the given length contains more than `limit` events (default 0, meaning no
failures permitted in any window), the rule fails -- and with error severity
it fails the whole evaluation. A row with a missing or non-numeric TIME
makes the timeline unenumerable, so the rule returns NA rather than guess.

Deterministic: stable time-sort (ties break by input order), inclusive
`[t, t + duration]` windows, O(n^2) scan by design -- batches, not fleets.
NA rows never count as events. Times are seconds by default (shared with
BUDGET durations); keep data and durations in one timebase.

## The compiler catches up (v0.6)

The deterministic NL compiler now emits real specs for the phrasings it used
to warn about:

```text
"no more than two missed deliveries in thirty days"
  -> FIELD missed_deliveries <= 0  WITHIN 30d  TIME t  LIMIT 2   (SEVERITY warn)

"average coverage must be at least 90 percent"
  -> FIELD AVG(coverage) >= 0.9

"sum of load must not exceed 1000"          -> FIELD SUM(load) <= 1000
"minimum temperature must stay above -40"   -> FIELD MIN(temperature) > -40
```

Compiled windows and aggregates are honest drafts: SEVERITY warn plus a NOTE
naming exactly what must be reviewed (the predicate polarity, a word-number
window length, an approximated month). The compiler guesses the encoding,
never the data. The NOTICE verb remains for what is still inexpressible
(rolling, consecutive, conditional, set membership).

## Two-leg interfaces (v0.4)

The ghost car with an actual exchange: an interface whose two legs are
different rows, paired by a join key.

```text
INTERFACE hub_swap
    FROM leg_a TO leg_b
    MATCH trailer_weight TO capacity
    JOIN shipment_id
    TOLERANCE 0.10
    BUDGET 15m
    TIME handoff_t
END
```

Pairing semantics (deterministic, pure function of the row set):

| join value appears | result |
|---|---|
| once | `NA` — no counterpart |
| twice | each side evaluates its own match against the other's lane field |
| thrice+ | `MISMATCHED` — non-unique join key |
| missing on a row | `NA` — missing join key |

Two-leg interfaces are dataset-level (like aggregates): `evaluate_row` alone
yields `NA` with reason `two-leg interface`, and they are not re-evaluated
under variations. Budget is measured on the entity side's `TIME` field.

## Compiler notices (v0.2)

The natural-language compiler flags structure the deterministic core cannot express
(windowed/temporal rules, conditionals, categorical checks) and emits a `NOTICE` line
into the spec instead of silently pretending. A compiled spec with a notice is a
*draft that needs a human*, and the CLI prints the notice to stderr beside the output.

## The three primitives

- **Criteria** — what "passing" means for a field: a threshold and an operator.
  `SEVERITY error` fails the evaluation; `warn` reports without failing it.
- **Variations** — what "if it changes" means: perturbations (`SCALE`, `OFFSET`,
  `SET`) applied to the data before re-evaluation. A variation that fails fails
  the evaluation — this is where edge cases earn their keep.
- **Interfaces** — the transition itself. An interface declares a `MATCH`
  between the entity's field and the receiving lane's field, a `TOLERANCE`
  (fractional deviation), and a `BUDGET` (time window) measured on a `TIME`
  field. A `FROM`/`TO` pair names the transition; the match is the constraint.

## Determinism

The engine is byte-deterministic: **the same spec + the same data produces
byte-identical output, every run.** No randomness, no environment dependence,
stable ordering throughout. That is the load-bearing property for an
evaluation tool — a verdict you can't reproduce isn't a verdict.

## Natural-language compilation

A natural-language description compiles to a spec via `miter compile` — a deterministic
core that recognises closed phrasings, plus an optional LLM backend:

```console
$ miter compile "check that driver hours stay under 14"
EVALUATION compiled_evaluation
SUBJECT subject
INPUTS driver_hours

CRITERION criterion_1
    FIELD driver_hours < 14

END
```

The compiler re-parses its own output before accepting it — nothing
unparseable ships. When the source text doesn't state a bound, the criterion
is emitted with `SEVERITY warn` and a note telling you to edit it, instead of
inventing a threshold.

## Install & run

```console
$ pip install miter            # or: uv add miter
$ miter run examples/route_feasibility.mtr --data examples/routes.json
$ miter lint examples/route_feasibility.mtr
$ miter compile "the route must respect depot capacity and driver hours"
```

## Development

```console
$ uv sync --dev
$ uv run pytest
```

License: MIT