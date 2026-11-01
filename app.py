"""Flask web app: Code Input, Evaluation Result and the live Risk Gate Dashboard.

    python app.py      ->  http://127.0.0.1:5000/            Code Input
                           http://127.0.0.1:5000/dashboard   Live dashboard

The dashboard shows GitHub Actions runs (read live from GitHub), local pipeline
runs and Code Input evaluations, and can start the pipeline with one click.
"""
import json
import os
import time
import urllib.request

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import github_live
import history
import runner
from config import AUTO, BLOCKED, GITHUB_REPO, MANUAL, PAGES_URL, REMOTE_HISTORY_URL
from evaluation_engine import evaluate_code

app = Flask(__name__)
app.json.sort_keys = False  # keep pipeline stages in order
REPO_URL = f"https://github.com/{GITHUB_REPO}"
_gh_cache = {}


@app.context_processor
def globals_():
    return {"REPO_URL": REPO_URL, "GITHUB_REPO": GITHUB_REPO, "PAGES_URL": PAGES_URL,
            "REMOTE_HISTORY_URL": REMOTE_HISTORY_URL, "AUTO": AUTO, "MANUAL": MANUAL, "BLOCKED": BLOCKED}


@app.route("/")
def home():
    return render_template("code_input.html")


@app.route("/evaluate", methods=["POST"])
def evaluate():
    code = request.form.get("code", "").strip()
    if not code:
        return "No code submitted.", 400
    evaluation = evaluate_code(code)
    risk = evaluation["risk"]
    status = {AUTO: "DEPLOYED", MANUAL: "WAITING APPROVAL", BLOCKED: "BLOCKED"}[risk["decision"]]
    first = code.strip().splitlines()[0][:70]
    run_id = history.add({
        "source": "code input", "commit": "", "message": f"Code input: {first}", "author": "web user",
        "risk": risk, "decision": risk["decision"], "risk_score": risk["risk_score"], "status": status,
        "quality": evaluation["quality_detail"], "security": evaluation["security_detail"],
        "stages": {
            "Syntax Check": {"status": evaluation["syntax"], "detail": "py_compile"},
            "Code Quality": {"status": evaluation["quality"], "detail": f"{evaluation['quality_detail']['issue_count']} issues"},
            "Security Scan": {"status": evaluation["security"], "detail": f"{evaluation['security_detail']['high']} high, "
                                                                          f"{evaluation['security_detail']['medium']} medium"},
            "Risk Gate": {"status": risk["decision"], "detail": f"risk {risk['risk_score']}/100"},
        },
        **({"deployed_at": history.now()} if status == "DEPLOYED" else {}),
    }, history.LOCAL_HISTORY_FILE)
    return render_template("evaluation_result.html", evaluation=evaluation, code=code, run_key=f"local-{run_id}",
                           run_id=run_id)


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", STATIC=False, GITHUB_LIVE=github_live.available())


@app.route("/run/<key>")
def run_detail(key):
    run = history.get_by_key(key)
    if not run:
        abort(404)
    return render_template("run_detail.html", run=run)


@app.route("/run/<key>/review", methods=["POST"])
def review(key):
    run = history.get_by_key(key)
    if not run or not key.startswith("local-") or run.get("status") != "WAITING APPROVAL":
        abort(400)
    run_id = run["id"]
    reviewer = request.form.get("reviewer", "").strip() or "Reviewer"
    note = request.form.get("note", "").strip()
    if request.form.get("action") == "approve":
        from deploy import deploy_application
        history.update(run_id, history.LOCAL_HISTORY_FILE, review_note=note)
        deploy_application(None, approved_by=reviewer, build=False)
        history.update(run_id, history.LOCAL_HISTORY_FILE, status="DEPLOYED", approved_by=reviewer,
                       approved_at=history.now(), deployed_at=history.now())
    else:
        history.update(run_id, history.LOCAL_HISTORY_FILE, status="REJECTED", rejected_by=reviewer, review_note=note,
                       reviewed_at=history.now())
    if request.headers.get("Accept") == "application/json":
        return jsonify(history.get_by_key(key))
    return redirect(url_for("run_detail", key=key))


@app.route("/api/history")
def api_history():
    return jsonify(history.load_all())


@app.route("/api/pipeline/run", methods=["POST"])
def api_pipeline_run():
    data = request.get_json(silent=True) or request.form
    scenario, custom = data.get("scenario"), None
    try:
        if data.get("code") is not None:
            custom = runner.custom_change(data.get("code"), data.get("filename"), data.get("message"))
        elif scenario and scenario not in runner.SCENARIOS:
            raise ValueError("Unknown scenario")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not runner.start(scenario, custom=custom):
        return jsonify({"error": "A pipeline run is already in progress"}), 409
    return jsonify(runner.status()), 202


@app.route("/api/pipeline/status")
def api_pipeline_status():
    return jsonify(runner.status())


def github_api(path, max_age=60):
    """GET api.github.com (public repo, no token needed), cached so we stay inside the rate limit."""
    hit = _gh_cache.get(path)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    if os.environ.get("RISKGATE_OFFLINE"):
        raise OSError("offline")
    req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/{path}",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "risk-gate-dashboard"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 - fixed https URL
        data = json.loads(resp.read().decode("utf-8"))
    _gh_cache[path] = (time.time(), data)
    return data


@app.route("/api/github/runs")
def api_github_runs():
    """Latest GitHub Actions workflow runs and the jobs of the newest one."""
    try:
        data = github_api("actions/runs?per_page=8")
        runs = [{k: r.get(k) for k in ("id", "run_number", "display_title", "status", "conclusion", "event",
                                         "created_at", "updated_at", "html_url", "head_sha")} for r in data.get("workflow_runs", [])]
        jobs = []
        if runs:
            done = runs[0]["status"] == "completed"
            jd = github_api(f"actions/runs/{runs[0]['id']}/jobs", max_age=3600 if done else 20)
            jobs = [{k: j.get(k) for k in ("name", "status", "conclusion", "html_url", "started_at", "completed_at")}
                    for j in jd.get("jobs", [])]
        return jsonify({"available": True, "runs": runs, "jobs": jobs})
    except (OSError, ValueError) as exc:
        return jsonify({"available": False, "error": str(exc)[:120], "runs": [], "jobs": []})


@app.route("/api/github/push", methods=["POST"])
def api_github_push():
    """Commit the dashboard's code to GitHub: the real CI/CD workflow starts on it."""
    data = request.get_json(silent=True) or {}
    if not github_live.available():
        return jsonify({"error": "GitHub token not set (see README: github_token.txt)"}), 400
    try:
        change = runner.custom_change(data.get("code"), data.get("filename"), data.get("message"))
        (filename, code), = change["files"].items()
        sha = github_live.push_code(filename, code, change["message"])
    except (ValueError, github_live.GitHubError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"sha": sha, "commit_url": f"{REPO_URL}/commit/{sha}"}), 201


@app.route("/api/github/track/<sha>")
def api_github_track(sha):
    try:
        return jsonify(github_live.track(sha))
    except github_live.GitHubError as exc:
        return jsonify({"found": False, "error": str(exc)}), 502


@app.route("/api/github/review", methods=["POST"])
def api_github_review():
    data = request.get_json(silent=True) or {}
    try:
        github_live.review(int(data.get("run_id")), data.get("action") == "approve", data.get("comment", ""))
    except (TypeError, ValueError, github_live.GitHubError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "Intelligent CI/CD Risk Gate"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False, threaded=True)
