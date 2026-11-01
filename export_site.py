"""Build the release package: a static copy of the Risk Gate dashboard.

The deploy stage runs this, and GitHub Actions publishes the folder to GitHub Pages,
so every change that passes the gate is really released to a public URL:
    https://<user>.github.io/<repo>/

    python export_site.py          ->  site/index.html + site/history.json
"""
import json
import os

import config
import history


def build(out_dir=None):
    from app import app  # imported here so the deploy stage only needs Flask when it builds

    out = out_dir or config.SITE_DIR
    out.mkdir(parents=True, exist_ok=True)
    in_actions = bool(os.environ.get("GITHUB_ACTIONS"))
    runs = [dict(r, key=f"gh-{r.get('id')}") for r in history.load(config.HISTORY_FILE)] if in_actions \
        else history.load_all(offline=True)
    with app.test_request_context("/dashboard"):
        from flask import render_template
        html = render_template("dashboard.html", STATIC=True, built_at=history.now(),
                               commit=os.environ.get("GITHUB_SHA", "")[:10])
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "history.json").write_text(json.dumps(runs, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(f"Release package built in {build()}")
