"""MITER command-line interface.

    miter run spec.mtr --data rows.json
    miter run spec.mtr --data rows.jsonl --out report.json
    miter lint spec.mtr
    miter compile "check that driver hours stay under 14"
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .compiler import compile_text
from .engine import MiterEngine
from .parser import MiterError, parse


def _load_rows(path: str) -> list[dict]:
    raw = open(path, encoding="utf-8").read().strip()
    if not raw:
        return []
    if raw.startswith("["):
        return json.loads(raw)
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def _format_row(row: dict) -> str:
    return json.dumps(row, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="miter", description=__doc__.strip().splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="evaluate data against a spec")
    p_run.add_argument("spec", help="path to a .mtr spec file")
    p_run.add_argument("--data", required=True, help="JSON or JSONL data file")
    p_run.add_argument("--out", default=None, help="write JSON report here instead of stdout")

    # lint
    p_lint = sub.add_parser("lint", help="parse-check a spec without data")
    p_lint.add_argument("spec")

    # compile (natural language -> spec)
    p_cmp = sub.add_parser("compile", help="translate plain English into a spec")
    p_cmp.add_argument("text", nargs="?", help="natural-language evaluation description")
    p_cmp.add_argument("--file", default=None, help="read the description from a file")
    p_cmp.add_argument("--out", default=None, help="write the generated spec here")

    args = ap.parse_args(argv)

    try:
        if args.command == "run":
            spec = parse(open(args.spec, encoding="utf-8").read())
            rows = _load_rows(args.data)
            report = MiterEngine(spec).evaluate_all(rows)
            text = json.dumps(report, indent=2, sort_keys=True)
            if args.out:
                open(args.out, "w", encoding="utf-8").write(text + "\n")
                print(f"wrote {args.out}")
            else:
                print(text)
            return 1 if report["summary"].get("FAIL", 0) else 0
        if args.command == "lint":
            spec = parse(open(args.spec, encoding="utf-8").read())
            print(f"OK {spec.name}: {len(spec.criteria)} criteria, "
                  f"{len(spec.variations)} variations, {len(spec.interfaces)} interfaces "
                  f"({spec.spec_hash()})")
            return 0
        if args.command == "compile":
            text = args.text
            if args.file:
                text = open(args.file, encoding="utf-8").read()
            if not text:
                print("error: pass text or --file", file=sys.stderr)
                return 2
            result = compile_text(text)
            # round-trip: the generated spec must parse, or the compile failed
            if args.out:
                open(args.out, "w", encoding="utf-8").write(result.spec_text)
                print(f"wrote {args.out}")
            else:
                print(result.spec_text)
            for note in result.notes:
                print(f"# note: {note}", file=sys.stderr)
            return 0
    except (MiterError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
