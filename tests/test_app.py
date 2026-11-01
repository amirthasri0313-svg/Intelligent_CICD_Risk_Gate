import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

import history  # noqa: E402
from app import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(history, "REPORT_DIR", tmp_path)
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
    assert client.get("/run/1").status_code == 200
    assert client.get("/run/99").status_code == 404


def test_manual_approval_flow(client):
    code = "import requests\n\ndef get(u):\n    return requests.get(u, timeout=5, verify=False).json()\n"
    client.post("/evaluate", data={"code": code})
    run = client.get("/api/history").get_json()[-1]
    assert run["status"] == "WAITING APPROVAL"
    client.post(f"/run/{run['id']}/review", data={"action": "approve", "reviewer": "Team Lead"})
    run = client.get("/api/history").get_json()[-1]
    assert run["status"] == "DEPLOYED" and run["approved_by"] == "Team Lead"
