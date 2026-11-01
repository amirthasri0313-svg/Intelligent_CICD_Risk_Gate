import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

import history  # noqa: E402
from app import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(history, "LOCAL_HISTORY_FILE", tmp_path / "local_history.json")
    monkeypatch.setattr(history, "REPORT_DIR", tmp_path)
    monkeypatch.setenv("RISKGATE_OFFLINE", "1")
    return app.test_client()


def test_home_shows_code_input(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Submit Code for Evaluation" in response.data


def test_health(client):
    assert client.get("/health").get_json()["status"] == "ok"


def test_empty_code_rejected(client):
    assert client.post("/evaluate", data={"code": "   "}).status_code == 400


def test_safe_code_is_auto_deployed_and_recorded(client):
    code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    response = client.post("/evaluate", data={"code": code})
    assert response.status_code == 200
    assert b"AUTO DEPLOY" in response.data
    runs = client.get("/api/history").get_json()
    assert runs[-1]["status"] == "DEPLOYED"


def test_sql_injection_is_blocked(client):
    code = "def get(con, sku):\n    return con.execute(f\"SELECT * FROM items WHERE sku = '{sku}'\").fetchone()\n"
    response = client.post("/evaluate", data={"code": code})
    assert b"RELEASE BLOCKED" in response.data
    assert client.get("/api/history").get_json()[-1]["status"] == "BLOCKED"


def test_dashboard_and_run_detail(client):
    client.post("/evaluate", data={"code": "x = 1\n"})
    assert client.get("/dashboard").status_code == 200
    assert client.get("/run/local-1").status_code == 200
    assert client.get("/run/local-99").status_code == 404


def test_manual_approval_flow(client):
    code = "import requests\n\ndef get(u):\n    return requests.get(u).json()\n"
    client.post("/evaluate", data={"code": code})
    run = client.get("/api/history").get_json()[-1]
    assert run["status"] == "WAITING APPROVAL"
    client.post(f"/run/{run['key']}/review", data={"action": "approve", "reviewer": "Team Lead"})
    run = client.get("/api/history").get_json()[-1]
    assert run["status"] == "DEPLOYED" and run["approved_by"] == "Team Lead"


def test_github_and_local_runs_are_merged(client, tmp_path):
    (tmp_path / "history.json").write_text(json.dumps([{"id": 1, "source": "github actions", "created_at": "2026-11-01T10:00:00+00:00",
                                                        "status": "DEPLOYED", "decision": "AUTO DEPLOY", "risk_score": 7.8,
                                                        "risk": {"risk_score": 7.8, "factors": [], "blockers": [], "guards": []},
                                                        "stages": {}, "security": {"findings": []}, "quality": {"issues": []}}]))
    client.post("/evaluate", data={"code": "x = 1\n"})
    keys = [r["key"] for r in client.get("/api/history").get_json()]
    assert keys == ["gh-1", "local-1"]
    assert client.get("/run/gh-1").status_code == 200
    assert client.post("/run/gh-1/review", data={"action": "approve"}).status_code == 400


def test_reject_and_github_panel_offline(client):
    code = "import requests\n\ndef get(u):\n    return requests.get(u).json()\n"
    client.post("/evaluate", data={"code": code})
    run = client.post("/run/local-1/review", data={"action": "reject", "reviewer": "QA"},
                      headers={"Accept": "application/json"}).get_json()
    assert run["status"] == "REJECTED" and run["rejected_by"] == "QA"
    assert client.get("/api/github/runs").get_json()["available"] is False
    page = client.get("/dashboard").data
    assert b"Run through pipeline" in page and b"Risk Calculation" in page


def test_pipeline_runner_api(client, monkeypatch):
    import runner
    steps = [("Change Analysis", [sys.executable, "-c", "print('analysing')"]),
             ("Risk Gate", [sys.executable, "-c", "import sys; sys.exit(1)"])]
    monkeypatch.setattr(runner, "default_steps", lambda: steps)
    assert client.post("/api/pipeline/run").status_code == 202
    for _ in range(100):
        state = client.get("/api/pipeline/status").get_json()
        if not state["running"]:
            break
        time.sleep(0.1)
    assert [s["status"] for s in state["steps"]][:2] == ["pass", "fail"]
    assert "analysing" in "\n".join(state["log"])


def test_custom_code_validation(client):
    assert client.post("/api/pipeline/run", json={"code": "   "}).status_code == 400
    assert client.post("/api/pipeline/run", json={"code": "x = 1", "filename": "../evil.py"}).status_code == 400
    import runner
    change = runner.custom_change("x = 1", "my_mod.py", "")
    assert change["files"] == {"my_mod.py": "x = 1\n"} and change["message"] == "Add my_mod.py"


def test_github_live_needs_token_and_maps_steps(client, monkeypatch):
    import github_live
    monkeypatch.setattr(github_live, "token", lambda: "")
    assert client.post("/api/github/push", json={"code": "x = 1"}).status_code == 400
    monkeypatch.setattr(github_live, "token", lambda: "t")
    monkeypatch.delenv("RISKGATE_OFFLINE")
    calls = []

    def fake(path, method="GET", body=None):
        calls.append((path, method))
        if path.startswith("contents/demo_changes") and method == "GET":
            raise github_live.GitHubError("GitHub 404: not found")
        if method == "PUT":
            return {"commit": {"sha": "abc1234567890"}}
        if path.startswith("actions/runs?head_sha"):
            return {"workflow_runs": [{"id": 9, "run_number": 18, "status": "waiting", "conclusion": None,
                                       "html_url": "u", "display_title": "t", "head_sha": "abc1234567890"}]}
        if path.endswith("/jobs"):
            return {"jobs": [{"name": "Evaluate & Risk Gate", "status": "completed", "conclusion": "success",
                              "steps": [{"name": "Stage 2 · Code quality (Ruff)", "status": "completed", "conclusion": "success"}]}]}
        if path.endswith("pending_deployments") and method == "GET":
            return [{"environment": {"id": 5, "name": "production-approval"}}]
        if path.startswith("contents/reports/history.json"):
            import base64
            return {"content": base64.b64encode(json.dumps([{"id": 7, "commit": "abc1234567"}]).encode()).decode()}
        return {}
    monkeypatch.setattr(github_live, "call", fake)
    assert client.post("/api/github/push", json={"code": "x = 1", "filename": "a.py"}).get_json()["sha"] == "abc1234567890"
    t = client.get("/api/github/track/abc1234567890").get_json()
    assert t["stages"][1]["status"] == "success" and t["pending"][0]["id"] == 5 and t["record"]["key"] == "gh-7"
    assert client.post("/api/github/review", json={"run_id": 9, "action": "approve"}).get_json()["ok"]
    assert ("actions/runs/9/pending_deployments", "POST") in calls
