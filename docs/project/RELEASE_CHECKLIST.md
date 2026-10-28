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
- [x] Post-install audit run 2026-10-28T02:40:46Z after the human's apt install: exit 0, empty stderr. No BLOCKER rows; MoveIt 2.12.4, ros2_control 4.48.1, ros2_controllers 4.42.1, gz_ros2_control 1.2.20, Panda and UR packages all PRESENT (`docs/environment_report.md` §5). **Re-run on the release machine before each release.**
- [x] `DEPENDENCY_MATRIX.md` "Installed" column refreshed from that audit. The **Pin** column is still TBD for the ROS packages (owner: Robotics) — pins are not decided, so this item is only half closed: installed versions are recorded, pins are not.
- [ ] Optional gaps open by decision: `gh` (needed for the PR step in §6), `shellcheck` (needed for §3), `rosbridge_server` (only if Andy's design uses it)

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

Desktop shell decision: **Electron** (no Rust / WebKitGTK installs). `frontend/package.json` and `desktop/package.json` now exist (Electron 44.9.3); the checks below are still **not executed** by REL.

- [ ] `package-lock.json` committed — `frontend/package-lock.json` is tracked since `df9570e`; `desktop/` (and its `package-lock.json`) is **untracked** at 2026-10-28 and has not been committed or reviewed by REL
- [ ] CI runs `npm audit --audit-level=high` (fail on high/critical) — no CI exists; **not executed**. Local equivalent to run before release: `npm audit --audit-level=high`
- [ ] Python dependency audit — `backend/requirements.txt` exists; tool (`pip-audit`) not installed; **not executed**
- [ ] Production frontend build has no source maps — `*.map` is git-ignored; build config must set `sourcemap: false` for production; **not executed** (check `find dist -name '*.map'` is empty)
- [ ] Electron settings (SEC-015): `nodeIntegration: false`, `contextIsolation: true`, `webSecurity: true`, preload via `contextBridge`, CSP limited to `http://localhost:8000` and `ws://localhost:8000` — review when `main.js` exists; **not executed**
- [x] Python lockfiles, hash-pinned (SEC-004-D1): `backend/requirements.lock` (production, 18 packages) and `backend/requirements-dev.lock` (adds pytest etc., 23 packages), built from `backend/.venv` versions with sha256 of the PyPI wheels (linux x86_64, CPython 3.12). Verified in a throwaway venv outside the repo: `pip install --require-hashes --no-deps --no-index --find-links <downloaded wheels> -r requirements-dev.lock` succeeded and `pip check` reported no broken requirements; a deliberately corrupted hash was rejected (exit 1, nothing installed). Nothing was installed system-wide. Regenerate when `requirements*.txt` changes or on another platform. ROS dependencies via `rosdep`: TBD
- [ ] Clean build from a fresh clone: command ____ · result ____
- [ ] `colcon build` of `ros2_ws/` clean — see §4a (nothing executed yet)

## 4a. ROS workspace build and launch verification (for when Andy delivers `ros2_ws/`)

Status 2026-10-28: **none of these steps has been executed.** At 02:50Z `ros2_ws/src` holds Andy's `munder_difflin_bringup`, `munder_difflin_description` and `munder_difflin_gazebo` (untracked, held by god until built and verified); `ros2_ws/` also has `build/ install/ log/ logs/` directories that REL did not create or inspect. The earlier Franka checkouts are gone. Run every step in a clean shell (`env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin bash --noprofile --norc`) so `~/ros2_ws`, `~/colcon_ws` and the other workspaces cannot shadow this one. No `sudo`; a missing system package is reported to the Boss for the human to install. Record the command, exit code and the real output tail for each step; mark anything skipped "not executed".

**Pre-conditions**
- [ ] No third-party source checkouts: the sim uses the apt Panda packages (`moveit_resources_panda_*`), so no `franka_ros2`, `franka_description` or `libfranka` (god, 2026-10-28). Evidence: `find ros2_ws/src -name .git -maxdepth 3` prints nothing; `ls ros2_ws/src` lists only `munder_difflin_*`. **If a source dependency is ever added**, pin it by tag + commit SHA in `ros2_ws/munder_difflin.repos`, fetch with `vcs import`, no submodules; its checkout path goes in `.gitignore`.
- [ ] `rosdep` keys resolve: `source /opt/ros/jazzy/setup.bash && rosdep install --from-paths ros2_ws/src --ignore-src --simulate` lists only already-installed or apt-available packages (`--simulate` prints, does not install). Any "cannot locate rosdep definition" is a blocker for Andy.

**Build**
- [ ] `cd ros2_ws && colcon build --symlink-install --event-handlers console_cohesion+` ends with `Summary: N packages finished`, **0 failed**, exit 0. Evidence: console tail plus `ros2_ws/log/latest_build/` (git-ignored; do not commit).
- [ ] Warnings reviewed: stderr of build packages listed; no new warning category without an owner's note.
- [ ] Build is repeatable from a fresh clone: `git clone` the repo to a scratch directory, repeat the two steps above, same result.
- [ ] `build/`, `install/`, `log/` are untracked afterwards: `git status --short ros2_ws` shows only intended source files.

**Unit tests**
- [ ] `colcon test --event-handlers console_direct+` then `colcon test-result --verbose`: 0 errors, 0 failures, skipped tests listed.

**Overlay**
- [ ] `source ros2_ws/install/setup.bash` in the clean shell; `ros2 pkg list | grep -E 'franka|panda|ur_|<project packages>'` shows the workspace packages; `ros2 pkg prefix <package>` points into `ros2_ws/install` for project-owned packages and into `/opt/ros/jazzy` for apt ones.

**Launch (simulation, Panda primary)**
- [ ] Display available, or headless: a desktop session (`DISPLAY` set) for the Gazebo GUI and rviz2, otherwise run the server only (`gz sim -s -r`, or the launch file's headless argument). State which was used.
- [ ] Launch command (Andy to supply — launch file name TBD): `ros2 launch <package> <launch file>` starts without a traceback; the first 60 s of output contain no `[ERROR]`/`[FATAL]` lines (list any that appear).
- [ ] Nodes up: `ros2 node list` includes `controller_manager`, `robot_state_publisher`, `move_group`, and the Gazebo bridge.
- [ ] Controllers active: `ros2 control list_controllers` shows `joint_state_broadcaster` **active**, the arm `joint_trajectory_controller` **active**, and the gripper controller **active** (if any). Paste the table.
- [ ] State flowing: `ros2 topic echo /joint_states --once` returns a message with the arm's joint names; `ros2 topic hz /joint_states` shows a steady rate (record the number).
- [ ] MoveIt reachable: `ros2 action list` includes the `MoveGroup` action (`/move_action`); `ros2 service call /get_planning_scene ...` or the project's smoke script returns a planning scene.
- [ ] Plan-and-execute smoke: one small joint-space goal plans and executes, final `/joint_states` is within tolerance of the goal. Command, goal and measured error recorded.
- [ ] Safety/validation: an out-of-range or colliding goal is **rejected** and the arm does not move (ties to §5 safety tests).
- [ ] Clean shutdown: Ctrl-C ends all processes; `pgrep -a -f 'gz sim|ruby|move_group|ros2_control_node'` prints nothing afterwards; no zombie Gazebo server holding port/transport.
- [ ] Time budget recorded: seconds from launch to "controllers active", and peak RAM (`free -m`) — the machine has 15 GB and showed ~5.7 GB available under load.

**Fallback arm (UR5e, ADR-006)**
- [ ] `ros2 launch ur_simulation_gz ur_sim_control.launch.py ur_type:=ur5e` (installed launch files, listed 2026-10-28: `ur_sim_control.launch.py`, `ur_sim_moveit.launch.py`) brings up controllers; repeat the "controllers active" and "state flowing" checks. Not executed.
- [ ] Panda reference config launches: `ros2 launch moveit_resources_panda_moveit_config demo.launch.py` (installed; needs a display) — baseline that MoveIt itself works independent of Andy's code. Not executed.

**Backend integration**
- [ ] The FastAPI backend reaches ROS through the interface in `docs/INTERFACE_CONTRACTS.md` (path TBD by Andy/Oscar): one natural-language command from the API to a completed motion in simulation, with request id, log lines and final joint state. Run only after QA signs off the backend suite (§5).
- [ ] Backend and ROS use separate Python environments (ADR-005): `backend/.venv` is not on the ROS `PYTHONPATH` and vice versa. Evidence: `echo $PYTHONPATH` in each shell.

**Sign-off for this block:** Tester GO path ____ · REL commit ____ (nothing is DONE until the Tester has verified it).

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
