"""Stage 6 - Release.

Builds the release package (the static Risk Gate dashboard, see export_site.py),
records the deployment in the pipeline history and, inside GitHub Actions, the
workflow publishes the package to GitHub Pages (a real public deployment).

    python deploy.py --run-id 7 [--approved-by NAME]
"""
import argparse
import os
import sys

import config
import history


def deploy_application(run_id=None, approved_by=None, build=True):
    print("Starting Deployment...")
    if run_id:
        fields = {"status": "DEPLOYED", "deployed_at": history.now()}
        if approved_by:
            fields.update(approved_by=approved_by, approved_at=history.now())
        if os.environ.get("GITHUB_ACTIONS"):
            fields["deploy_url"] = (f"{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}"
                                    f"/actions/runs/{os.environ.get('GITHUB_RUN_ID')}")
            fields["site_url"] = config.PAGES_URL
        history.update(run_id, **fields)
    if build:
        import export_site
        out = export_site.build()
        print(f"  - Release package built: {out}")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"  - Publishing to GitHub Pages: {config.PAGES_URL}")
    else:
        print(f"  - Local release: open {config.SITE_DIR / 'index.html'}")
    print("Application deployed successfully!")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int)
    ap.add_argument("--approved-by")
    a = ap.parse_args()
    sys.exit(0 if deploy_application(a.run_id, a.approved_by) else 1)
