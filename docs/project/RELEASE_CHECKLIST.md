# Release Checklist — Munder Difflin (SKELETON)

_Owner: Stanley (REL) · Status: skeleton, v0. Items are unchecked until someone has evidence. Tick with proof (command output, CI link, report path) — never from memory._

**Release:** `v____` · **Date:** ____ · **Release owner:** Stanley · **Approver (human):** ____

## 0. Preconditions (stop if any is unmet)
- [ ] Tester (QA) GO recorded for this exact commit: report path ____
- [ ] Security (SEC) GO recorded where required: report path ____
- [ ] Boss (god) approval received: message id ____
- [ ] Production/human approval received explicitly (for any production deploy): ____
- [ ] Working in the project's own git repo — **not** the home-directory repo

## 1. Environment (see `docs/environment_report.md`)
- [ ] `scripts/audit_env.sh` re-run on the release machine; no BLOCKER rows
- [ ] `DEPENDENCY_MATRIX.md` pins match what the audit shows

## 2. Secrets and repo hygiene (SEC-004 — CRITICAL) — status as of 2026-10-28, REL

Repo: `munder_difflin/` is its own git repository (`git init`, branch `main`, local only, no remote). The outer home-directory repo was not modified. Hook path is set in this repo's local config: `git config core.hooksPath .githooks` (re-run once per fresh clone).

- [x] **S1** `.gitignore` covers every entry in SECURITY_FINDINGS §3.1 plus `**/.env.local`, `secrets/`, `.pytest_cache/`, `log/`, `reports/`, `.claude/`. Evidence: `.gitignore`; `git add -A` staged 83 files, none matching `.venv/`, `node_modules/`, `__pycache__`, `.pytest_cache`, `.claude`, `.map`, or a real `.env` (only `backend/.env.example`).
- [x] **S4** No `.env` in history. Evidence: `git log --all --diff-filter=A -- "*.env"` printed nothing; repository has 0 commits. **Re-run before every release**: history is empty now, so this is trivially true today.
- [x] **S7** Docker configs: none exist yet (`find` for `Dockerfile*`, `docker-compose*`, `compose*.yml` found nothing). The hook blocks `ENV/ARG <KEY|TOKEN|SECRET|PASSWORD>=value` in Dockerfiles. **Re-check when the first Dockerfile/compose file lands**; use `environment:` pass-through or Docker `secrets:`.
- [x] **S8** Pre-commit secret scan installed: `.githooks/pre-commit` (offline; git + grep + awk). Blocks forbidden file names (`.env`, `.env.*` except `.env.example`, `*.key`, `*.pem`, `*.secret`, `secrets/`, ssh private keys) and added lines matching: sk-/nvapi-/AKIA/GitHub/Slack/Google key shapes, private-key blocks, `*_KEY|SECRET|TOKEN|PASSWORD = <20+ chars>`, Dockerfile `ENV` secrets. Prints file:line and rule only, never the value. Escape for a deliberate false positive: `secret-scan: allow` on that line.
  - Hook tested with fakes built at runtime (nothing stored): `.env` file, sk- key, key assignment, private-key header, Dockerfile `ENV` secret all blocked (exit 1); a line marked `secret-scan: allow` and `os.environ.get("ANTHROPIC_API_KEY")` were not flagged. Runtime on the 83-file stage: 0.2 s.
- [x] **Gate for the initial commit — MET, committed as `df9570e`** (116 files, local only). Pam replaced the literal fake keys with runtime-built ones (MD-DEV-005) and the static test no longer fails. Evidence: `backend/.venv/bin/python -m pytest -c tests/pytest.ini tests/static -q` → 2 passed; `.githooks/pre-commit` → exit 0 on the staged set; S4 re-run after the commit: `git log --all --diff-filter=A -- "*.env"` → 0 entries, and tracked env-style files are only `backend/.env.example` and `frontend/.env.example`.
- [ ] No API keys in frontend bundle (`grep` on built assets) — no frontend exists yet; **not executed**.
- [ ] Rest of §3.2 (S2, S3, S5, S6, S9, S10) belongs to Pam/Dwight; S3 grep result today: only runtime-built or masked test fixtures and the scanner's own regexes; no real key shapes in `app/` code.

## 3. Install scripts (SEC-008 — HIGH)

Scope today: `scripts/audit_env.sh` is the only script in the repo.

- [x] No `sudo` — the only occurrence is the comment "or uses sudo". Evidence: `grep -n sudo scripts/audit_env.sh`.
- [x] Idempotent and read-only — three consecutive runs, exit 0, identical output apart from RAM/disk figures.
- [x] No `curl | bash` / `wget | sh` — `curl` appears only as `curl --version`.
- [x] No package installs inside scripts (`apt`/`pip install` absent). System installs are listed for the human in `docs/environment_report.md` §4 and are run by the human.
- [x] Downloads: none performed. Rule for future scripts: any download needs a pinned URL plus a published SHA-256 checked before use.
- [ ] `shellcheck` clean — `shellcheck` is not installed on this machine; **not executed** (`bash -n` syntax check passes for `audit_env.sh` and `.githooks/pre-commit`).
- [ ] Re-review every new script added by other agents before release.

## 4. Build and dependencies (SEC-014 — MEDIUM)

Desktop shell decision: **Electron** (no Rust / WebKitGTK installs). No `package.json` exists yet, so the Node items cannot be executed.

- [ ] `package-lock.json` committed — no frontend yet; **not executed**
- [ ] CI runs `npm audit --audit-level=high` (fail on high/critical) — no CI exists; **not executed**. Local equivalent to run before release: `npm audit --audit-level=high`
- [ ] Python dependency audit — `backend/requirements.txt` exists; tool (`pip-audit`) not installed; **not executed**
- [ ] Production frontend build has no source maps — `*.map` is git-ignored; build config must set `sourcemap: false` for production; **not executed** (check `find dist -name '*.map'` is empty)
- [ ] Electron settings (SEC-015): `nodeIntegration: false`, `contextIsolation: true`, `webSecurity: true`, preload via `contextBridge`, CSP limited to `http://localhost:8000` and `ws://localhost:8000` — review when `main.js` exists; **not executed**
- [x] Python lockfile: `backend/requirements.lock` (pip freeze of `backend/.venv`, 2026-10-28; closes SEC-004-D1 for now). It includes dev packages (pytest) and has no hashes. Regenerate when `requirements*.txt` changes. ROS dependencies via `rosdep`: TBD
- [ ] Clean build from a fresh clone: command ____ · result ____
- [ ] `colcon build` of `ros2_ws/` clean — `ros2_ws/src` is empty today: ____

## 5. Tests (run by QA, not by the author)
- [ ] Backend unit tests: ____
- [ ] Frontend tests/typecheck/lint: ____
- [ ] Simulation integration test (Gazebo + MoveIt + controllers): ____
- [ ] Safety/validation-layer tests (invalid AI output rejected): ____

## 6. Git and PR
- [ ] Feature branch from up-to-date `main`; no force-push, no `--no-verify`
- [ ] Commits use conventional messages; attribution lines present
- [ ] PR opened, description lists changes + test evidence + risks
- [ ] CI green on the PR head commit: link ____
- [ ] Review approvals: ____
- [ ] Merged by: ____ · merge commit: ____

## 7. Deploy / package
- [ ] Artifact built: name ____ · checksum (sha256) ____
- [ ] Deploy target and method: ____ (human approval above)
- [ ] Version tag created: ____

## 8. Post-release verification (proof required)
- [ ] Health check: command/URL ____ · output ____
- [ ] Smoke test: one NL command end-to-end in simulation: ____
- [ ] Logs show no errors in first ____ minutes
- [ ] If any item above is "not executed", it is listed in the release report as such

## 9. Rollback notes
- **Previous good version/commit:** ____
- **Rollback trigger:** health check fails, safety validation bypass, secret exposure, or crash loop
- **Steps:** (1) stop service/app; (2) check out/redeploy previous tag; (3) restore config; (4) re-run section 8; (5) notify Boss
- **Data/state to restore:** ____ (none expected for simulation-only releases)
- **Who can authorise rollback:** Boss / human

## 10. Release report
- [ ] Handoff report filed with real command output, commit SHAs and URLs (nothing fabricated)
