"""python -m evals run [--engine mock|cli|sdk] [--case ID ...] [--parallel N] [--label TEXT]"""

import argparse
import json

from .runner import load_cases, run


def main():
    ap = argparse.ArgumentParser(prog="python -m evals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--engine", default="mock", choices=["mock", "cli", "sdk"])
    r.add_argument("--case", action="append")
    r.add_argument("--parallel", type=int, default=2)
    r.add_argument("--run-id")
    r.add_argument("--label")
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "list":
        for c in load_cases():
            print(f"{c['id']:18} {c.get('title')}")
        return
    out = run(a.engine, a.case, a.run_id, a.parallel, a.label)
    ag = out.get("aggregate", {})
    print(json.dumps(ag, indent=2))
    for c in out["cases"]:
        s = c.get("scores", {})
        print(
            f"{'PASS' if c.get('passed') else 'FAIL'} {c['id']:18} overall={s.get('overall')} data={s.get('data')} code={s.get('code')} gates={s.get('gates')}"
        )


if __name__ == "__main__":
    main()
