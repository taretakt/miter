"""the evaluation DSL evaluation engine.

Fully deterministic: the same spec + the same data produces byte-identical
output every run. No random, no sets, no environment dependence. That is a
deliberately load-bearing property for an evaluation tool — verdicts must be
reproducible or they are not verdicts.

Output shape (per data row):

    {
      "row": { ... source fields ... },
      "criteria": { "id": {"status": "PASS"|"FAIL"|"NA", "value": ..., "threshold": ...} },
      "interfaces": { "id": {"status": "MATCHED"|"MISMATCHED"|"NA", ...} },
      "variations": { "variation_id": { "criteria": {...}, "interfaces": {...} } },
      "verdict": "PASS" | "FAIL"
    }
"""

from __future__ import annotations

import json
from typing import Any

from .model import Evaluation, nested_get


class MiterEngine:
    def __init__(self, evaluation: Evaluation):
        self.evaluation = evaluation

    def evaluate_row(self, row: dict[str, Any]) -> dict[str, Any]:
        base = self._evaluate_flat(row)
        variations: dict[str, Any] = {}
        for var in self.evaluation.variations:
            mutated = var.apply(row)
            variations[var.id] = self._evaluate_flat(mutated)
        return {
            "row": row,
            "criteria": base["criteria"],
            "interfaces": base["interfaces"],
            "variations": variations,
            "verdict": self._verdict(base, variations),
        }

    def _evaluate_flat(self, row: dict[str, Any]) -> dict[str, Any]:
        criteria: dict[str, Any] = {}
        for c in self.evaluation.criteria:
            if c.agg is not None:
                continue  # aggregates are dataset-level; evaluated in evaluate_all
            value = nested_get(row, c.field)
            result = c.evaluate(value)
            if result is None:
                status = "NA"
            else:
                status = "PASS" if result else "FAIL"
            criteria[c.id] = {
                "status": status,
                "value": _fmt(value),
                "threshold": _fmt(
                    c.threshold_str if c.threshold_str is not None else c.threshold
                ),
                "severity": c.severity,
            }
        interfaces: dict[str, Any] = {}
        for i in self.evaluation.interfaces:
            if i.join:
                interfaces[i.id] = {"status": "NA", "reason": "two-leg interface; evaluated in evaluate_all"}
            else:
                interfaces[i.id] = i.check(row)
        return {"criteria": criteria, "interfaces": interfaces}

    def _verdict(self, base: dict[str, Any], variations: dict[str, Any]) -> str:
        def flat_pass(flat: dict[str, Any]) -> bool:
            for c in flat["criteria"].values():
                if c["status"] == "FAIL" and c["severity"] == "error":
                    return False
            for iv in flat["interfaces"].values():
                if iv.get("status") == "MISMATCHED":
                    return False
            return True

        if not flat_pass(base):
            return "FAIL"
        for v in variations.values():
            if not flat_pass(v):
                return "FAIL"
        return "PASS"

    def evaluate_all(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        rows_out = [self.evaluate_row(r) for r in rows]
        self._resolve_two_leg(rows_out, rows)
        counts = {"PASS": 0, "FAIL": 0}
        for r in rows_out:
            counts[r["verdict"]] += 1
        # evaluate aggregates across the dataset
        aggregates = self._evaluate_aggregates(rows)
        agg_fail = any(a["status"] == "FAIL" and a["severity"] == "error" for a in aggregates)
        return {
            "spec": {
                "name": self.evaluation.name,
                "subject": self.evaluation.subject,
                "hash": self.evaluation.spec_hash(),
            },
            "summary": {"rows": len(rows_out), **counts},
            "results": rows_out,
            "aggregates": aggregates,
            "verdict": "FAIL" if agg_fail else "PASS",
        }

    def _evaluate_aggregates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for c in self.evaluation.criteria:
            if c.agg is None:
                continue
            values = [nested_get(r, c.field) if c.field != "*" else None for r in rows]
            result = c.evaluate_many(values)
            if result is None:
                status = "NA"
            else:
                status = "PASS" if result else "FAIL"
            out.append({
                "id": c.id,
                "agg": c.agg,
                "field": c.field,
                "status": status,
                "threshold": c.threshold,
                "severity": c.severity,
            })
            if c.agg == "count":
                if c.field == "*":
                    out[-1]["value"] = len(rows)
                else:
                    out[-1]["value"] = sum(1 for v in values if v is not None)
            elif c.agg in ("avg",) and status in ("PASS", "FAIL"):
                clean = [float(v) for v in values if v is not None]
                out[-1]["value"] = sum(clean) / len(clean) if clean else None
            elif c.agg == "sum" and status in ("PASS", "FAIL"):
                clean = [float(v) for v in values if v is not None]
                out[-1]["value"] = sum(clean) if clean else None
            elif c.agg in ("min", "max") and status in ("PASS", "FAIL"):
                clean = [float(v) for v in values if v is not None]
                out[-1]["value"] = (min if c.agg == "min" else max)(clean) if clean else None
        return out

    def _resolve_two_leg(self, rows_out: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
        """Resolve JOIN-ed interfaces across the dataset, then refresh verdicts.

        Two-leg interfaces are dataset-level: pairing is a pure function of the
        row set (deterministic), and each paired row sees the other side.
        Variations are NOT re-evaluated here -- they perturb row-local state.
        """
        for iface in self.evaluation.interfaces:
            if not iface.join:
                continue
            index: dict[str, list[int]] = {}
            for idx, row in enumerate(rows):
                k = nested_get(row, iface.join)
                if k is None:
                    rows_out[idx]["interfaces"][iface.id] = {"status": "NA", "reason": "missing join key", "join": None}
                    continue
                index.setdefault(str(k), []).append(idx)
            for k, idxs in index.items():
                if len(idxs) == 1:
                    rows_out[idxs[0]]["interfaces"][iface.id] = {"status": "NA", "reason": "no counterpart", "join": k}
                elif len(idxs) == 2:
                    i, j = idxs[0], idxs[1]
                    a = iface.check_pair(rows[i], rows[j])
                    a["join"] = k
                    b = iface.check_pair(rows[j], rows[i])
                    b["join"] = k
                    rows_out[i]["interfaces"][iface.id] = a
                    rows_out[j]["interfaces"][iface.id] = b
                else:
                    for idx in idxs:
                        rows_out[idx]["interfaces"][iface.id] = {"status": "MISMATCHED", "reason": f"non-unique join key ({len(idxs)} rows)", "join": k}
        for r in rows_out:
            base = {"criteria": r["criteria"], "interfaces": r["interfaces"]}
            r["verdict"] = self._verdict(base, r["variations"])

    def to_json(self, rows: list[dict[str, Any]], indent: int = 2) -> str:
        report = self.evaluate_all(rows)
        return json.dumps(report, sort_keys=True, indent=indent, ensure_ascii=False)


def _fmt(v: float | None | str) -> float | None | str:
    """Normalise a report value: None stays None, strings pass through exactly,
    numbers are rounded to 6 places. String thresholds are compared exactly,
    so they must not be mutated here."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return round(float(v), 6)