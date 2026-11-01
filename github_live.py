"""Live link between the dashboard and GitHub Actions.

push_code()  commits the code typed on the dashboard to the repository (GitHub
             Contents API), which triggers the real CI/CD workflow.
track()      follows that workflow run: job and step status, the risk gate
             record and any deployment waiting for a reviewer.
review()     approves or rejects the waiting deployment, exactly like pressing
             "Review deployments" on GitHub.

Needs a GitHub token of a reviewer of the repository, read from the GITHUB_TOKEN
environment variable or the file github_token.txt (never committed).
"""
import base64
import json
import os
import urllib.error
import urllib.request

from config import GITHUB_BRANCH, GITHUB_REPO, ROOT

API = f"https://api.github.com/repos/{GITHUB_REPO}"
DEMO_DIR = "demo_changes"


def token():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not tok:
        try:
            tok = (ROOT / "github_token.txt").read_text(encoding="utf-8").strip()
        except OSError:
            tok = ""
    return tok


def available():
    return bool(token()) and not os.environ.get("RISKGATE_OFFLINE")


class GitHubError(Exception):
    pass


def call(path, method="GET", body=None):
    req = urllib.request.Request(path if path.startswith("https://") else f"{API}/{path}", method=method,
                                 data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "risk-gate-dashboard",
                                          "X-GitHub-Api-Version": "2022-11-28", "Authorization": f"Bearer {token()}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 - fixed https URL
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise GitHubError(f"GitHub {exc.code}: {detail}") from exc
    except OSError as exc:
        raise GitHubError(f"GitHub not reachable: {exc}") from exc


def push_code(filename, code, message):
    """Commit one file under demo_changes/ to the main branch; returns the new commit sha."""
    path = f"{DEMO_DIR}/{filename}"
    body = {"message": message, "branch": GITHUB_BRANCH,
            "content": base64.b64encode(code.encode("utf-8")).decode("ascii")}
    try:
        body["sha"] = call(f"contents/{path}?ref={GITHUB_BRANCH}")["sha"]  # file exists: update it
    except GitHubError as exc:
        if "404" not in str(exc):
            raise
    res = call(f"contents/{path}", "PUT", body)
    return res["commit"]["sha"]


STAGE_OF_STEP = [("Stage 1", 0), ("Stage 2", 1), ("Stage 3", 2), ("Stage 4", 3), ("Stage 5", 4)]


def _gate_record(sha):
    """The risk gate's record for this commit, from reports/history.json on GitHub (fresh, not cached)."""
    try:
        data = call(f"contents/reports/history.json?ref={GITHUB_BRANCH}")
        runs = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
    except (GitHubError, KeyError, ValueError):
        return None
    return next((dict(r, key=f"gh-{r.get('id')}") for r in reversed(runs)
                 if sha.startswith(str(r.get("commit") or "-"))), None)


def track(sha):
    runs = call(f"actions/runs?head_sha={sha}&per_page=5").get("workflow_runs", [])
    if not runs:
        return {"found": False}
    run = runs[0]
    jobs = call(f"actions/runs/{run['id']}/jobs").get("jobs", [])
    stages = [{"status": "pending", "detail": ""} for _ in range(6)]
    for job in jobs:
        if job["name"].startswith("Evaluate"):
            for step in job.get("steps", []):
                i = next((i for p, i in STAGE_OF_STEP if step["name"].startswith(p)), None)
                if i is None:
                    continue
                state = _state(step)
                if stages[i]["status"] in ("pending", "success") or state == "failure":
                    stages[i] = {"status": state, "detail": step["name"].split("·", 1)[-1].strip()}
        elif job["name"].startswith("Stage 6") and job.get("conclusion") != "skipped":
            state = _state(job)
            if stages[5]["status"] in ("pending", "success"):
                stages[5] = {"status": state, "detail": job["name"].split("·", 1)[-1].strip()}
    pending = []
    if run["status"] == "waiting":
        pending = [{"id": p["environment"]["id"], "name": p["environment"]["name"]}
                   for p in call(f"actions/runs/{run['id']}/pending_deployments")]
        stages[5] = {"status": "waiting", "detail": "waiting for reviewer"}
    return {"found": True, "run": {k: run.get(k) for k in ("id", "run_number", "status", "conclusion", "html_url",
                                                             "display_title", "head_sha")},
            "stages": stages, "pending": pending, "record": _gate_record(sha),
            "jobs": [{k: j.get(k) for k in ("name", "status", "conclusion", "html_url")} for j in jobs]}


def _state(item):
    if item.get("status") != "completed":
        return "running" if item.get("status") == "in_progress" else "pending"
    return {"success": "success", "skipped": "skipped"}.get(item.get("conclusion"), "failure")


def review(run_id, approve, comment):
    pending = call(f"actions/runs/{run_id}/pending_deployments")
    if not pending:
        raise GitHubError("Nothing is waiting for approval on this run")
    call(f"actions/runs/{run_id}/pending_deployments", "POST",
         {"environment_ids": [p["environment"]["id"] for p in pending],
          "state": "approved" if approve else "rejected", "comment": comment or "Reviewed on the Risk Gate dashboard"})
    return True
