"""Flask web app: Code Input, Evaluation Result and the live Risk Gate Dashboard.

    python app.py      ->  http://127.0.0.1:5000/            Code Input
                           http://127.0.0.1:5000/dashboard   Live dashboard
"""
import os

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import history
from config import AUTO, BLOCKED, MANUAL
from evaluation_engine import evaluate_code

app = Flask(__name__)
app.json.sort_keys = False  # keep pipeline stages in order
REPO_URL = os.environ.get("RISKGATE_REPO_URL", "https://github.com/amirthasri0313-svg/Intelligent_CICD_Risk_Gate")


@app.context_processor
def globals_():
    return {"REPO_URL": REPO_URL, "AUTO": AUTO, "MANUAL": MANUAL, "BLOCKED": BLOCKED}


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
    })
    return render_template("evaluation_result.html", evaluation=evaluation, code=code, run_id=run_id)


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/run/<int:run_id>")
def run_detail(run_id):
    run = history.get(run_id)
    if not run:
        abort(404)
    return render_template("run_detail.html", run=run)


@app.route("/run/<int:run_id>/review", methods=["POST"])
def review(run_id):
    run = history.get(run_id)
    if not run or run.get("status") != "WAITING APPROVAL":
        abort(400)
    reviewer = request.form.get("reviewer", "").strip() or "Reviewer"
    note = request.form.get("note", "").strip()
    if request.form.get("action") == "approve":
        from deploy import deploy_application
        history.update(run_id, review_note=note)
        deploy_application(run_id, approved_by=reviewer)
    else:
        history.update(run_id, status="REJECTED", rejected_by=reviewer, review_note=note, reviewed_at=history.now())
    return redirect(url_for("run_detail", run_id=run_id))


@app.route("/api/history")
def api_history():
    return jsonify(history.load())


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "Intelligent CI/CD Risk Gate"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
