import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from change_analyzer import calculate_change_score  # noqa: E402
from config import AUTO, BLOCKED, MANUAL  # noqa: E402
from release_readiness import calculate, calculate_readiness, get_release_decision  # noqa: E402
from static_analysis import complexity, quality_findings, security_findings  # noqa: E402

CLEAN_CHANGE = {"files_changed": 2, "change_score": 30, "source_files": ["app.py"], "test_files": ["tests/test_app.py"]}
GREEN_TESTS = {"total": 20, "failed": 0, "pass_rate": 1.0, "coverage": 0.9, "removed": 0}
NO_FINDINGS = {"high": 0, "medium": 0, "low": 0, "findings": []}
CLEAN_QUALITY = {"issue_count": 0, "max_complexity": 4, "syntax_errors": []}
ML_LOW = {"available": True, "historical_risk": 20.0}


def test_change_score_by_file_type():
    assert calculate_change_score(["app.py"]) == 20
    assert calculate_change_score([".github/workflows/ci.yml"]) == 30
    assert calculate_change_score(["requirements.txt"]) == 25
    assert calculate_change_score(["tests/test_app.py"]) == 10
    assert calculate_change_score(["a.py"] * 9) == 100


def test_clean_change_auto_deploys():
    r = calculate(CLEAN_CHANGE, GREEN_TESTS, CLEAN_QUALITY, NO_FINDINGS, ML_LOW)
    assert r["decision"] == AUTO and r["risk_score"] <= 30


def test_failing_tests_block():
    tests = {**GREEN_TESTS, "failed": 2, "pass_rate": 0.9}
    r = calculate(CLEAN_CHANGE, tests, CLEAN_QUALITY, NO_FINDINGS, ML_LOW)
    assert r["decision"] == BLOCKED and r["blockers"]


def test_high_security_finding_blocks():
    sec = {"high": 1, "medium": 0, "low": 0,
           "findings": [{"severity": "HIGH", "issue": "SQL injection", "file": "a.py", "line": 3}]}
    assert calculate(CLEAN_CHANGE, GREEN_TESTS, CLEAN_QUALITY, sec, ML_LOW)["decision"] == BLOCKED


def test_workflow_change_needs_approval():
    change = {**CLEAN_CHANGE, "workflow_changed": True}
    r = calculate(change, GREEN_TESTS, CLEAN_QUALITY, NO_FINDINGS, ML_LOW)
    assert r["decision"] == MANUAL and r["guards"]


def test_removed_tests_need_approval():
    r = calculate(CLEAN_CHANGE, {**GREEN_TESTS, "removed": 3}, CLEAN_QUALITY, NO_FINDINGS, ML_LOW)
    assert r["decision"] == MANUAL


def test_ml_risk_raises_score():
    low = calculate(CLEAN_CHANGE, GREEN_TESTS, CLEAN_QUALITY, NO_FINDINGS, {"available": True, "historical_risk": 5})
    high = calculate(CLEAN_CHANGE, GREEN_TESTS, CLEAN_QUALITY, NO_FINDINGS, {"available": True, "historical_risk": 95})
    assert high["risk_score"] > low["risk_score"]


def test_backwards_compatible_helpers():
    assert get_release_decision(calculate_readiness(20, True, True, True)) == "LOW RISK - AUTO DEPLOY"
    assert get_release_decision(10) == "HIGH RISK - BLOCK RELEASE"


def test_static_analysis_rules():
    src = 'import os\npassword = "hunter22"\nos.system("ls " + x)\neval(y)\ntry:\n    pass\nexcept:\n    pass\n'
    ids = {f["test_id"] for f in security_findings(src)}
    assert {"B105", "B605", "B307"} <= ids
    codes = {q["code"] for q in quality_findings(src)}
    assert "E722" in codes
    assert complexity("def f(a):\n    if a and a > 1:\n        return 1\n    return 0\n")["max_cc"] == 3
