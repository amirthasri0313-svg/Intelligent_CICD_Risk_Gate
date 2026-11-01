"""Stage 3 - Risk Calculation (release readiness).

Combines every stage report into one explainable score:

    E = evaluation risk  (tests, coverage, security, quality, complexity, change impact)
    H = historical ML risk (ml_risk.py)
    Risk R = 0.65 * E + 0.35 * H          Readiness = 100 - R

Hard blockers (failing tests, syntax error, HIGH security finding) push R above 70.
Policy guards (pipeline / dependency change, removed tests, MEDIUM finding)
send an otherwise low-risk change to manual approval.
Writes reports/risk.json.
"""
import json
import sys

from config import AUTO, AUTO_MAX, BLOCKED, COVERAGE_TARGET, MANUAL, MANUAL_MAX, W_EVAL, W_HIST, report_path


def load(name, default=None):
    try:
        return json.loads(report_path(name).read_text())
    except (OSError, ValueError):
        return default if default is not None else {}


def factors(change, tests, quality, security):
    fx = []
    if tests.get("total"):
        rate = tests["pass_rate"]
        fx.append(("Failing tests", min(30.0, (1 - rate) * 300) if tests["failed"] else 0.0,
                   f"{tests['failed']} of {tests['total']} tests failing"))
    elif tests:
        fx.append(("No tests found", 20.0, "the test suite did not run any tests"))
    cov = tests.get("coverage")
    if cov is not None:
        fx.append(("Low coverage", round(min(15.0, max(0.0, COVERAGE_TARGET - cov) * 50), 2),
                   f"coverage {cov:.0%} (target {COVERAGE_TARGET:.0%})"))
    fx.append(("Tests removed", min(10.0, 3.0 * tests.get("removed", 0)), f"{tests.get('removed', 0)} tests removed"))
    sec = 8 * security.get("high", 0) + 5 * security.get("medium", 0) + 1 * security.get("low", 0)
    fx.append(("Security findings", min(25.0, float(sec)),
               f"{security.get('high', 0)} high, {security.get('medium', 0)} medium, {security.get('low', 0)} low"))
    fx.append(("Code quality", min(8.0, float(quality.get("issue_count", 0))), f"{quality.get('issue_count', 0)} lint issues"))
    cc = quality.get("max_complexity", 0)
    fx.append(("Complexity", min(5.0, max(0, cc - 10) * 0.5), f"max cyclomatic complexity {cc}"))
    fx.append(("Change impact", round(change.get("change_score", 0) * 0.15, 2),
               f"change score {change.get('change_score', 0)}/100, {change.get('files_changed', 0)} files"))
    src_no_tests = bool(change.get("source_files")) and not change.get("test_files")
    fx.append(("Source changed without tests", 4.0 if src_no_tests else 0.0,
               "no test file updated" if src_no_tests else "tests updated or no source change"))
    return [(n, round(p, 2), d) for n, p, d in fx]


def blockers(tests, quality, security):
    b = []
    if tests.get("failed"):
        b.append(f"{tests['failed']} failing test(s)")
    if quality.get("syntax_errors"):
        e = quality["syntax_errors"][0]
        b.append(f"syntax error in {e['file']}:{e['line']}")
    if security.get("high"):
        first = next(f for f in security["findings"] if f["severity"] == "HIGH")
        b.append(f"{security['high']} HIGH security finding(s), e.g. {first['issue']} ({first['file']}:{first['line']})")
    return b


def guards(change, tests, security):
    g = []
    if change.get("workflow_changed"):
        g.append("CI/CD workflow file changed")
    if change.get("dependency_changed"):
        g.append("dependency / build file changed")
    if tests.get("removed"):
        g.append(f"{tests['removed']} test(s) removed since the last pipeline run")
    if security.get("medium"):
        g.append(f"{security['medium']} MEDIUM security finding(s)")
    return g


def decide(score, blk, grd):
    if blk or score > MANUAL_MAX:
        return BLOCKED
    if score > AUTO_MAX or grd:
        return MANUAL
    return AUTO


def calculate(change=None, tests=None, quality=None, security=None, ml=None):
    change = change if change is not None else load("change")
    tests = tests if tests is not None else load("tests")
    quality = quality if quality is not None else load("quality")
    security = security if security is not None else load("security")
    ml = ml if ml is not None else load("ml", {"available": False, "historical_risk": 0.0})
    fx = factors(change, tests, quality, security)
    E = min(100.0, sum(p for _, p, _ in fx))
    H = float(ml.get("historical_risk", 0.0)) if ml.get("available") else None
    score = W_EVAL * E + W_HIST * H if H is not None else E
    blk = blockers(tests, quality, security)
    if blk:
        score = max(score, 75.0 + min(25.0, 5.0 * (len(blk) - 1) + E * 0.2))
    score = round(min(100.0, score), 1)
    grd = guards(change, tests, security)
    decision = decide(score, blk, grd)
    return {
        "risk_score": score, "readiness_score": round(100 - score, 1),
        "evaluation_risk": round(E, 1), "historical_risk": H,
        "level": "LOW" if decision == AUTO else "MEDIUM" if decision == MANUAL else "HIGH",
        "decision": decision, "blockers": blk, "guards": grd,
        "factors": sorted(fx, key=lambda x: -x[1]),
        "formula": (f"R = {W_EVAL} x E {E:.1f} + {W_HIST} x H {H:.1f}" if H is not None else f"R = E {E:.1f}")
                   + (f"  -> raised to {score} by blocker" if blk else ""),
    }


# Backwards-compatible helpers from the first version
def calculate_readiness(change_score, tests_passed, security_passed, quality_passed):
    r = calculate({"change_score": change_score, "files_changed": 1},
                  {"total": 1, "failed": 0 if tests_passed else 1, "pass_rate": 1.0 if tests_passed else 0.0},
                  {"issue_count": 0 if quality_passed else 3},
                  {"high": 0, "medium": 0 if security_passed else 1, "low": 0, "findings": []},
                  {"available": False})
    return round(r["readiness_score"])


def get_release_decision(readiness_score):
    risk = 100 - readiness_score
    if risk <= AUTO_MAX:
        return "LOW RISK - AUTO DEPLOY"
    if risk <= MANUAL_MAX:
        return "MEDIUM RISK - MANUAL APPROVAL"
    return "HIGH RISK - BLOCK RELEASE"


if __name__ == "__main__":
    r = calculate()
    report_path("risk").write_text(json.dumps(r, indent=2))
    print(f"Evaluation risk E: {r['evaluation_risk']}   Historical ML risk H: {r['historical_risk']}")
    print(r["formula"])
    for n, p, d in r["factors"]:
        if p:
            print(f"  +{p:5.1f}  {n}: {d}")
    print(f"\nRisk Score: {r['risk_score']}/100   Readiness: {r['readiness_score']}/100   Level: {r['level']}")
    sys.exit(0)
