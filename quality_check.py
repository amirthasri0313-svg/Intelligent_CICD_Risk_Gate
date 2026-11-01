"""Stage 2b - Code quality (Ruff) and complexity.

Runs `ruff check --output-format json` on the Python files changed in this push
(falls back to the built-in analyzer if ruff is not installed) and measures the
cyclomatic complexity of those files. Writes reports/quality.json.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from config import ROOT, report_path
from static_analysis import complexity, quality_findings


def target_files():
    try:
        change = json.loads(report_path("change").read_text())
        files = [f for f in change["files"] if f.endswith(".py") and (ROOT / f).exists()]
        return files, "changed files"
    except (OSError, ValueError, KeyError):
        files = [str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.rglob("*.py")
                 if not any(part in {".git", "venv", ".venv", "__pycache__"} for part in p.parts)]
        return files, "all files"


def run_ruff(files):
    ruff = shutil.which("ruff")
    if not ruff or not files:
        return None
    proc = subprocess.run([ruff, "check", "--output-format", "json", *files], cwd=ROOT,
                          capture_output=True, text=True, check=False)
    try:
        items = json.loads(proc.stdout or "[]")
    except ValueError:
        return None
    return [{"code": i.get("code") or "E", "message": i.get("message", ""),
             "file": str(Path(i.get("filename", "")).resolve().relative_to(ROOT)).replace("\\", "/")
             if i.get("filename") else "", "line": (i.get("location") or {}).get("row", 0)} for i in items]


def run():
    files, scope = target_files()
    issues = run_ruff(files)
    tool = "ruff"
    if issues is None:
        tool = "built-in"
        issues = []
        for f in files:
            issues += quality_findings((ROOT / f).read_text(encoding="utf-8", errors="replace"), f)
    cc = [complexity((ROOT / f).read_text(encoding="utf-8", errors="replace"))["max_cc"] for f in files] or [0]
    syntax_errors = [i for i in issues if i["code"] in ("E999",) or "SyntaxError" in i["message"]]
    return {"tool": tool, "scope": scope, "files": files, "issues": issues, "issue_count": len(issues),
            "max_complexity": max(cc), "syntax_errors": syntax_errors,
            "status": "PASS" if not issues else "FAIL"}


if __name__ == "__main__":
    result = run()
    report_path("quality").write_text(json.dumps(result, indent=2))
    print(f"Running {result['tool']} on {len(result['files'])} {result['scope']}...")
    for i in result["issues"][:30]:
        print(f"  {i['file']}:{i['line']} {i['code']} {i['message']}")
    print(f"\nCode Quality Check: {result['status']} ({result['issue_count']} issues, "
          f"max complexity {result['max_complexity']})")
    sys.exit(0)
