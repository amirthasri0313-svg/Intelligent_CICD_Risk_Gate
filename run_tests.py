"""Stage 2a - Automated tests and coverage.

Runs the whole pytest suite with line coverage (pytest-cov) and writes
reports/tests.json: total, passed, failed, coverage, and how many tests the
previous pipeline run had (to detect removed tests).
"""
import json
import os
import subprocess
import sys
# Only parses XML reports that pytest writes in this same run (trusted input).
import xml.etree.ElementTree as ET  # nosec B405

from config import HISTORY_FILE, ROOT, report_path


def previous_test_count():
    try:
        runs = json.loads(HISTORY_FILE.read_text())
        pipeline_runs = [r for r in runs if r.get("source") == "pipeline" and r.get("tests", {}).get("total")]
        return pipeline_runs[-1]["tests"]["total"] if pipeline_runs else None
    except (OSError, ValueError, KeyError):
        return None


def run():
    junit = report_path("junit").with_suffix(".xml")
    cov_xml = report_path("coverage").with_suffix(".xml")
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"]
    have_cov = subprocess.run([sys.executable, "-c", "import pytest_cov"], capture_output=True).returncode == 0
    if have_cov:
        cmd += ["--cov=.", f"--cov-report=xml:{cov_xml}", "--cov-report=term"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    print(proc.stdout[-3000:])
    total = failed = skipped = 0
    if junit.exists():
        root = ET.parse(junit).getroot()  # nosec B314
        for s in ([root] if root.tag == "testsuite" else root.findall("testsuite")):
            total += int(s.get("tests", 0))
            failed += int(s.get("failures", 0)) + int(s.get("errors", 0))
            skipped += int(s.get("skipped", 0))
    coverage = None
    if have_cov and cov_xml.exists():
        coverage = round(float(ET.parse(cov_xml).getroot().get("line-rate", 0)), 4)  # nosec B314
    prev = previous_test_count()
    return {
        "total": total, "failed": failed, "skipped": skipped, "passed": total - failed - skipped,
        "pass_rate": round((total - failed) / total, 4) if total else 0.0,
        "coverage": coverage, "previous_total": prev,
        "removed": max(0, prev - total) if prev is not None else 0,
        "pytest_exit": proc.returncode,
    }


if __name__ == "__main__":
    result = run()
    report_path("tests").write_text(json.dumps(result, indent=2))
    cov = f"{result['coverage']:.1%}" if result["coverage"] is not None else "n/a"
    print(f"Tests: {result['passed']}/{result['total']} passed, {result['failed']} failed, coverage {cov}")
    # Never fail here: the risk gate decides what a failing test means.
    sys.exit(0)
