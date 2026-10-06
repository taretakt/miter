"""the evaluation DSL core model — a deterministic workflow-evaluation DSL.

The three primitives:

- **Criteria** — what "passing" means for a single field (threshold + operator).
- **Variations** — perturbations applied to the data before re-evaluation
  (edge cases, peak conditions, alternative paths).
- **Interfaces** — the ghost car: a transition between two network segments
  that must *match phase* (e.g. match lane velocity within tolerance) inside
  a time budget. This is what makes the evaluation DSL a trajectory-matching language
  rather than a static rubric.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

Operator = Literal["<", "<=", ">", ">=", "==", "!="]
Severity = Literal["error", "warn"]
AdjustOp = Literal["scale", "offset", "set"]

OPS = ("<", "<=", ">", ">=", "==", "!=")
ADJUST_OPS = ("scale", "offset", "set")
AggregateFn = str  # "avg","sum","min","max","count"
AGGREGATES = ("avg", "sum", "min", "max", "count")


@dataclass
class Criterion:
    id: str
    field: str
    op: Operator
    threshold: float
    severity: Severity = "error"
    note: str = ""
    agg: str | None = None
    threshold_str: str | None = None
    within_s: float | None = None
    time_field: str = "t"
    limit: int | None = None

    def evaluate(self, value: float | None | str) -> bool | None:
        """True = pass, False = fail, None = not applicable (missing field)."""
        if value is None:
            return None
        if self.threshold_str is not None:
            s = str(value)
            if self.op == "==":
                return s == self.threshold_str
            if self.op == "!=":
                return s != self.threshold_str
            return None
        try:
            lhs = float(value)
        except (TypeError, ValueError):
            return None
        if self.op == "<":
            return lhs < self.threshold
        if self.op == "<=":
            return lhs <= self.threshold
        if self.op == ">":
            return lhs > self.threshold
        if self.op == ">=":
            return lhs >= self.threshold
        if self.op == "==":
            return lhs == self.threshold
        if self.op == "!=":
            return lhs != self.threshold
        raise ValueError(f"unknown operator {self.op!r}")
    
    def evaluate_many(self, values: Sequence[float | None]) -> bool | None:
        """Aggregate evaluation over many rows. None = not applicable (empty pool)."""
        if self.agg is None:
            return None
        if self.agg == "count":
            if self.field == "*":
                return self.evaluate(float(len(values)))
            present = [v for v in values if v is not None]
            return self.evaluate(float(len(present)))
        clean = [v for v in values if v is not None]
        if not clean:
            return None
        try:
            clean_f = [float(v) for v in clean]
        except (TypeError, ValueError):
            return None
        if self.agg == "avg":
            return self.evaluate(sum(clean_f) / len(clean_f))
        if self.agg == "sum":
            return self.evaluate(sum(clean_f))
        if self.agg == "min":
            return self.evaluate(min(clean_f))
        if self.agg == "max":
            return self.evaluate(max(clean_f))
        return None


@dataclass
class Adjustment:
    op: AdjustOp
    field: str
    value: float

    def apply(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        v = self.get(row)
        if v is None:
            return out
        out[self.field] = v
        return out

    def get(self, row: dict[str, Any]) -> float | None:
        v = row.get(self.field)
        if v is None:
            return None
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if self.op == "scale":
            return v * self.value
        if self.op == "offset":
            return v + self.value
        if self.op == "set":
            return self.value
        raise ValueError(f"unknown adjustment op {self.op!r}")


@dataclass
class Variation:
    id: str
    adjustments: list[Adjustment] = field(default_factory=list)
    note: str = ""

    def apply(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        for adj in self.adjustments:
            out = adj.apply(out)
        return out


@dataclass
class Interface:
    """A ghost car: a lane transition that must match phase.

    `match_field` is the value carried by the entity (e.g. its velocity at
    the merge point); `lane_field` is the receiving lane's value. The match
    passes when the relative deviation stays within `tolerance`, and the
    transition completes within `budget_s` seconds (measured by `time_field`,
    defaulting to `t`).
    """

    id: str
    lane_from: str
    lane_to: str
    match_field: str
    lane_field: str
    tolerance: float
    budget_s: float | None = None
    time_field: str = "t"
    note: str = ""
    join: str | None = None  # two-leg: pair rows by equal value of this field

    def check(self, row: dict[str, Any]) -> dict[str, Any]:
        """Within-row phase match (single subject)."""
        return self.check_pair(row, row)

    def check_pair(self, entity: dict[str, Any], lane: dict[str, Any]) -> dict[str, Any]:
        """Two-leg phase match: entity value vs receiving lane value.
        Used for both within-row (entity is lane) and JOIN-ed row pairs.
        """
        a = self._num(entity, self.match_field)
        b = self._num(lane, self.lane_field)
        if a is None or b is None:
            return {"status": "NA", "reason": "missing match or lane field"}
        if b == 0:
            dev = abs(a)
            ok = dev <= self.tolerance
        else:
            dev = abs(a - b) / abs(b)
            ok = dev <= self.tolerance
        result: dict[str, Any] = {
            "status": "MATCHED" if ok else "MISMATCHED",
            "deviation": round(dev, 6),
            "tolerance": self.tolerance,
        }
        if self.budget_s is not None:
            t = self._num(entity, self.time_field)
            if t is None:
                result["budget"] = "NA"
            else:
                result["budget"] = "OK" if t <= self.budget_s else "OVER"
                if result["budget"] == "OVER":
                    result["status"] = "MISMATCHED"
        return result
    @staticmethod
    def _num(row: dict[str, Any], key: str) -> float | None:
        v = row.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


@dataclass
class Evaluation:
    name: str
    subject: str = ""
    inputs: list[str] = field(default_factory=list)
    criteria: list[Criterion] = field(default_factory=list)
    variations: list[Variation] = field(default_factory=list)
    interfaces: list[Interface] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)

    def spec_hash(self) -> str:
        """Deterministic hash of the spec source (for audit / linking)."""
        payload = json.dumps(
            {
                "name": self.name,
                "subject": self.subject,
                "inputs": self.inputs,
                "criteria": [
                    (c.id, c.field, c.op, c.threshold, c.severity, c.agg, c.threshold_str, c.within_s, c.time_field, c.limit) for c in self.criteria
                ],
                "notices": self.notices,
                "variations": [
                    (v.id, [(a.op, a.field, a.value) for a in v.adjustments])
                    for v in self.variations
                ],
                "interfaces": [
                    (
                        i.id,
                        i.lane_from,
                        i.lane_to,
                        i.match_field,
                        i.lane_field,
                        i.tolerance,
                        i.budget_s,
                        i.time_field,
                        i.join,
                    )
                    for i in self.interfaces
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def nested_get(row: dict[str, Any], path: str) -> float | None:
    """Access dotted paths like `trip.duration`; returns None when missing. Returns the raw value (no float coercion)."""
    cur: Any = row
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    # return the RAW value; numeric coercions happen in criteria/aggregates,
    # so string criteria can see string values
    return cur