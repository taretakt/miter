# MITER — what this is, and why it exists

*Positioning document. Companion to the README; the README says how it works, this says what it means.*

---

## One sentence

MITER is a deterministic, natural-language-compilable DSL for evaluating **workflows at their transitions** — where the entity crossing a boundary must match the receiving lane's conditions inside a tolerance and a time budget.

## Elevator version

Most evaluation tools check *states*: is this field under its threshold? MITER's claim is that work doesn't fail inside a segment — **it fails crossing into the next one.** The merge, the handoff, the hand-over between systems or shifts: that's where the exception lives. MITER makes the transition a first-class, checkable object instead of a phrase in a meeting.

## The problem

Three failures in how evaluation is done today:

1. **State-checking misses the handoff.** A dashboard watches per-field thresholds. The moment two segments connect — a driver hands a load to a plant, an agent hands a case to a workflow, a cheque batch moves from truck to site — the state of each side can be fine and the *connection* still break.[^1]
2. **Rubrics are prose.** Acceptance criteria live in documents and drift from the code that enforces them. Nothing parses a paragraph of eligibility rules.
3. **Verdicts aren't reproducible.** LLM-as-judge is the fashion. It's also non-deterministic: same input, different verdicts, no audit trail. A verdict you can't reproduce isn't a verdict — it's an opinion with a timestamp.

MITER is aimed at all three. Criteria for the fields, variations for the edge cases, **interfaces for the transitions** — and a byte-deterministic engine so every verdict has a fingerprint anyone can re-run.

[^1]: This is not a metaphor. The origin of MITER is route feasibility: a route is a trajectory through a network, and every network boundary is an interface that must be matched, not just crossed. The canonical example is the expressway merge — a collector road entity entering the expressway lane must match lane velocity within tolerance and inside a time budget. Operations people call this the ghost car: an entity in transition that must match phase with the lane it's joining.

## The thesis

> **The transition is where work actually fails — an entity entering a new segment must match the receiving lane's conditions, within tolerance and time budget.**
> **And: if a verdict can't be interrogated by the operator who must act on it, it won't be adopted — so explainability is a deployment prerequisite, not a feature.**

The second sentence is borrowed from a harder lesson: a routing solution with 45 parameters no one could explain was unsellable to the people who'd have to trust it — regardless of how optimal it was. MITER is the answer to that failure mode: **a spec is a human-readable, operator-interrogatable object** (what passes, what's a warning, what edge case is being stress-tested, what the handoff requires), and the engine is deterministic so the operator can re-run the exact verdict.

## How it works (what actually exists)

Three primitives, defined in `miter/model.py` and parsed by `miter/parser.py`:

- **Criterion** — "what passing means" for a field: field, operator, threshold, severity (`error` fails the evaluation; `warn` reports without failing). When the field is missing, the verdict is `None` — not applicable is not a failure, which is itself a decision.
- **Variation** — "what *if it changes* means": perturbations (`SCALE`, `OFFSET`, `SET`) applied to the data before re-evaluation. A failing variation fails the evaluation. This is how edge cases earn their keep — the peak-volume route isn't a different evaluation, it's the same spec under a perturbation.
- **Interface** — the transition itself: `FROM`/`TO` names the boundary, `MATCH a TO b` names the fields that must align, `TOLERANCE` is the fractional deviation, `BUDGET` is the time window measured on a `TIME` field. The match is the constraint.

Then `miter compile` takes a natural-language sentence and produces a spec — with a rule that matters: **the compiler re-parses its own output before accepting it, and when the source doesn't state a bound, it emits `SEVERITY warn` plus a note instead of inventing a threshold.** The tool refuses to fabricate. (Yes, that rule is deliberate.)

Verified behaviour, 2026-10-05:

```console
$ miter lint examples/route_feasibility.mtr
OK route_feasibility: 3 criteria, 2 variations, 2 interfaces (e22edbfd42629e04)

$ miter run examples/route_feasibility.mtr --data examples/routes.json
# R-104: depot_capacity 0.75 ≤ 0.95 PASS · driver_hours 11.5 ≤ 14 PASS
#   variations: driver_exhaustion (+1h → 12.5) still PASS
#   interfaces: merge deviation 0.020 ≤ 0.10 MATCHED · offramp deviation 0.225 ≤ 0.25 MATCHED
# R-117, R-121 fail — the engine exits non-zero and the report says which clause, on which row, under which variation.

$ miter compile "check that driver hours stay under 14 on the expressway segment"
EVALUATION compiled_evaluation ...
CRITERION criterion_1
    FIELD driver_hours < 14
END
```

30 tests, byte-deterministic output, stable ordering, no randomness, no environment dependence.

## Why it's different

| Approach | What it checks | What it can't see |
|---|---|---|
| Checklist / rubric doc | Fields, by a human re-read | Drift between doc and reality; transitions |
| Monitoring / SLO dashboards | States over time | The moment of crossing; one-off payloads |
| Rule engine / BPMN | Prescribed flows | Anything the model didn't anticipate |
| LLM-as-judge | Vibes, calibrated by prompt | A reproducible verdict (by construction) |
| **MITER** | **States, under variations, at transitions** | Little — that's the point |

The load-bearing property is determinism, because it's what makes the other three primitives mean anything. Same spec + same data → byte-identical verdict, every run, hash-pinned at lint time. An evaluation tool that can't do this isn't an evaluation tool.

## Where it came from

The domain is logistics, and it shows. Depot capacity, driver hours, the expressway merge — these are the *receiving lane's conditions* from eleven years of transportation network work. The interface primitive is the same structure Ross his whole career was built around: the handoff — truck to plant, plant to site, dispatch to driver, one network segment to the next. In his own vocabulary, **resolutions are cheap and transitions are steel.** Most evaluation tools formalize the cheap part. MITER formalizes the part that costs.

## The broader claim

MITER is the constraint discipline made executable: find what actually gates the outcome — for route feasibility it's the merge, not the depot; for evaluation it's the transition, not the state — and satisfy it with the cheapest formalization that works. The discipline has shown up all over his record (container geometry on a fry cart, beaver-tail channel access, capacity modelling behind a $500M decision, a contingency process designed to run hands-off). MITER is the version of it that ships as code with a license.

## Roadmap (candidate)

- **Golden datasets & regression suites** — a `tests/golden/` corpus of spec+data+verdict triples; `miter check` as a CI gate.
- **LLM-judge adapter** — MITER as the deterministic verdict substrate under an LLM judge: judge for the fuzzy cases, MITER for the checkable ones, LLM never the sole authority.
- **Replay** — feed prior verdicts + new spec, get the drift report (spec versioning in git is already natural).
- **PyPI packaging** (`pip install miter`), a `--junit`/`--github-actions` output, and more operators (string/match/window).
- A `SUBMIT`-style block to version interfaces, so a changed tolerance is an intentional, reviewable diff.

## Positioning notes (how to talk about it)

- **It is not a workflow engine.** MITER doesn't run workflows; it evaluates them. The reframe matters in demos.
- **It is not an LLM evaluation framework** in the RAGAS sense — it's narrower and more honest: a substrate any such framework can sit on.
- **The ghost-car framing** (internal, evocative) — an entity in transition must match phase with the lane it's joining. Use it to explain why interfaces exist; it renders instantly to an operations audience.
- The strongest demo is the route example: three rows, one spec, variations firing, interfaces failing, a hash on the verdict. No slides needed.