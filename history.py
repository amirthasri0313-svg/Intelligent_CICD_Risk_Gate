"""Pipeline history.

Two files, so a local demo never conflicts with what GitHub Actions commits:
  reports/history.json        runs recorded by GitHub Actions (committed by the pipeline)
  reports/local_history.json  local pipeline runs and Code Input evaluations (not committed)

The dashboard shows both. GitHub runs are read live from the repository on GitHub
(raw history.json, cached for 30 s), falling back to the local copy when offline.
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

from config import HISTORY_FILE, LOCAL_HISTORY_FILE, REMOTE_HISTORY_URL, REPORT_DIR

_cache = {"time": 0.0, "runs": None}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _target():
    """GitHub Actions writes the committed history; everything else writes the local one."""
    return HISTORY_FILE if os.environ.get("GITHUB_ACTIONS") else LOCAL_HISTORY_FILE


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def load(path=None):
    return _read(path or _target())


def save(runs, path=None):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (path or _target()).write_text(json.dumps(runs, indent=1), encoding="utf-8")


def add(record, path=None):
    runs = load(path)
    record["id"] = max((r.get("id", 0) for r in runs), default=0) + 1
    record.setdefault("created_at", now())
    runs.append(record)
    save(runs, path)
    return record["id"]


def update(run_id, path=None, **fields):
    runs = load(path)
    for r in runs:
        if r.get("id") == run_id:
            r.update(fields)
            save(runs, path)
            return r
    return None


def get(run_id, path=None):
    return next((r for r in load(path) if r.get("id") == run_id), None)


def github_runs(max_age=30, offline=False):
    """GitHub Actions runs: fresh from the repository on GitHub, else the local copy."""
    if offline or os.environ.get("RISKGATE_OFFLINE") or not REMOTE_HISTORY_URL:
        return _read(HISTORY_FILE)
    if _cache["runs"] is not None and time.time() - _cache["time"] < max_age:
        return _cache["runs"]
    try:
        url = f"{REMOTE_HISTORY_URL}?t={int(time.time())}"
        with urllib.request.urlopen(url, timeout=4) as resp:  # nosec B310 - fixed https URL from config
            runs = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        runs = _read(HISTORY_FILE)
    _cache.update(time=time.time(), runs=runs)
    return runs


def load_all(offline=False):
    """All runs for the dashboard, each with a unique key (gh-N or local-N), oldest first."""
    gh = [dict(r, key=f"gh-{r.get('id')}") for r in github_runs(offline=offline)]
    local = [dict(r, key=f"local-{r.get('id')}") for r in _read(LOCAL_HISTORY_FILE)]
    return sorted(gh + local, key=lambda r: r.get("created_at", ""))


def get_by_key(key):
    return next((r for r in load_all() if r["key"] == key), None)
