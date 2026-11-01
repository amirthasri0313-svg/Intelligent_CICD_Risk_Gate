"""Run the complete CI/CD risk-gate pipeline locally, exactly as GitHub Actions does.

    python pipeline.py

Stages: Change Analysis -> Tests & Coverage -> Code Quality -> Security Scan
        -> ML Risk Model -> Release Readiness -> Risk Gate -> Deploy / Approval
The run appears on the dashboard (python app.py, http://127.0.0.1:5000/dashboard).
"""
import json
import subprocess
import sys

from config import report_path

STAGES = [
    ("CHANGE ANALYSIS", "change_analyzer.py"),
    ("TESTS & COVERAGE", "run_tests.py"),
    ("CODE QUALITY (RUFF)", "quality_check.py"),
    ("SECURITY SCAN (BANDIT)", "security_check.py"),
    ("ML RISK MODEL", "ml_risk.py"),
    ("RELEASE READINESS", "release_readiness.py"),
]


def banner(text):
    print("\n" + "=" * 64 + f"\n{text}\n" + "=" * 64)


def main():
    banner("   INTELLIGENT CI/CD RISK GATE PIPELINE")
    for name, script in STAGES:
        banner(f"STAGE: {name}")
        if subprocess.run([sys.executable, script], check=False).returncode != 0:
            print(f"{name}: ERROR")
            sys.exit(1)

    banner("STAGE: RISK GATE")
    code = subprocess.run([sys.executable, "risk_gate.py"], check=False).returncode
    rec = json.loads(report_path("latest").read_text())

    banner("STAGE: RELEASE")
    if code == 0:
        subprocess.run([sys.executable, "deploy.py", "--run-id", str(rec["id"])], check=False)
        result = "DEPLOYED"
    elif code == 2:
        print("MANUAL APPROVAL REQUIRED - approve or reject it on the dashboard:")
        print(f"  http://127.0.0.1:5000/run/local-{rec['id']}")
        result = "WAITING FOR APPROVAL"
    else:
        print("RELEASE BLOCKED - fix the blockers and run the pipeline again.")
        result = "BLOCKED"
    banner(f"CI/CD PIPELINE RESULT: {result}  (risk {rec['risk_score']}/100)")
    sys.exit(1 if code == 1 else 0)


if __name__ == "__main__":
    main()
