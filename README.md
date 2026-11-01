# Intelligent CI/CD Risk Gate for Automated Deployment Risk Assessment

A DevOps pipeline on **GitHub Actions** that scores the risk of every push (0–100)
and decides whether it may be deployed:

```
 Code Input ──► Automated Evaluation ──► Risk Calculation ──► Risk Gate ──► Dashboard ──► Release / Manual Approval
 git push        tests + coverage          E = rule factors      0-30  auto     history.json    deploy job
 or Code Input   Ruff (quality)            H = ML model on       31-70 approval  + Flask         or GitHub reviewer
 page            Bandit (security)         commit history        71+   blocked   dashboard       approves first
                 complexity, change size   R = 0.65E + 0.35H
```

## Where each stage runs

| Stage | File | In GitHub Actions |
|---|---|---|
| 1 Code input / change analysis | `change_analyzer.py` | step "Stage 1 · Change analysis" |
| 2 Tests + coverage | `run_tests.py` (pytest, pytest-cov) | step "Stage 2 · Automated tests and coverage" |
| 2 Code quality | `quality_check.py` (Ruff) | step "Stage 2 · Code quality (Ruff)" |
| 2 Security | `security_check.py` (Bandit) | step "Stage 2 · Security scan (Bandit)" |
| 3 ML historical risk | `ml_risk.py` + `model/jit_model.joblib` | step "Stage 3 · ML historical risk" |
| 3 Risk calculation | `release_readiness.py` | step "Stage 3 · Risk calculation" |
| 4 Risk gate | `risk_gate.py` | step "Stage 4 · Risk gate decision" + **job summary table** |
| 5 Dashboard | `reports/history.json`, `app.py` | step "Stage 5 · Save run to dashboard history" |
| 6 Release | `deploy.py`, `export_site.py` | job **Auto deploy** or **Manual approval, then deploy** builds the release, job **Release to GitHub Pages** publishes it |

The ML model (Gradient Boosting) was trained on 18,505 commits of Flask, Requests,
Werkzeug, Jinja, Click and HTTPX, labelled with the SZZ algorithm (ROC-AUC 0.80 on
held-out commits). It reads this repository's own git history to judge each new commit.

## Live release (GitHub Pages)

Every change the gate lets through is really deployed: the deploy job builds the
release package (the Risk Gate dashboard as a static site) and the **Release to
GitHub Pages** job publishes it to

**https://amirthasri0313-svg.github.io/Intelligent_CICD_Risk_Gate/**

Blocked or rejected changes never reach this URL. The live site reads the run
history and the GitHub Actions runs straight from GitHub, so it stays current.

## Dashboard

`python app.py` → http://127.0.0.1:5000/dashboard

- the six stages of the title as a live flow, coloured by the latest run
- **▶ Run pipeline now**: runs every stage on your last commit and lights them up live, with the log
- GitHub Actions panel: latest workflow runs and jobs, read live from GitHub
- risk trend (R, E and H with the 30/70 bands), gate decision donut, E/H contribution per run
- all runs with filters and search; click a run for stages, factors, findings, ML signals and approve / reject

## One-time GitHub setup (2 minutes)

1. **Settings → Environments → New environment → `production-approval`**
   → tick **Required reviewers** → add yourself → **Save protection rules**.
   (This is what pauses medium-risk deployments until a human approves.)
2. **Settings → Environments → New environment → `production`** (no rules).
3. **Settings → Actions → General → Workflow permissions → Read and write permissions → Save**
   (lets the pipeline save each run to `reports/history.json`).
4. **Settings → Pages → Build and deployment → Source: GitHub Actions** (the live release).

## Run it

```bash
pip install -r requirements.txt
python -m pytest            # unit tests
python pipeline.py          # the full pipeline locally on the last commit
python app.py               # http://127.0.0.1:5000  (Code Input)  and  /dashboard
git pull                    # brings GitHub Actions runs into the local dashboard
```

## Review demo (what to show)

1. **GitHub → Actions**: open the latest run → stages as steps → scroll to the
   **Risk Gate** summary (score, factor table, blockers, decision).
2. **Low risk**: edit a comment or docstring, commit, push → the **Auto deploy** job runs.
3. **Medium risk**: change `requirements.txt` or the workflow → the run stops at
   **Manual approval** → *Review deployments → Approve and deploy*.
4. **High risk**: add a file with a SQL injection (sample on the Code Input page),
   push → the gate step turns red: **RELEASE BLOCKED**. Then delete the file and push again.
5. **Dashboard** (`python app.py`, `/dashboard`, after `git pull`): every run with
   its source, score, decision and a link to the GitHub run; approve / reject local runs.
6. **Code Input** page: paste code → instant score and decision.

Project by Amirtha, MCA, PMIST Thanjavur.
