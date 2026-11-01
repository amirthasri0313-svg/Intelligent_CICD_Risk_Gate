"""Stage 4 - Risk Gate.

Reads every stage report, records the run in reports/history.json (stage 5,
dashboard data), prints the decision and, inside GitHub Actions, writes the
job summary table and the step outputs that decide which deploy job runs:

    AUTO DEPLOY       -> deploy job runs straight away
    MANUAL APPROVAL   -> deploy job waits for a reviewer (GitHub environment)
    RELEASE BLOCKED   -> this step fails and the pipeline stops

Exit codes: 0 auto deploy, 2 manual approval (0 inside GitHub Actions), 1 blocked.
"""
import json
import os
import sys

import history
from config import AUTO, BLOCKED, MANUAL, report_path
from release_readiness import calculate, load

ICON = {AUTO: "🟢", MANUAL: "🟡", BLOCKED: "🔴"}
STATUS = {AUTO: "DEPLOYING", MANUAL: "WAITING APPROVAL", BLOCKED: "BLOCKED"}


def github_context():
    if not os.environ.get("GITHUB_ACTIONS"):
        return {"source": "local pipeline"}
    server, repo, run = (os.environ.get(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return {"source": "github actions", "run_url": f"{server}/{repo}/actions/runs/{run}",
            "run_number": os.environ.get("GITHUB_RUN_NUMBER"), "event": os.environ.get("GITHUB_EVENT_NAME"),
            "branch": os.environ.get("GITHUB_REF_NAME"), "actor": os.environ.get("GITHUB_ACTOR"),
            "commit_url": f"{server}/{repo}/commit/{os.environ.get('GITHUB_SHA', '')}"}


def build_record(risk):
    change, tests, quality, security, ml = (load(n) for n in ("change", "tests", "quality", "security", "ml"))
    stages = {
        "Change Analysis": {"status": "DONE", "detail": f"{change.get('files_changed', 0)} files, +{change.get('lines_added', 0)} "
                                                        f"-{change.get('lines_deleted', 0)}, score {change.get('change_score', 0)}"},
        "Tests & Coverage": {"status": "FAIL" if tests.get("failed") else "PASS",
                             "detail": f"{tests.get('passed', 0)}/{tests.get('total', 0)} passed"
                                       + (f", coverage {tests['coverage']:.0%}" if tests.get("coverage") is not None else "")},
        "Code Quality": {"status": quality.get("status", "PASS"),
                         "detail": f"{quality.get('tool', '')}: {quality.get('issue_count', 0)} issues, max complexity {quality.get('max_complexity', 0)}"},
        "Security Scan": {"status": security.get("status", "PASS"),
                          "detail": f"{security.get('tool', '')}: {security.get('high', 0)} high, {security.get('medium', 0)} medium, {security.get('low', 0)} low"},
        "ML Risk Model": {"status": "DONE" if ml.get("available") else "SKIPPED",
                          "detail": f"H = {ml.get('historical_risk')} (p = {ml.get('probability')})" if ml.get("available") else ml.get("error", "")},
        "Risk Gate": {"status": risk["decision"], "detail": f"risk {risk['risk_score']}/100"},
    }
    return {
        **github_context(),
        "commit": change.get("head"), "message": change.get("message"), "author": change.get("author"),
        "files": change.get("files", []), "change": change, "tests": tests,
        "quality": {k: v for k, v in quality.items() if k != "files"},
        "security": {k: v for k, v in security.items() if k != "files"},
        "ml": ml, "risk": risk, "stages": stages,
        "decision": risk["decision"], "risk_score": risk["risk_score"], "status": STATUS[risk["decision"]],
    }


def summary_markdown(rec):
    r = rec["risk"]
    lines = [f"## {ICON[r['decision']]} Risk Gate: **{r['decision']}**", "",
             f"**Risk score {r['risk_score']}/100** · readiness {r['readiness_score']}/100 · level {r['level']}  ",
             f"Commit `{rec['commit']}` by {rec['author']}: {rec['message']}", "",
             "| Stage | Result | Detail |", "|---|---|---|"]
    lines += [f"| {name} | {s['status']} | {s['detail']} |" for name, s in rec["stages"].items()]
    lines += ["", f"`{r['formula']}`", "", "| Risk factor | Points | Detail |", "|---|---:|---|"]
    lines += [f"| {n} | {p} | {d} |" for n, p, d in r["factors"] if p]
    if r["blockers"]:
        lines += ["", "### Blockers"] + [f"- 🔴 {b}" for b in r["blockers"]]
    if r["guards"]:
        lines += ["", "### Policy guards (need a human)"] + [f"- 🟡 {g}" for g in r["guards"]]
    findings = rec["security"].get("findings", [])
    if findings:
        lines += ["", "### Security findings", "| Severity | Rule | Location | Issue |", "|---|---|---|---|"]
        lines += [f"| {f['severity']} | {f['test_id']} | `{f['file']}:{f['line']}` | {f['issue']} |" for f in findings[:20]]
    if rec["ml"].get("available"):
        lines += ["", f"ML model: {rec['ml']['trained_on']}."]
    nxt = {AUTO: "Deploying automatically.", MANUAL: "Waiting for a reviewer to approve the **production** deployment.",
           BLOCKED: "Deployment stopped. Fix the blockers and push again."}[r["decision"]]
    return "\n".join(lines + ["", f"**Next:** {nxt}"])


def main():
    risk = calculate()
    report_path("risk").write_text(json.dumps(risk, indent=2))
    rec = build_record(risk)
    rec["id"] = history.add(rec)
    report_path("latest").write_text(json.dumps(rec, indent=2))

    print(f"Risk Score: {risk['risk_score']}/100   Readiness: {risk['readiness_score']}/100")
    for b in risk["blockers"]:
        print(f"  BLOCKER: {b}")
    for g in risk["guards"]:
        print(f"  GUARD:   {g}")
    print(f"Risk Gate Decision: {risk['decision']}  (run #{rec['id']} recorded for the dashboard)")

    in_actions = bool(os.environ.get("GITHUB_ACTIONS"))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(summary_markdown(rec) + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"decision={risk['decision']}\nrisk_score={risk['risk_score']}\nrun_id={rec['id']}\n")
    if risk["decision"] == BLOCKED:
        if in_actions:
            print(f"::error title=Risk gate::Release blocked (risk {risk['risk_score']}): " + "; ".join(risk["blockers"] or ["score above 70"]))
        return 1
    if risk["decision"] == MANUAL:
        if in_actions:
            print(f"::warning title=Risk gate::Manual approval required (risk {risk['risk_score']})")
            return 0
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
