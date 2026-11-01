"""Automated evaluation for code pasted on the Code Input page (single snippet).

Runs the same checks as the pipeline on a single snippet: syntax (py_compile),
code quality (ruff, or the built-in analyzer), security (bandit, or the built-in
rules) and complexity; then scores it with the same risk engine and gate.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release_readiness import calculate
from static_analysis import complexity, quality_findings, security_findings


def run_command(command, cwd=None):
    try:
        r = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=30, check=False)
        return {"success": r.returncode == 0, "returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"success": False, "returncode": -1, "stdout": "", "stderr": str(e)}


def _ruff(path):
    if not shutil.which("ruff"):
        return None
    r = run_command(["ruff", "check", "--output-format", "json", str(path)])
    try:
        return [{"code": i.get("code") or "E", "message": i.get("message", ""), "file": "submitted_code.py",
                 "line": (i.get("location") or {}).get("row", 0)} for i in json.loads(r["stdout"] or "[]")]
    except ValueError:
        return None


def _bandit(path):
    if not shutil.which("bandit"):
        return None
    r = run_command(["bandit", "-q", "-f", "json", str(path)])
    try:
        data = json.loads(r["stdout"] or "{}")
    except ValueError:
        return None
    return [{"severity": x.get("issue_severity", "LOW").upper(), "test_id": x.get("test_id", ""),
             "issue": x.get("issue_text", ""), "file": "submitted_code.py", "line": x.get("line_number", 0)}
            for x in data.get("results", []) if x.get("test_id") != "B101"]


def evaluate_code(code):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "submitted_code.py"
        path.write_text(code, encoding="utf-8")
        syntax = run_command([sys.executable, "-m", "py_compile", str(path)])
        issues = _ruff(path)
        q_tool = "ruff"
        if issues is None:
            issues, q_tool = quality_findings(code, "submitted_code.py"), "built-in"
        findings = _bandit(path)
        s_tool = "bandit"
        if findings is None:
            findings, s_tool = security_findings(code, "submitted_code.py"), "built-in"

    syntax_ok = syntax["success"]
    syntax_errors = [] if syntax_ok else [{"file": "submitted_code.py", "line": 0,
                                          "message": (syntax["stderr"] or "SyntaxError").strip().splitlines()[-1]}]
    lines = code.count("\n") + 1
    count = {s: sum(1 for f in findings if f["severity"] == s) for s in ("HIGH", "MEDIUM", "LOW")}
    change = {"files_changed": 1, "lines_added": lines, "change_score": 20, "source_files": ["submitted_code.py"],
              "test_files": [], "files": ["submitted_code.py"]}
    quality = {"tool": q_tool, "issues": issues, "issue_count": len(issues),
               "max_complexity": complexity(code)["max_cc"], "syntax_errors": syntax_errors}
    security = {"tool": s_tool, "findings": findings, "high": count["HIGH"], "medium": count["MEDIUM"], "low": count["LOW"]}
    risk = calculate(change, {}, quality, security, {"available": False})
    return {
        # keys used by the first version of the result page
        "syntax": "PASS" if syntax_ok else "FAIL",
        "quality": "PASS" if not issues else "FAIL",
        "security": "PASS" if not (count["HIGH"] or count["MEDIUM"]) else "FAIL",
        "quality_detail": quality, "security_detail": security, "lines": lines, "risk": risk,
    }


if __name__ == "__main__":
    sample = 'import sqlite3\n\ndef find(con, sku):\n    return con.execute(f"SELECT * FROM items WHERE sku = \'{sku}\'").fetchone()\n'
    e = evaluate_code(sample)
    print("Evaluation Results\n==================")
    for k in ("syntax", "quality", "security"):
        print(f"{k.title():10}: {e[k]}")
    print(f"Risk score: {e['risk']['risk_score']}  Decision: {e['risk']['decision']}")
