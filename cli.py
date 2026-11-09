#!/usr/bin/env python3
"""BetterPrompt standalone CLI — zero deps, zero tokens.

Usage:
    python cli.py "<prompt>"
    python cli.py --file prompt.txt
    echo "prompt" | python cli.py                      # read stdin
    python cli.py --rewrite "<prompt>"                 # + local rewrite
    python cli.py --json "<prompt>"                    # full audit as JSON
    python cli.py --models                             # list pricing table
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import engine  # noqa: E402


def _color(code, s):
    if not sys.stdout.isatty():
        return s
    return f"\033[{code}m{s}\033[0m"


def grade_color(score):
    if score >= 90:
        return "32"   # green
    if score >= 75:
        return "36"   # cyan
    if score >= 55:
        return "33"   # yellow
    return "31"       # red


def report(r):
    g = grade_color(r.score)
    L = []
    L.append(f"{_color(g, '░'*10)}  {_color('1;37', str(r.score))}/100 {_color(g, r.grade)}  {r.tokens['input_tokens']} tokens · ~${r.tokens['est_cost_usd']} · {r.tokens['model']}")
    if not r.text:
        L.append(_color('33', "  (empty prompt — nothing to audit)"))
        return "\n".join(L)
    if r.issues:
        L.append("")
        for i in r.issues:
            sev = {"high": _color("31", "HIGH"), "medium": _color("33", "mid"),
                   "low": _color("36", "low")}.get(i["severity"], "low")
            L.insert(len(L), f"  {sev}  {i['kind']:<13} {i['message']}")
    else:
        L.append(_color("32", "  Clean — no issues."))
    L.append("")
    L.append(f"  Template: {_color('1;37', r.recommended_template['name'])}")
    if r.workflow:
        for w in r.workflow[:3]:
            L.append(f"  Tip: {w}")
    return "\n".join(L)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--models" in argv:
        print(f"{'model':<18}{'in $/1M':>10}{'out $/1M':>10}")
        for m, (i, o) in engine.MODEL_PRICING.items():
            print(f"{m:<18}{i:>10}{o:>10}")
        return 0
    if "--rewrite" in argv:
        i = argv.index("--rewrite")
        text = _text(argv[:i], argv[i + 1:])
        r = engine.audit(text)
        print(report(r))
        print(f"\n{_color('1;36', '—  local zero-token rewrite  —')}\n{r.rebuilded}")
        return 0
    if "--json" in argv:
        i = argv.index("--json")
        text = _text(argv[:i], argv[i + 1:])
        print(json.dumps(engine.audit(text).to_dict(), indent=2))
        return 0
    print(report(engine.audit(_text(list(argv), []))))
    return 0


def _text(prefix: list, rest: list) -> str:
    if "--file" in rest:
        p = rest[rest.index("--file") + 1]
        return open(p).read()
    joined = " ".join(rest + prefix)
    if joined.strip():
        return joined
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
