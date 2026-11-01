"""Stage 2d - Machine-learning historical risk (the "intelligent" part).

A Gradient Boosting model was trained on 18,505 real commits from six open-source
Python projects (Flask, Requests, Werkzeug, Jinja, Click, HTTPX). Each commit was
labelled risk-inducing or not with the SZZ algorithm (a later bug fix changed
lines it introduced). The model predicts, from Just-In-Time change metrics
(Kamei et al., 2013), how likely a new commit is to introduce a defect.

This stage computes those metrics for every commit in the push from this
repository's own git history, scores them, and reports the riskiest one as a
percentile H (0-100) of the training distribution. Writes reports/ml.json.
"""
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from config import MODEL_FILE, report_path

FIX = re.compile(r"\b(fix(e[sd])?|bug|defect|patch|issue|error|crash|regression|hotfix|repair)\b", re.I)
NOT_FIX = re.compile(r"\b(prefix|suffix|fixture|fixtures|typo|docs?|changelog|readme)\b", re.I)
TEST = re.compile(r"(^|/)(tests?|testing)(/|$)|(^|/)test_[^/]*\.py$|_test\.py$")
CONFIG = re.compile(r"(requirements.*\.txt|setup\.(py|cfg)|pyproject\.toml|Pipfile|poetry\.lock|Dockerfile|"
                    r"docker-compose.*\.ya?ml|\.github/workflows/.*|tox\.ini|\.env.*|.*\.ini)$")

FEATURE_HELP = {
    "log_la": "lines added", "log_ld": "lines deleted", "log_nf": "files changed", "nd": "directories touched",
    "ns": "subsystems touched", "entropy": "how scattered the change is", "log_lt": "size of touched files",
    "fix": "bug-fix commit", "log_ndev": "developers who touched these files", "log_age": "days since files last changed",
    "log_nuc": "earlier changes to these files", "log_exp": "author experience", "test_ratio": "share of test files",
    "config_change": "config / dependency change", "hour": "hour of commit", "weekend": "weekend commit",
}


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, errors="replace", check=False).stdout


def parse_log(rev="HEAD"):
    """Yield (sha, author, timestamp, subject, {file: (added, deleted)}) oldest first."""
    log = _git("log", rev, "--reverse", "--no-merges", "-M", "--numstat", "--format=\x1e%H\x1f%an\x1f%at\x1f%s\x1d")
    for block in log.split("\x1e")[1:]:
        head, _, num = block.partition("\x1d")
        sha, author, ts, subject = head.split("\x1f", 3)
        churn = {}
        for line in num.strip().splitlines():
            p = line.split("\t")
            if len(p) == 3:
                path = p[2].split("=>")[-1].strip(" {}") if "=>" in p[2] else p[2]
                churn[path] = (int(p[0]) if p[0].isdigit() else 0, int(p[1]) if p[1].isdigit() else 0)
        if churn:
            yield sha, author, int(ts), subject, churn


def entropy(churn):
    total = sum(a + d for a, d in churn.values())
    if not total or len(churn) < 2:
        return 0.0
    return -sum(((a + d) / total) * math.log2((a + d) / total) for a, d in churn.values() if a + d) / math.log2(len(churn))


class History:
    """What was known about files and authors before each commit."""

    def __init__(self):
        self.devs, self.last, self.nchg, self.size = defaultdict(set), {}, defaultdict(int), defaultdict(int)
        self.a_n, self.a_t, self.a_sub = defaultdict(int), defaultdict(list), defaultdict(int)

    def metrics(self, author, ts, subject, churn):
        files = list(churn)
        subs = {f.split("/")[0] if "/" in f else "." for f in files}
        ages = [(ts - self.last[f]) / 86400 for f in files if f in self.last]
        dt = datetime.fromtimestamp(ts, timezone.utc)
        return {
            "ns": len(subs), "nd": len({f.rsplit("/", 1)[0] if "/" in f else "." for f in files}), "nf": len(files),
            "entropy": entropy(churn), "la": sum(a for a, _ in churn.values()), "ld": sum(d for _, d in churn.values()),
            "lt": sum(self.size[f] for f in files) / len(files),
            "fix": int(bool(FIX.search(subject)) and not NOT_FIX.search(subject)),
            "ndev": len(set().union(*(self.devs[f] for f in files))), "age": sum(ages) / len(ages) if ages else 0.0,
            "nuc": sum(self.nchg[f] for f in files), "exp": self.a_n[author],
            "rexp": sum(1 / (1 + (ts - t) / (365 * 86400)) for t in self.a_t[author][-500:]),
            "sexp": sum(self.a_sub[(author, s)] for s in subs),
            "test_ratio": sum(1 for f in files if TEST.search(f)) / len(files),
            "config_change": int(any(CONFIG.search(f) for f in files)), "hour": dt.hour, "weekend": int(dt.weekday() >= 5),
        }

    def record(self, author, ts, churn):
        for f, (a, d) in churn.items():
            self.devs[f].add(author)
            self.last[f] = ts
            self.nchg[f] += 1
            self.size[f] = max(0, self.size[f] + a - d)
        self.a_n[author] += 1
        self.a_t[author].append(ts)
        for s in {f.split("/")[0] if "/" in f else "." for f in churn}:
            self.a_sub[(author, s)] += 1


def commit_metrics(rev="HEAD"):
    """JIT metrics for every non-merge commit, computed in time order (no future leakage)."""
    hist, rows = History(), []
    for sha, author, ts, subject, churn in parse_log(rev):
        rows.append({"sha": sha, "subject": subject, **hist.metrics(author, ts, subject, churn)})
        hist.record(author, ts, churn)
    return rows


def vector(row, features):
    d = dict(row)
    for c in ["nf", "la", "ld", "lt", "ndev", "age", "nuc", "exp", "rexp", "sexp"]:
        d[f"log_{c}"] = math.log1p(max(0.0, d[c]))
    denom = max(1.0, d["lt"] * d["nf"])
    d["rel_la"] = min(10.0, d["la"] / denom)
    d["rel_ld"] = min(10.0, d["ld"] / denom)
    return [float(d[f]) for f in features]


def score(base, head="HEAD"):
    import joblib
    bundle = joblib.load(MODEL_FILE)
    model, features = bundle["model"], bundle["features"]
    ref = np.sort(np.asarray(bundle["train_proba"]))
    wanted = set(_git("rev-list", "--no-merges", f"{base}..{head}").split()) if base else set()
    rows = commit_metrics(head)
    push = [r for r in rows if r["sha"] in wanted] or rows[-1:]
    proba = model.predict_proba(np.array([vector(r, features) for r in push]))[:, 1]
    i = int(np.argmax(proba))
    pct = float(np.searchsorted(ref, proba[i]) / len(ref) * 100)
    top = [(f, FEATURE_HELP.get(f, f)) for f, _ in bundle.get("importance", [])[:4]]
    r = push[i]
    return {
        "available": True, "historical_risk": round(pct, 1), "probability": round(float(proba[i]), 4),
        "commit": r["sha"][:10], "commit_message": r["subject"], "commits_scored": len(push),
        "metrics": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k not in ("sha", "subject")},
        "top_features": top,
        "trained_on": "18,505 SZZ-labelled commits from Flask, Requests, Werkzeug, Jinja, Click and HTTPX",
    }


def run():
    try:
        change = json.loads(report_path("change").read_text())
        base = _git("rev-parse", change["base"]).strip()
    except (OSError, ValueError, KeyError):
        base = ""
    try:
        return score(base)
    except Exception as exc:  # model missing or incompatible: the gate still works on E only
        return {"available": False, "historical_risk": 0.0, "error": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    result = run()
    report_path("ml").write_text(json.dumps(result, indent=2))
    if result["available"]:
        print(f"ML historical risk H = {result['historical_risk']} (probability {result['probability']}) "
              f"for commit {result['commit']}: {result['commit_message']}")
    else:
        print(f"ML model not available, gate will use evaluation risk only ({result['error']})")
    sys.exit(0)
