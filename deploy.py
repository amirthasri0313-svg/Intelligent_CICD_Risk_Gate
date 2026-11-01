"""Stage 6 - Release.

Simulates the production deployment and records it in the pipeline history
so the dashboard shows the change as deployed.

    python deploy.py --run-id 7 [--approved-by NAME]
"""
import argparse
import os
import sys
import time

import history


def deploy_application(run_id=None, approved_by=None):
    print("Starting Deployment...")
    for step in ("Building release package", "Uploading to production server", "Switching traffic", "Health check"):
        print(f"  - {step} ... ok")
        time.sleep(0.2)
    print("Application deployed successfully!")
    if run_id:
        fields = {"status": "DEPLOYED", "deployed_at": history.now()}
        if approved_by:
            fields.update(approved_by=approved_by, approved_at=history.now())
        if os.environ.get("GITHUB_ACTIONS"):
            fields["deploy_url"] = (f"{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}"
                                    f"/actions/runs/{os.environ.get('GITHUB_RUN_ID')}")
        history.update(run_id, **fields)
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int)
    ap.add_argument("--approved-by")
    a = ap.parse_args()
    sys.exit(0 if deploy_application(a.run_id, a.approved_by) else 1)
