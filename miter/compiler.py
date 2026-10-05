"""the compiler — natural language to the evaluation DSL compiler.

Two layers:

1. **Deterministic core** (always available, zero dependencies). Recognises a
   closed set of constraint phrasings and maps them onto the evaluation DSL directives:

       "check that the route respects depot capacity and driver hours"
         -> SUBJECT route; CRITERION depot_capacity; CRITERION driver_hours

       "driver hours must stay under 14"
         -> CRITERION driver_hours <= 14

       "depot utilization must not exceed 95%"
         -> CRITERION depot_utilization <= 0.95  (percent collapsed)

       "the truck must match the lane velocity within 10%"
         -> INTERFACE ... MATCH velocity TO lane_velocity TOLERANCE 0.1

2. **LLM backend** (optional). When `OPENROUTER_API_KEY` is set, free-form
   sentences are compiled by a model with a constrained prompt, then the
   output is re-parsed by the the evaluation DSL parser — generated specs are only
   accepted if they actually parse. The compiler never verifies a spec that
   fails to parse.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from miter.parser import MiterError, parse

_UNIT_MAP: dict[str, float] = {
    "hours": 1.0, "hour": 1.0,
    "minutes": 1 / 60, "minute": 1 / 60, "min": 1 / 60,
    "seconds": 1 / 3600, "second": 1 / 3600, "sec": 1 / 3600,
    "km/h": 1.0, "kph": 1.0, "kmh": 1.0,
    "%": 0.01, "percent": 0.01,
    "kg": 1.0, "kilograms": 1.0,
    "tons": 1.0, "tonnes": 1.0,
}

_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(?:hours?|minutes?|min|seconds?|sec|km/h|kph|kmh|%|percent|kg|kilograms|tons|tonnes)?"

# (pattern, operator) — matched against the full lowercased text
_THRESHOLD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"(?:must not exceed|not exceed|no more than|at most)\s+{_NUM}\s*({_UNIT})", re.I), "<="),
    (re.compile(rf"under\s+{_NUM}\s*({_UNIT})", re.I), "<"),
    (re.compile(rf"below\s+{_NUM}\s*({_UNIT})", re.I), "<"),
    (re.compile(rf"less than\s+{_NUM}\s*({_UNIT})", re.I), "<"),
    (re.compile(rf"at least\s+{_NUM}\s*({_UNIT})", re.I), ">="),
    (re.compile(rf"minimum of\s+{_NUM}\s*({_UNIT})", re.I), ">="),
    (re.compile(rf"more than\s+{_NUM}\s*({_UNIT})", re.I), ">"),
    (re.compile(rf"over\s+{_NUM}\s*({_UNIT})", re.I), ">"),
    (re.compile(rf"exactly\s+{_NUM}\s*({_UNIT})", re.I), "=="),
]

# clause splitters — "A and B", "A as well as B", "A, B"
_CLAUSE_SPLIT = re.compile(r"\s+(?:and|as well as)\s+|,\s+")

_WORD = re.compile(r"[^a-z0-9]+")

# Patterns for detecting structure the deterministic core cannot express
_LOST_STRUCTURE: list[tuple[str, str]] = [
    ("windowed/temporal", r"(?:no more than|at most|at least|fewer than) [a-z0-9]+ (?:[a-z]+ ){0,4}?(?:in|within|over) (?:[a-z0-9]+ )?(?:days?|weeks?|months?|years?)|(?:per|in|within|over|every) (?:[a-z0-9]+ )?(?:days?|weeks?|months?|years?)|rolling|window(?:ed)?|consecutive"),
    ("conditional", r"(?:^| |,)(?:if|unless|when(?:ever)?|provided(?: that)?|then)(?=(?: |,|$))"),
    ("categorical/string", r"one of|in (?:the )?set|list of allowed|allowed values|any of|equals orders? of"),
]

@dataclass
class CompileResult:
    spec_text: str
    source: str  # "deterministic" | "llm"
    notes: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        if not self.spec_text:
            return False
        try:
            parse(self.spec_text)
            return True
        except MiterError:
            return False


@dataclass
class _CriterionSpec:
    field: str
    op: str | None = None  # None = no bound stated in source text
    value: float | None = None
    value_str: str | None = None  # categorical: exact string match


def _snake(s: str) -> str:
    """camelCase / space-separated -> snake_case (the the evaluation DSL field convention)."""
    parts = [p for p in _WORD.split(s.lower()) if p]
    if not parts:
        return "value"
    return "_".join(parts)


def _clean(s: str) -> str:
    return re.sub(r"[\"'`\u2019\u2018]", "", s.lower().strip())


def _scale(value_text: str, num: float) -> float:
    unit = _UNIT_MAP.get(value_text.lower().rstrip("."), 1.0)
    return num * unit


def _extract_subject(text: str) -> str:
    m = re.search(
        r"(?:check|validate|verify|test)(?: that)? (?:the |a |an )?"
        r"([a-z][a-z ]*?)(?:\s+(?:respects|satisfies|meets|obeys|has|must|uses|is))",
        text,
    )
    return (m.group(1).strip() if m else "subject")



_CATEGORICAL_PATTERNS = (
    re.compile(r"(?:tagged|classified|labeled|labelled) as (?:a |an )?(?P<val>[a-z][a-z0-9 _]*)", re.I),
    re.compile(r"(?:status|type|category|class) must be (?:a |an )?(?P<val>[a-z][a-z0-9 _]*)", re.I),
)


def _extract_categorical(text: str) -> list[tuple[str, str]]:
    # closed phrasings that become exact string matches:
    #   '<x> tagged/classified/labeled/labelled as <v>'  and  'status/type/category/class must be <v>'
    out: list[tuple[str, str]] = []
    for m in _CATEGORICAL_PATTERNS[0].finditer(text):
        prefix = _snake(_field_from_clause(text[: m.start()])) or "category"
        val = m.group("val").split()[0]
        out.append((prefix, val))
    for m in _CATEGORICAL_PATTERNS[1].finditer(text):
        out.append(("status", m.group("val").split()[0]))

    seen = set()
    final = []
    for pair in out:
        if pair not in seen:
            seen.add(pair)
            final.append(pair)
    return final

_VERB_TAIL_WORDS = (
    r"must|should|shall|needs?|need|has|have|is|are|was|were|be|been|"
    r"stays?|remain(?:ing|s)?|keeps?|kept|hold(?:s|ing)?|"
    r"respects|satisfies|meets|obeys|uses|stay|remain|keep|hold|"
    r"under|within|to|the|a|an|and|with|of"
)
_FIELD_VERB_TAIL = re.compile(rf"\s+(?:{_VERB_TAIL_WORDS})+\s*$", re.I)


def _field_from_clause(clause: str) -> str:
    """Extract a field name from one clause.

    Strategy: cut everything from the start of the first threshold match (the
    bound phrase ends the field), then normalise the remainder:
      - "route respects depot capacity"  -> keep the OBJECT  ("depot capacity")
      - "driver hours stay under 14"     -> cut at the bound, drop "stay"
      - "the batch size must be exactly 32" -> drop leading article + modals
    """
    c = _clean(clause)
    cut = len(c)
    for pat, _op in _THRESHOLD_PATTERNS:
        m = pat.search(c)
        if m and m.start() < cut:
            cut = m.start()
    prefix = c[:cut]
    prefix = re.sub(r"^(?:check|validate|verify|test)(?: that)?(?: the| a| an)?\s+", "", prefix)
    prefix = re.sub(r"^(?:the|a|an)\s+", "", prefix)
    # subject-verb-object: "route respects depot capacity" -> the object
    m_obj = re.search(
        r"^[a-z_ ]+?\s+(?:respects|satisfies|meets|obeys|has|uses|is)\s+(.+)$",
        prefix,
    )
    if m_obj:
        prefix = m_obj.group(1)
    else:
        # cut at any modal/verb that bridges to a bound already removed
        prefix = re.sub(
            r"\s+(?:must|should|shall|needs?|need|has|have|is|are|be|stays?|remains?|"
            r"respects|satisfies|meets|obeys|uses|stay|remain|keep|holds?)\b.*$",
            "", prefix,
        )
    prefix = _FIELD_VERB_TAIL.sub("", prefix)
    prefix = prefix.strip(" ,")
    return prefix


def _dedupe(criteria: list[_CriterionSpec]) -> list[_CriterionSpec]:
    out: dict[str, _CriterionSpec] = {}
    for c in criteria:
        if c.field in out:
            prev = out[c.field]
            if c.op is not None and c.value is not None:
                if prev.op is None:  # bounded wins over unbounded
                    out[c.field] = c
                elif prev.value is not None:
                    # keep the tightest bound toward failure for the same op
                    out[c.field] = min((prev, c), key=lambda x: abs(x.value or 0))
        else:
            out[c.field] = c
    return list(out.values())


def compile_text(text: str) -> CompileResult:
    """Compile a natural-language sentence into a the evaluation DSL spec (deterministic core)."""
    t = _clean(text)
    subject = _extract_subject(text)
    notes: list[str] = []

    # 1. thresholds anywhere in the text
    bounds: list[tuple[str, str, float]] = []  # (field, op, scaled value)
    for pat, op in _THRESHOLD_PATTERNS:
        for m in pat.finditer(t):
            value_text = m.group(2) if m.lastindex and m.lastindex >= 2 else (m.group(1) if len(m.groups()) == 1 else "")
            num = float(m.group(1))
            scaled = _scale(value_text, num)
            prefix = _field_from_clause(t[: m.start()]) or "value"
            bounds.append((_snake(prefix), op, scaled))

    # 2. criteria: clause-split the sentence, drop verbs and bound phrases
    _criteria: list[_CriterionSpec] = []
    for part in _CLAUSE_SPLIT.split(t):
        if any(re.search(p, _clean(part)) for p in _CATEGORICAL_PATTERNS):
            continue
        name = _snake(_field_from_clause(part))
        if name and re.fullmatch(r"[a-z_]+", name):
            _criteria.append(_CriterionSpec(field=name))

    # 3. merge bounds into criteria (bounded entries win/are filled)
    criteria_by_field: dict[str, _CriterionSpec] = {c.field: c for c in _criteria}
    for field, op, value in bounds:
        c = criteria_by_field.get(field)
        if c is None:
            criteria_by_field[field] = _CriterionSpec(field=field, op=op, value=value)
        else:
            criteria_by_field[field] = _CriterionSpec(field=field, op=op, value=value)
    # categorical exact-match criteria from closed phrasings (last wins by field)
    for _cfd, _cval in _extract_categorical(text):
        criteria_by_field[_cfd] = _CriterionSpec(field=_cfd, op="==", value_str=_cval)
    criteria = _dedupe(list(criteria_by_field.values()))
    if not criteria:
        criteria = [_CriterionSpec(field="value")]

    # 4. interfaces (ghost car)
    interfaces: list[tuple[str, str, str, float]] = []
    m = re.search(
        rf"match(?:es|ing)?\s+(?P<f>[a-z_ ]+?)\s+to\s+(?:the\s+)?(?P<l>[a-z_ ]+?)\s+"
        rf"(?:lane\s+)?within\s+({_NUM})(?:%| percent)?",
        text,
        re.I,
    )
    if m:
        tol = float(m.group(3))
        if tol > 1.0:
            tol = tol / 100.0
        interfaces.append(("iface_1", _snake(m.group("f")), _snake(m.group("l")), round(tol, 4)))
    else:
        # "match the lane velocity within 10%" — no target lane named; the
        # lane is implicit in the phrase ("lane velocity" -> match velocity
        # to lane_velocity). This is the ghost-car phrasing proper.
        m2 = re.search(
            rf"match(?:es|ing)?\s+(?:the\s+)?(?P<f>[a-z_ ]+?)\s+"
            rf"(?:with\s+)?within\s+({_NUM})(?:%| percent)?",
            text,
            re.I,
        )
        if m2:
            f = _snake(m2.group("f"))
            tol = float(m2.group(2))
            if tol > 1.0:
                tol = tol / 100.0
            if f.startswith("lane"):
                # "lane velocity" -> entity field "velocity", lane field "lane_velocity"
                interfaces.append(("iface_1", "velocity", "lane_velocity", round(tol, 4)))
            else:
                interfaces.append(("iface_1", f, f"lane_{f}", round(tol, 4)))
        else:
            m3 = re.search(r"(?:match|merge|sync)(?: the)? (?:speed|velocity).*?(?P<l>[a-z_ ]+?)(?: lane)?", text, re.I)
            if m3:
                interfaces.append(("iface_1", "velocity", _snake(m3.group("l")), 0.1))

    # detect structure the core cannot express -> NOTICE lines in the spec
    for category, pat_str in _LOST_STRUCTURE:
        if re.search(pat_str, text, re.I):
            notice = category + " semantics not supported in the deterministic core - compiled as a plain field check"
            notes.append(notice)
    spec = _render(subject, [c.field for c in criteria], criteria, interfaces, notices=notes)
    return CompileResult(spec_text=spec, source="deterministic", notes=notes)


def _render(
    subject: str,
    fields: list[str],
    criteria: list[_CriterionSpec],
    interfaces: list[tuple[str, str, str, float]],
    notices: list[str] | None = None,
) -> str:
    lines = [
        "EVALUATION compiled_evaluation",
        f"SUBJECT {subject}",
        "INPUTS " + " ".join(sorted(set(fields))),
    ]
    for idx, c in enumerate(criteria):
        lines.append(f"\nCRITERION criterion_{idx + 1}")
        if c.value_str is not None:
            lines.append(f'    FIELD {c.field} == "{c.value_str}"')
        elif c.op is not None and c.value is not None:
            lines.append(f"    FIELD {c.field} {c.op} {_fmt(c.value)}")
        else:
            # no bound stated in the source text: emit warn severity + note
            lines.append(f"    FIELD {c.field} <= 0.0")
            lines.append("    SEVERITY warn")
            lines.append(f"    NOTE threshold not stated in source text; edit this bound")
    for iid, mf, lf, tol in interfaces:
        lines.append(f"\nINTERFACE {iid}")
        lines.append(f"    FROM {subject} TO {lf}")
        lines.append(f"    MATCH {mf} TO {lf}")
        lines.append(f"    TOLERANCE {tol}")
    for n in (notices or []):
        lines.append(f"NOTICE {n}")
    lines.append("\nEND")
    return "\n".join(lines)


def _fmt(v: float) -> str:
    return f"{v:g}"


def compile_file(path: str) -> CompileResult:
    return compile_text(open(path, encoding="utf-8").read())


def compile_with_llm(text: str, model: str = "openai/gpt-4o-mini") -> CompileResult:
    """Compile free-form text via OpenRouter; re-parse output before trusting it."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        result = compile_text(text)
        result.notes.append("no OPENROUTER_API_KEY; fell back to deterministic core")
        return result

    system = (
        "You compile natural-language evaluation criteria into the the evaluation DSL DSL. "
        "Emit ONLY the spec text. The grammar is:\n"
        "EVALUATION <name>\nSUBJECT <subject>\nINPUTS <fields...>\n"
        "CRITERION <id>\n    FIELD <path> <op> <number>    # op in <= >= < > == !=\n"
        "    SEVERITY error|warn\n"
        "INTERFACE <id>\n    FROM <lane> TO <lane>\n    MATCH <field> TO <field>\n"
        "    TOLERANCE <fraction>\n    BUDGET <duration>\nEND\n"
        "Never invent thresholds: if the text gives no bound, use SEVERITY warn "
        "and a NOTE saying the threshold must be edited in. Percent means /100."
    )
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
        }
    ).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
        spec_text = payload["choices"][0]["message"]["content"].strip()
        if spec_text.startswith("```"):
            spec_text = spec_text.split("```")[1].lstrip()
            # tolerate a stale DSL-directive keyword from an LLM reply
            for kw in ("weave", "miter"):
                if spec_text.startswith(kw):
                    spec_text = spec_text[len(kw):].strip()
                    break
        try:
            parse(spec_text)
            return CompileResult(spec_text=spec_text, source="llm")
        except MiterError as e:
            return CompileResult(spec_text="", source="llm", notes=[f"LLM output failed to parse: {e}"])
    except Exception as e:
        return CompileResult(spec_text="", source="llm", notes=[f"LLM unavailable: {e}"])


def compile_text_auto(text: str) -> CompileResult:
    """Deterministic core, upgraded to the LLM only when the core detects
    structure it cannot express (rare). Default: deterministic."""
    return compile_text(text)