"""Tests for the pipeline stages: change analysis, quality, security, ML features,
risk gate (GitHub summary + outputs), history and deployment."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

import change_analyzer  # noqa: E402
import config  # noqa: E402
import deploy  # noqa: E402
import history  # noqa: E402
import ml_risk  # noqa: E402
import quality_check  # noqa: E402
import risk_gate  # noqa: E402
import security_check  # noqa: E402
from evaluation_engine import evaluate_code, run_command  # noqa: E402


@pytest.fixture
def reports(tmp_path, monkeypatch):
    """Send every stage report and the history file to a temporary folder."""
    monkeypatch.setattr(config, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(history, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(history, "LOCAL_HISTORY_FILE", tmp_path / "local_history.json")
    monkeypatch.setattr(config, "SITE_DIR", tmp_path / "site")
    monkeypatch.setenv("RISKGATE_OFFLINE", "1")
    for var in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def write(folder, name, data):
    (folder / f"{name}.json").write_text(json.dumps(data))


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    env = dict(os.environ, GIT_AUTHOR_NAME="Dev", GIT_AUTHOR_EMAIL="dev@example.com",
               GIT_COMMITTER_NAME="Dev", GIT_COMMITTER_EMAIL="dev@example.com")

    def commit(files, message):
        for name, text in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text)
        subprocess.run(["git", "add", "-A"], check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", message], check=True, env=env)

    subprocess.run(["git", "init", "-q"], check=True)
    commit({"app.py": "x = 1\n"}, "Initial commit")
    commit({"app.py": "x = 1\ny = 2\n", "tests/test_app.py": "def test_x():\n    pass\n"}, "Add y with test")
    commit({"requirements.txt": "flask\n", "app.py": "x = 1\ny = 3\n"}, "Fix y value and pin flask")
    monkeypatch.delenv("BASE_SHA", raising=False)
    return commit


def test_change_analysis_reads_last_commit(git_repo):
    c = change_analyzer.analyse()
    assert c["files"] == ["app.py", "requirements.txt"]
    assert c["dependency_changed"] and not c["workflow_changed"]
    assert c["lines_added"] == 2 and c["lines_deleted"] == 1
    assert c["change_score"] == 45
    assert c["source_files"] == ["app.py"] and c["test_files"] == []


def test_change_analysis_uses_base_sha(git_repo, monkeypatch):
    first = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], capture_output=True, text=True).stdout.strip()
    monkeypatch.setenv("BASE_SHA", first)
    c = change_analyzer.analyse()
    assert c["commits"] == 2 and "tests/test_app.py" in c["test_files"]


def test_ml_commit_metrics_have_no_future_leakage(git_repo):
    rows = ml_risk.commit_metrics()
    assert [r["subject"] for r in rows] == ["Initial commit", "Add y with test", "Fix y value and pin flask"]
    assert rows[0]["exp"] == 0 and rows[2]["exp"] == 2
    assert rows[2]["fix"] == 1 and rows[2]["config_change"] == 1
    assert rows[1]["test_ratio"] == 0.5
    vec = ml_risk.vector(rows[2], ["log_la", "rel_la", "nf", "entropy"])
    assert len(vec) == 4 and vec[2] == 2


def test_ml_stage_reports_unavailable_model(reports, monkeypatch):
    monkeypatch.setattr(ml_risk, "MODEL_FILE", reports / "missing.joblib")
    result = ml_risk.run()
    assert result["available"] is False and result["historical_risk"] == 0.0


def test_ml_score_with_trained_model(git_repo):
    try:
        import joblib
        joblib.load(config.MODEL_FILE)
    except Exception:  # model built with a different scikit-learn version
        pytest.skip("trained model not loadable here")
    result = ml_risk.score("")
    assert result["available"] and 0 <= result["historical_risk"] <= 100


def test_quality_and_security_scan_changed_files(reports):
    write(reports, "change", {"files": ["static_analysis.py", "tests/test_app.py", "README.md"]})
    q = quality_check.run()
    assert q["files"] == ["static_analysis.py", "tests/test_app.py"] and q["status"] in ("PASS", "FAIL")
    s = security_check.run()
    assert s["files"] == ["static_analysis.py"]  # tests are not security-scanned
    assert {"high", "medium", "low", "findings"} <= s.keys()


def stage_reports(folder, failed=0, workflow=False, high=0):
    write(folder, "change", {"head": "abc1234", "message": "Change", "author": "Dev", "files": ["app.py"],
                             "files_changed": 1, "change_score": 20, "source_files": ["app.py"],
                             "test_files": ["tests/test_app.py"], "workflow_changed": workflow})
    write(folder, "tests", {"total": 10, "failed": failed, "passed": 10 - failed, "pass_rate": (10 - failed) / 10,
                            "coverage": 0.9, "removed": 0})
    write(folder, "quality", {"tool": "ruff", "issues": [], "issue_count": 0, "max_complexity": 3, "syntax_errors": []})
    findings = [{"severity": "HIGH", "test_id": "B608", "issue": "SQL injection", "file": "app.py", "line": 4}] * high
    write(folder, "security", {"tool": "bandit", "findings": findings, "high": high, "medium": 0, "low": 0, "status": "PASS"})
    write(folder, "ml", {"available": True, "historical_risk": 20.0, "probability": 0.1,
                         "trained_on": "test data", "top_features": []})


def test_risk_gate_auto_deploy_and_deploy(reports):
    stage_reports(reports)
    assert risk_gate.main() == 0
    run = history.load()[-1]
    assert run["decision"] == config.AUTO and run["status"] == "DEPLOYING"
    deploy.deploy_application(run["id"])
    assert history.get(run["id"])["status"] == "DEPLOYED"
    site = reports / "site"
    assert (site / "index.html").exists() and "Deployment Risk Dashboard" in (site / "index.html").read_text(encoding="utf-8")
    assert json.loads((site / "history.json").read_text())[-1]["key"] == f"local-{run['id']}"


def test_risk_gate_manual_approval(reports):
    stage_reports(reports, workflow=True)
    assert risk_gate.main() == 2
    assert history.load()[-1]["status"] == "WAITING APPROVAL"


def test_risk_gate_blocks_and_writes_github_summary(reports, monkeypatch):
    stage_reports(reports, failed=2, high=1)
    summary, output = reports / "summary.md", reports / "output.txt"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    assert risk_gate.main() == 1
    text = summary.read_text(encoding="utf-8")
    assert "RELEASE BLOCKED" in text and "Blockers" in text and "B608" in text
    assert "decision=RELEASE BLOCKED" in output.read_text()
    run = history.load()[-1]
    assert run["run_url"] == "https://github.com/me/repo/actions/runs/42" and run["source"] == "github actions"


def test_history_update_unknown_run(reports):
    assert history.update(99, status="X") is None
    assert history.get(99) is None


def test_run_command_handles_missing_program():
    assert run_command(["definitely-not-a-real-program-xyz"])["success"] is False


def test_evaluate_syntax_error_blocks():
    e = evaluate_code("def broken(:\n    pass\n")
    assert e["syntax"] == "FAIL" and e["risk"]["decision"] == config.BLOCKED


def test_demo_scenario_commits_in_a_temporary_worktree(git_repo, reports, monkeypatch):
    import time

    import runner
    repo = os.getcwd()
    monkeypatch.setattr(runner, "ROOT", __import__("pathlib").Path(repo))
    show = [sys.executable, "-c", "import subprocess; print(subprocess.check_output(['git', 'log', '-1', '--format=%s']).decode())"]
    assert runner.start("dangerous", steps=[("Change Analysis", show)])
    for _ in range(100):
        if not runner.status()["running"]:
            break
        time.sleep(0.1)
    state = runner.status()
    assert state["steps"][0]["name"] == "Code Input" and state["steps"][0]["status"] == "pass"
    assert "Add inventory lookup by SKU" in "\n".join(state["log"])
    assert not os.path.exists(os.path.join(repo, "inventory_lookup.py"))  # the working folder is never touched
    assert "riskgate-demo" not in subprocess.run(["git", "worktree", "list"], capture_output=True, text=True).stdout
    with pytest.raises(ValueError):
        runner.start("unknown")
