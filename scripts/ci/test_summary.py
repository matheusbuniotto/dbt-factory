#!/usr/bin/env python3
"""Markdown test summary from junit xml + coverage.xml (+ optional diff-cover markdown). Missing files are skipped."""

# XML here is CI-generated (pytest/coverage), never untrusted input.
import os
import sys
import xml.etree.ElementTree as ET  # nosec B405


def main(junit, cov, diff=None):
    out = ["## Test results", ""]
    if os.path.exists(junit):
        root = ET.parse(junit).getroot()  # nosec B314
        s = root if root.tag == "testsuite" else root.find("testsuite")
        if s is not None:
            t, f, e, sk = (int(s.get(k, 0)) for k in ("tests", "failures", "errors", "skipped"))
            out.append(
                f"| tests | passed | failed | errors | skipped | time |\n|---:|---:|---:|---:|---:|---:|\n"
                f"| {t} | {t - f - e - sk} | {f} | {e} | {sk} | {float(s.get('time', 0)):.1f}s |"
            )
    if os.path.exists(cov):
        c = ET.parse(cov).getroot()  # nosec B314
        out.append(
            f"\nLine coverage **{float(c.get('line-rate', 0)) * 100:.1f}%** · branch **{float(c.get('branch-rate', 0)) * 100:.1f}%**"
        )
    if diff and os.path.exists(diff):
        out += ["", "<details><summary>diff-cover</summary>", "", open(diff).read(), "</details>"]
    print("\n".join(out) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:4])
