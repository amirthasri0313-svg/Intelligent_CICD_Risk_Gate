"""Stage 1 - Code Input / Change Analysis.

Reads the pushed change from git (BASE_SHA..HEAD, default HEAD~1..HEAD):
changed files, lines added/deleted, directories touched, change entropy,
whether it touches CI/CD workflow, dependency or test files, and the
file-type impact score from the first version of this project.
Writes reports/change.json.
"""
import json
import math
import os
import subprocess
import sys

from config import report_path

WORKFLOW = ".github/workflows"
DEPENDENCY_FILES = {"requirements.txt", "package.json", "pyproject.toml", "setup.py", "setup.cfg",
                    "Pipfile", "poetry.lock", "Dockerfile", "docker-compose.yml"}


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def resolve_base(head="HEAD"):
    base = os.environ.get("BASE_SHA", "").strip()
    if base and set(base) != {"0"} and git("cat-file", "-t", base) == "commit":
        return base
    parent = git("rev-parse", f"{head}~1")
    return parent or git("hash-object", "-t", "tree", os.devnull)  # first commit: diff against empty tree


def changed_files(base, head="HEAD"):
    files, added, deleted = [], {}, {}
    for line in git("diff", "--numstat", "-M", base, head).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, d, path = parts
        if "=>" in path:
            path = path.split("=>")[-1].strip(" {}")
        files.append(path)
        added[path] = int(a) if a.isdigit() else 0
        deleted[path] = int(d) if d.isdigit() else 0
    return files, added, deleted


def is_test(path):
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") or "/tests/" in path or name.startswith("test_")


def calculate_change_score(files):
    """File-type impact score (original rule set of this project), 0-100."""
    score = 0
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if WORKFLOW in f:
            score += 30
        elif name in DEPENDENCY_FILES:
            score += 25
        elif is_test(f):
            score += 10
        elif f.endswith(".py"):
            score += 20
        else:
            score += 5
    return min(score, 100)


def analyse(head="HEAD"):
    base = resolve_base(head)
    files, added, deleted = changed_files(base, head)
    churn = [added[f] + deleted[f] for f in files]
    total = sum(churn)
    entropy = 0.0
    if total and len(files) > 1:
        entropy = -sum((c / total) * math.log2(c / total) for c in churn if c) / math.log2(len(files))
    commits = [c for c in git("rev-list", "--no-merges", f"{base}..{head}").split() if c]
    msg = git("log", "-1", "--format=%s", head)
    return {
        "base": base[:10], "head": git("rev-parse", "--short=10", head), "message": msg,
        "author": git("log", "-1", "--format=%an", head), "commits": len(commits),
        "files": files, "files_changed": len(files),
        "lines_added": sum(added.values()), "lines_deleted": sum(deleted.values()),
        "directories": len({f.rsplit("/", 1)[0] if "/" in f else "." for f in files}),
        "entropy": round(entropy, 3),
        "source_files": [f for f in files if f.endswith(".py") and not is_test(f)],
        "test_files": [f for f in files if is_test(f)],
        "workflow_changed": any(WORKFLOW in f for f in files),
        "dependency_changed": any(f.rsplit("/", 1)[-1] in DEPENDENCY_FILES for f in files),
        "change_score": calculate_change_score(files),
    }


if __name__ == "__main__":
    result = analyse()
    report_path("change").write_text(json.dumps(result, indent=2))
    print(f"Change {result['base']}..{result['head']}: {result['message']}")
    print(f"Changed files ({result['files_changed']}), +{result['lines_added']} -{result['lines_deleted']}:")
    for f in result["files"]:
        print(f"  - {f}")
    print(f"\nChange Score: {result['change_score']}/100")
    sys.exit(0)
