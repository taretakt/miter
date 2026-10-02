"""MITER DSL parser — turns `.mtr` source text into an Evaluation model.

The language is deliberately small and line-oriented. Every block is opened
by a keyword and closed by indentation (or a matching END keyword for the
top-level EVALUATION block). Comments start with `#`.

Example:

    EVALUATION route_feasibility
    # the vehicle, its load, and its driver
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
        TIME field t
    END
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import (
    ADJUST_OPS,
    Criterion,
    Evaluation,
    Interface,
    Operator,
    OPS,
    Severity,
    Variation,
)

BLOCK_KEYWORDS = {"CRITERION", "VARIATION", "INTERFACE"}
TOP_LEVEL = {"EVALUATION", "SUBJECT", "INPUTS", "CRITERION", "VARIATION", "INTERFACE", "END"}


class MiterError(Exception):
    pass


def _parse_duration(text: str) -> float:
    """Parse durations like `20m`, `1.5h`, `900s`, or a bare number of seconds."""
    t = text.strip().lower()
    if not t:
        raise MiterError("empty duration")
    if t.endswith("s"):
        return float(t[:-1])
    if t.endswith("m"):
        return float(t[:-1]) * 60
    if t.endswith("h"):
        return float(t[:-1]) * 3600
    if t.endswith("d"):
        return float(t[:-1]) * 86400
    return float(t)


def _parse_number(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise MiterError(f"expected a number, got {text!r}")


@dataclass
class _Block:
    kind: str
    id: str
    lines: list[tuple[int, str]]


def _split_lines(source: str) -> list[tuple[int, str]]:
    """Return (lineno, content) pairs with comments stripped and trailing
    whitespace removed, but **leading indentation preserved** — indentation
    is how the parser knows it is inside a block."""
    out = []
    for i, raw in enumerate(source.splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip()
        if line.strip():
            out.append((i, line))
    return out


def _parse_block_header(line: str, lineno: int) -> _Block:
    parts = line.split(None, 1)
    kind = parts[0]
    if kind not in BLOCK_KEYWORDS:
        raise MiterError(f"line {lineno}: expected CRITERION/VARIATION/INTERFACE, got {kind!r}")
    if len(parts) < 2 or not parts[1]:
        raise MiterError(f"line {lineno}: {kind} block needs an id")
    return _Block(kind=kind, id=parts[1].strip(), lines=[])


def _require_nonindented(line: str, lineno: int) -> None:
    # Caller already strips; we enforce that block bodies use indentation.
    pass


def parse(source: str) -> Evaluation:
    lines = _split_lines(source)
    if not lines:
        raise MiterError("empty spec")

    name: str | None = None
    subject = ""
    inputs: list[str] = []
    criteria: list[Criterion] = []
    variations: list[Variation] = []
    interfaces: list[Interface] = []
    blocks: list[_Block] = []
    cur: _Block | None = None
    in_block = False
    ended = False

    for lineno, line in lines:
        indent = len(line) - len(line.lstrip())
        content = line.strip()

        if not in_block:
            if indent != 0:
                raise MiterError(f"line {lineno}: unexpected indentation outside a block")
            parts = content.split()
            kw = parts[0].upper()
            if kw == "EVALUATION":
                if len(parts) < 2:
                    raise MiterError(f"line {lineno}: EVALUATION needs a name")
                name = parts[1]
            elif kw == "SUBJECT":
                subject = " ".join(parts[1:])
            elif kw == "INPUTS":
                inputs = parts[1:]
            elif kw in BLOCK_KEYWORDS:
                cur = _parse_block_header(content, lineno)
                blocks.append(cur)
                in_block = True
            elif kw == "END":
                ended = True
                break
            else:
                raise MiterError(f"line {lineno}: unknown statement {kw!r}")
        else:
            assert cur is not None
            cur_id = cur.id
            if indent == 0:
                # block body ended by a new top-level statement
                in_block = False
                cur = None
                if content.split()[0].upper() in BLOCK_KEYWORDS:
                    cur = _parse_block_header(content, lineno)
                    blocks.append(cur)
                    in_block = True
                else:
                    # re-process this line at top level
                    parts = content.split()
                    kw = parts[0].upper()
                    if kw == "END":
                        ended = True
                        break
                    if kw == "SUBJECT":
                        subject = " ".join(parts[1:])
                    elif kw == "INPUTS":
                        inputs = parts[1:]
                    else:
                        raise MiterError(
                            f"line {lineno}: block {cur_id!r} closed by unexpected {kw!r}"
                        )
            else:
                cur.lines.append((lineno, content))

    if name is None:
        raise MiterError("spec has no EVALUATION name")
    if not ended:
        raise MiterError("spec never reached END")

    # ---- build blocks ----
    for blk in blocks:
        if blk.kind == "CRITERION":
            criteria.append(_build_criterion(blk))
        elif blk.kind == "VARIATION":
            variations.append(_build_variation(blk))
        elif blk.kind == "INTERFACE":
            interfaces.append(_build_interface(blk))

    return Evaluation(
        name=name,
        subject=subject,
        inputs=inputs,
        criteria=criteria,
        variations=variations,
        interfaces=interfaces,
    )


def _build_criterion(blk: _Block) -> Criterion:
    field: str | None = None
    op: Operator | None = None
    threshold: float | None = None
    severity: Severity = "error"
    note = ""
    for lineno, content in blk.lines:
        parts = content.split()
        kw = parts[0]
        if kw.upper() == "FIELD":
            if len(parts) < 4 or parts[2] not in OPS:
                raise MiterError(
                    f"line {lineno}: FIELD needs `path <op> <value>` with op in {OPS}"
                )
            field, op = parts[1], parts[2]
            threshold = _parse_number(parts[3])
        elif kw.upper() == "SEVERITY":
            if len(parts) < 2 or parts[1].lower() not in ("error", "warn"):
                raise MiterError(f"line {lineno}: SEVERITY must be error or warn")
            severity = parts[1].lower()  # type: ignore[assignment]
        elif kw.upper() == "NOTE":
            note = " ".join(parts[1:])
        else:
            raise MiterError(f"line {lineno}: unknown CRITERION directive {kw!r}")
    if field is None or op is None or threshold is None:
        raise MiterError(f"CRITERION {blk.id!r} is missing a FIELD line")
    return Criterion(id=blk.id, field=field, op=op, threshold=threshold, severity=severity, note=note)


def _build_variation(blk: _Block) -> Variation:
    from .model import Adjustment

    adjustments: list[Adjustment] = []
    note = ""
    for lineno, content in blk.lines:
        parts = content.split()
        kw = parts[0]
        if kw.upper() == "ADJUST":
            op = parts[2].lower() if len(parts) >= 3 else ""
            if len(parts) < 4 or op not in ADJUST_OPS:
                raise MiterError(f"line {lineno}: ADJUST needs `path <scale|offset|set> <value>`")
            adjustments.append(
                Adjustment(op=op, field=parts[1], value=_parse_number(parts[3]))
            )
        elif kw.upper() == "NOTE":
            note = " ".join(parts[1:])
        else:
            raise MiterError(f"line {lineno}: unknown VARIATION directive {kw!r}")
    if not adjustments:
        raise MiterError(f"VARIATION {blk.id!r} has no ADJUST line")
    return Variation(id=blk.id, adjustments=adjustments, note=note)


def _build_interface(blk: _Block) -> Interface:
    lane_from = lane_to = ""
    match_field = lane_field = ""
    tolerance: float | None = None
    budget_s: float | None = None
    time_field = "t"
    note = ""
    for lineno, content in blk.lines:
        parts = content.split()
        kw = parts[0]
        if kw.upper() == "FROM":
            if len(parts) < 3 or parts[2].upper() != "TO":
                raise MiterError(f"line {lineno}: FROM needs `FROM <lane> TO <lane>`")
            lane_from, lane_to = parts[1], parts[3]
        elif kw.upper() == "MATCH":
            if len(parts) < 4 or parts[2].upper() != "TO":
                raise MiterError(f"line {lineno}: MATCH needs `MATCH <field> TO <field>`")
            match_field, lane_field = parts[1], parts[3]
        elif kw.upper() == "TOLERANCE":
            tolerance = _parse_number(parts[1])
        elif kw.upper() == "BUDGET":
            budget_s = _parse_duration(parts[1])
        elif kw.upper() == "TIME":
            time_field = parts[1]
        elif kw.upper() == "NOTE":
            note = " ".join(parts[1:])
        else:
            raise MiterError(f"line {lineno}: unknown INTERFACE directive {kw!r}")
    if not lane_from or not lane_to:
        raise MiterError(f"INTERFACE {blk.id!r} is missing a FROM/TO line")
    if not match_field or not lane_field:
        raise MiterError(f"INTERFACE {blk.id!r} is missing a MATCH line")
    if tolerance is None:
        raise MiterError(f"INTERFACE {blk.id!r} is missing a TOLERANCE line")
    return Interface(
        id=blk.id,
        lane_from=lane_from,
        lane_to=lane_to,
        match_field=match_field,
        lane_field=lane_field,
        tolerance=tolerance,
        budget_s=budget_s,
        time_field=time_field,
        note=note,
    )