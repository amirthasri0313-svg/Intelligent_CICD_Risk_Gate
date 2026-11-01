"""Run the pipeline in the background so the dashboard can show each stage live.

The dashboard's buttons call start(); the page polls status() every second and
lights up each stage as it finishes. The stages are the same scripts GitHub
Actions runs (see pipeline.STAGES).

Demo scenarios: start("safe" | "risky" | "dangerous") makes a real git commit with
that change in a temporary worktree (your working folder is never touched) and
runs the whole pipeline on it, exactly as GitHub Actions would after a push.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from config import MODEL_FILE, REPORT_DIR, ROOT, SITE_DIR, report_path

_lock = threading.Lock()
_state = {"running": False, "steps": [], "log": [], "result": None, "run_key": None,
          "started_at": None, "finished_at": None, "scenario": None}

SCENARIOS = {
    "safe": {
        "title": "Safe change", "message": "Docs: explain how to open the risk dashboard",
        "files": {"docs/usage.md": "# Using the dashboard\n\nRun `python app.py` and open /dashboard.\n"},
    },
    "risky": {
        "title": "Risky change", "message": "Add price service client and requests dependency",
        "files": {
            "price_client.py": ('"""Client for the external price service."""\n\n\n'
                                "def total(items):\n    return round(sum(i['price'] * i['qty'] for i in items), 2)\n\n\n"
                                "def fetch_prices(url):\n    import requests\n    return requests.get(url).json()\n"),
            "tests/test_price_client.py": ("import os\nimport sys\n\n"
                                           "sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))\n\n"
                                           "from price_client import total  # noqa: E402\n\n\n"
                                           "def test_total():\n    assert total([{'price': 2.5, 'qty': 2}, {'price': 1, 'qty': 3}]) == 8.0\n"),
            "requirements.txt": "+requests>=2.32\n",
        },
    },
    "dangerous": {
        "title": "Dangerous change", "message": "Add inventory lookup by SKU",
        "files": {"inventory_lookup.py": ('"""Look up stock for a SKU."""\n\n\n'
                                          "def stock(con, sku):\n"
                                          "    return con.execute(f\"SELECT qty FROM inventory WHERE sku = '{sku}'\").fetchone()\n")},
    },
}


def default_steps():
    from pipeline import STAGES
    nice = {"ML RISK MODEL": "ML Risk Model"}
    return [(nice.get(name, name.title()), [sys.executable, str(ROOT / script)]) for name, script in STAGES] + [
        ("Risk Gate", [sys.executable, str(ROOT / "risk_gate.py")])]


def _log(line):
    _state["log"].append(line.rstrip()[:300])
    del _state["log"][:-200]


def _run(cmd, env, cwd=ROOT):
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        _log(line)
    return proc.wait()


def _git(args, cwd, env=None):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=False)


def _prepare_scenario(name, env):
    """Commit the scenario's change on top of HEAD in a temporary git worktree."""
    sc = SCENARIOS[name]
    work = Path(tempfile.mkdtemp(prefix="riskgate-demo-")) / "repo"
    r = _git(["worktree", "add", "--detach", str(work), "HEAD"], ROOT)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "git worktree failed")
    _log(f"Code input: new commit \"{sc['message']}\"")
    for rel, text in sc["files"].items():
        path = work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if text.startswith("+"):  # append a line, e.g. a new dependency
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            text = old + ("" if old.endswith("\n") or not old else "\n") + text[1:]
        path.write_text(text, encoding="utf-8")
        _log(f"  changed {rel}")
    genv = dict(env, GIT_AUTHOR_NAME="Demo developer", GIT_AUTHOR_EMAIL="demo@example.com",
                GIT_COMMITTER_NAME="Demo developer", GIT_COMMITTER_EMAIL="demo@example.com")
    _git(["add", "-A"], work, genv)
    r = _git(["commit", "-q", "-m", sc["message"]], work, genv)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "git commit failed")
    return work


def _cleanup(work):
    if work:
        _git(["worktree", "remove", "--force", str(work)], ROOT)
        shutil.rmtree(work.parent, ignore_errors=True)
        _git(["worktree", "prune"], ROOT)


def _worker(scenario):
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
               RISKGATE_REPORTS=str(REPORT_DIR), RISKGATE_MODEL=str(MODEL_FILE), RISKGATE_SITE_DIR=str(SITE_DIR))
    for var in ("GITHUB_ACTIONS", "BASE_SHA", "GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT"):
        env.pop(var, None)  # local runs go to the local history
    work, cwd, code = None, ROOT, 0
    try:
        if scenario:
            step = _state["steps"][0]
            step.update(status="running", started=time.time())
            work = cwd = _prepare_scenario(scenario, env)
            env["RISKGATE_ROOT"] = str(work)
            step.update(status="pass", seconds=round(time.time() - step["started"], 1))
        for step in _state["steps"]:
            if step["status"] != "pending":
                continue
            step.update(status="running", started=time.time())
            _log(f"$ {' '.join(os.path.basename(c) for c in step['cmd'])}")
            code = _run(step["cmd"], env, cwd)
            is_gate = step["name"] == "Risk Gate"
            step.update(status=("pass" if code == 0 else "warn" if is_gate and code == 2 else "fail"),
                        seconds=round(time.time() - step["started"], 1), code=code)
            if code == 0:
                _flag_findings(step)
            if code != 0 and not is_gate:
                _state["result"] = "ERROR"
                break
        else:
            _finish_release(code, env)
    except (OSError, RuntimeError) as exc:
        _log(f"ERROR: {exc}")
        for step in _state["steps"]:
            if step["status"] == "running":
                step["status"] = "fail"
        _state["result"] = "ERROR"
    finally:
        _cleanup(work)
        _state.update(running=False, finished_at=time.time())


def _flag_findings(step):
    """A stage can finish fine and still find problems: show those on the step."""
    try:
        if step["name"].startswith("Security"):
            sec = json.loads(report_path("security").read_text(encoding="utf-8"))
            if sec.get("high") or sec.get("medium"):
                step.update(status="warn", detail=f"{sec.get('high', 0)} high, {sec.get('medium', 0)} medium")
        elif step["name"].startswith("Tests"):
            t = json.loads(report_path("tests").read_text(encoding="utf-8"))
            if t.get("failed"):
                step.update(status="warn", detail=f"{t['failed']} failing")
    except (OSError, ValueError):
        pass


def _finish_release(code, env):
    try:
        rec = json.loads(report_path("latest").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _state["result"] = "ERROR"
        return
    _state["run_key"] = f"local-{rec.get('id')}"
    release = {"name": "Release", "cmd": [], "status": "running", "started": time.time()}
    _state["steps"].append(release)
    if code == 0:
        rc = _run([sys.executable, str(ROOT / "deploy.py"), "--run-id", str(rec["id"])], env)
        release.update(status="pass" if rc == 0 else "fail", detail="deployed")
        _state["result"] = "DEPLOYED" if rc == 0 else "ERROR"
    elif code == 2:
        release.update(status="warn", detail="waiting for approval")
        _log("Manual approval required: approve or reject it on the dashboard.")
        _state["result"] = "WAITING APPROVAL"
    else:
        release.update(status="fail", detail="blocked")
        _log("Release blocked: fix the blockers and run again.")
        _state["result"] = "BLOCKED"
    release["seconds"] = round(time.time() - release["started"], 1)


def start(scenario=None, steps=None):
    """Start a pipeline run; returns False when one is already running."""
    if scenario and scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario}")
    with _lock:
        if _state["running"]:
            return False
        steps = steps or default_steps()
        first = [{"name": "Code Input", "cmd": [], "status": "pending"}] if scenario else []
        _state.update(running=True, log=[], result=None, run_key=None, started_at=time.time(), finished_at=None,
                      scenario=scenario, steps=first + [{"name": n, "cmd": c, "status": "pending"} for n, c in steps])
    threading.Thread(target=_worker, args=(scenario,), daemon=True).start()
    return True


def status():
    s = dict(_state)
    s["steps"] = [{k: v for k, v in st.items() if k not in ("cmd", "started")} for st in _state["steps"]]
    s["log"] = _state["log"][-60:]
    s["elapsed"] = round((s["finished_at"] or time.time()) - s["started_at"], 1) if s["started_at"] else 0
    return s
