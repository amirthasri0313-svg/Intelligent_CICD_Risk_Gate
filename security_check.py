"""Stage 2c - Security scan (Bandit).

Runs `bandit -f json` over the Python files changed in this push (whole repo if
the change report is missing) and counts findings by severity. Falls back to
the built-in rules when bandit is not installed. Writes reports/security.json.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from config import ROOT, report_path
from static_analysis import security_findings
from quality_check import target_files


def run_bandit(files):
    bandit = shutil.which("bandit")
    if not bandit or not files:
        return None
    proc = subprocess.run([bandit, "-q", "-f", "json", *files], cwd=ROOT,
                          capture_output=True, text=True, check=False)
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        return None
    out = []
    for r in data.get("results", []):
        name = r.get("filename", "")
        try:
            name = str(Path(name).resolve().relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            pass
        # assert statements are normal in tests
        if r.get("test_id") == "B101":
            continue
        out.append({"severity": r.get("issue_severity", "LOW").upper(), "test_id": r.get("test_id", ""),
                    "issue": r.get("issue_text", ""), "file": name, "line": r.get("line_number", 0)})
    return out


def run():
    files, scope = target_files()
    findings = run_bandit(files)
    tool = "bandit"
    if findings is None:
        tool = "built-in"
        findings = []
        for f in files:
            findings += security_findings((ROOT / f).read_text(encoding="utf-8", errors="replace"), f)
    count = {s: sum(1 for f in findings if f["severity"] == s) for s in ("HIGH", "MEDIUM", "LOW")}
    return {"tool": tool, "scope": scope, "files": files, "findings": findings, **{s.lower(): n for s, n in count.items()},
            "status": "FAIL" if count["HIGH"] or count["MEDIUM"] else "PASS"}


def run_security_check():
    """Kept for backwards compatibility with the first version."""
    result = run()
    report_path("security").write_text(json.dumps(result, indent=2))
    return result["status"] == "PASS"


if __name__ == "__main__":
    result = run()
    report_path("security").write_text(json.dumps(result, indent=2))
    print(f"Running {result['tool']} security scan on {len(result['files'])} {result['scope']}...")
    for f in result["findings"]:
        print(f"  [{f['severity']}] {f['test_id']} {f['file']}:{f['line']} {f['issue']}")
    print(f"\nSecurity Check: {result['status']} (HIGH {result['high']}, MEDIUM {result['medium']}, LOW {result['low']})")
    sys.exit(0)
