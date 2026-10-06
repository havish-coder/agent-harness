"""Attack lab report (Lesson 35): which attacks the harness stops, by threat.

Run:  python scripts/attack_report.py [--markdown]

Runs `pytest tests/security` and groups the results by the threat number in the test names
(`test_t4_...` is threat T4 in docs/security.md). An attack that is defended is a passing test; an
attack we know we can't stop on this machine is an expected failure, with its reason.
"""
import argparse
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THREATS = {
    "t1": "Read outside the workspace", "t2": "Write outside the workspace", "t3": "Escape through a link",
    "t4": "Tamper with configuration that runs code", "t7": "Secrets through the shell",
    "t9": "Prompt injection", "t13": "Runaway use", "t14": "Secrets in logs and transcripts",
}


def run_lab() -> list[tuple[str, str, str, str]]:
    """(status, test function name, full name, reason) for every test in tests/security."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        subprocess.run([sys.executable, "-m", "pytest", "tests/security", "-q", "--no-header", "-p", "no:cacheprovider",
                        f"--junitxml={report}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if not report.exists():
            return []
        results = []
        for case in ET.parse(report).getroot().iter("testcase"):
            full = case.get("name", "")
            status, why = "PASSED", ""
            for child in case:
                if child.tag in ("failure", "error"):
                    status, why = "FAILED", child.get("message", "")
                elif child.tag == "skipped":
                    status, why = ("XFAIL" if child.get("type") == "pytest.xfail" else "SKIPPED"), child.get("message", "")
            results.append((status, full.split("[")[0], full, why))
        return results


def threat_of(test_name: str) -> str:
    m = re.match(r"test_(t\d+)_", test_name)
    return m.group(1) if m else "other"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    results = run_lab()
    if not results:
        print("no results: is pytest installed? (pip install -e \".[dev]\")")
        return 1
    table: dict[str, dict] = defaultdict(lambda: {"defended": 0, "open": [], "failed": 0})
    for status, name, full, why in results:
        row = table[threat_of(name)]
        if status in ("PASSED", "XPASS"):
            row["defended"] += 1
        elif status == "XFAIL":
            row["open"].append((full, why))
        elif status in ("FAILED", "ERROR"):
            row["failed"] += 1
    order = sorted(table, key=lambda t: (t == "other", int(t[1:]) if t[1:].isdigit() else 0))
    if args.markdown:
        print("| Threat | Attacks stopped | Open here | |\n|---|---|---|---|")
    for key in order:
        row, label = table[key], THREATS.get(key, "Modes, rules, limits and the rest")
        opened = len(row["open"])
        if args.markdown:
            print(f"| {key.upper() if key != 'other' else '-'} {label} | {row['defended']} | {opened} | "
                  + ("; ".join(why for _, why in row["open"])[:120]) + " |")
        else:
            print(f"{key.upper() if key != 'other' else '  ':<4}{label:<42} stopped {row['defended']:>3}   open {opened}"
                  + (f"   FAILING {row['failed']}" if row["failed"] else ""))
    stopped = sum(r["defended"] for r in table.values())
    open_ = sum(len(r["open"]) for r in table.values())
    failing = sum(r["failed"] for r in table.values())
    print(f"\n{stopped} attacks stopped, {open_} known to get through on this machine, {failing} unexpected failures")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
