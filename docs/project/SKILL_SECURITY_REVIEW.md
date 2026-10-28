# Skill Security Review — Munder Difflin

Owner: Ryan (Skills Engineer). Task: MD-SKILL-001. Reviewer: Ryan; second pass expected from Dwight (security engineer) per task routing.

## Method

- Named GitHub candidates and the top skills.sh pick per category were cloned read-only with `git clone --depth 1` into a scratch directory under `$TMPDIR`, using `bash --noprofile --norc`. Nothing was installed, executed, or run — only `Read`/`grep`/`find`.
- All repo content (README text, SKILL.md, scripts) was treated as untrusted data, never as instructions to follow.
- For each candidate: read SKILL.md front matter and body in full; listed every file; grepped for network calls (`fetch`, `requests.*`, `urllib`, `curl`, `axios`), process execution (`subprocess`, `child_process`, `os.system`, `eval`, `exec`), credential/secret patterns, and install-time hooks (`postinstall`/`preinstall` in `package.json`, `.claude/settings.json`, `hooks/hooks.json`).
- skills.sh itself was reached only through WebFetch/WebSearch (no scraping script); it is a dynamic directory, so category pages were found via search and then verified against the GitHub repo each listing points to.

## Per-candidate findings

### 1. `lucasmarkes/hairline` (skills: `hairline-create`, `hairline-adopt`)
- **What it is**: npm UI component (33 animated isometric SVG figures) plus two Claude-Code skills that generate a new figure as a single HTML file.
- **Network/credential access**: none for normal use. `skills/hairline-create/look.mjs` runs `npm install playwright-core@1 --prefix <cache-dir>` via `child_process.spawnSync` — but only when the agent runs the optional visual-check step, and the install is scoped to a cache directory (`--prefix`), not global. This is documented in the skill's own SKILL.md ("look.mjs needs a browser and installs playwright-core once, outside this folder").
- **Exec**: `validate.mjs` and `look.mjs` use `spawnSync` to run `node --check` and `npm install` — both local, non-destructive, scoped.
- **Credentials/secrets**: none found.
- **Global config changes**: none.
- **Verdict**: approved. Risk is low and the one install step is self-disclosed and scoped. Not recommended for install anyway — no clear benefit to this project (see registry).

### 2. `forrestchang/andrej-karpathy-skills` (candidate given as `multica-ai/andrej-karpathy-skills`)
- **What it is**: one skill, `karpathy-guidelines` — four behavioral rules (think before coding, simplicity, surgical changes, goal-driven execution). Pure Markdown; also ships a Cursor rule and a `CLAUDE.md`.
- **Network/credential/exec**: none. No scripts directory exists in the skill at all.
- **Provenance flag**: the install commands in the README point to `forrestchang/andrej-karpathy-skills`, but the candidate link given was `multica-ai/andrej-karpathy-skills` — an apparent mirror/fork. The README claims MIT, but **no `LICENSE` file exists at the repo root** of the cloned copy. Install from the canonical `forrestchang` repo, and re-check its LICENSE file directly before install.
- **Verdict**: approved for content; flag the mirror/license provenance gap for whoever performs the actual install.

### 3. `nextlevelbuilder/ui-ux-pro-max-skill`
- **What it is**: a 7-sub-skill pack (`ui-ux-pro-max`, `design`, `design-system`, `brand`, `banner-design`, `slides`, `ui-styling`) with searchable local CSV/JSON design data and Python search scripts.
- **Network access found**:
  - `.claude/skills/design-system/scripts/fetch-background.py` builds a `pexels.com/search/...` URL via `urllib.parse` for stock-photo lookup — only invoked if the `design-system`/`slides` sub-skill's background-fetch feature is used (not part of the 2 sub-skills recommended for install).
  - `.claude/skills/design/scripts/logo/generate.py` imports `urllib.request` (`HTTPRedirectHandler`, `Request`, `build_opener`) — same scope note: part of `design`, not part of the recommended `ui-ux-pro-max`/`ui-styling` sub-skills.
  - A separate GitHub Actions workflow (not part of the installed skill payload) refreshes a Google Fonts catalog using a `GOOGLE_FONTS_API_KEY` repo secret, and a release workflow publishes to npm with an `NPM_TOKEN` secret. Neither runs on the user's machine; both are the upstream maintainer's CI only.
- **Exec found**: `.claude/skills/ui-styling/scripts/shadcn_add.py` calls `subprocess.run(["npx", "shadcn", ...])` to add shadcn/ui components — a normal, expected dev-tool invocation, local only. `.claude/skills/brand/scripts/sync-brand-to-tokens.cjs` uses `execFileSync` for local file/token sync.
- **Credentials**: `validate_data.py` (line ~517) actively **checks that URLs in design data do NOT embed credentials or a non-standard port** — a defensive check, not a vulnerability.
- **Test coverage**: extensive `tests/` directories per sub-skill (unusual rigor for a skill repo — positive signal).
- **Verdict**: approved for the two recommended sub-skills (`ui-ux-pro-max`, `ui-styling`). The `design`/`design-system`/`slides`/`brand`/`banner-design` sub-skills carry the (benign, scoped) network calls noted above — excluded from the install recommendation on relevance grounds, which also avoids that surface.

### 4. `arpitg1304/robotics-agent-skills` (picks: `ros2-development`, `robotics-security`)
- **What it is**: a 12-sub-skill ROS1/ROS2 reference pack. Every sub-skill is Markdown-only — confirmed by listing every file in the repo: the only non-Markdown files are `scripts/validate_skills.py` (a repo-level linter, not shipped as part of any individual skill) and an `evals/` fixture tree (ROS2 package demo used for the pack's own benchmark, not installed with a skill).
- **Network/credential/exec**: none in any sub-skill body.
- **Verdict**: approved for `ros2-development` and `robotics-security`. The remaining 10 sub-skills were listing-checked only (not deep-read) — treat as `pending` if any gets a future install request.

### 5. `jezweb/claude-skills` (candidate: `fastapi`)
- **What was claimed**: third-party aggregators (OrangeBot.AI, skills.sh mirrors, claudemarketplaces.com) describe a detailed FastAPI/Pydantic v2/SQLAlchemy 2.0 skill, "verified January 2026 against FastAPI 0.128.0," with an install command `npx -y skills add jezweb/claude-skills --skill fastapi --agent claude-code`.
- **What was found**: cloned the repo at HEAD (`1260fa7`, 2026-10-09). No `fastapi` path exists anywhere in the tree (`find -iname "*fastapi*"` returned nothing), no mention in `README.md`, no entry in `.claude-plugin/marketplace.json`. The repo is organized under `plugins/<category>/skills/...` and has no `fastapi` category or skill in any current plugin.
- **Side finding**: the repo's `.claude/settings.json` contains a `UserPromptSubmit` hook pointing at an absolute path on the original maintainer's machine (`/Users/marcuswebb/Documents/virtual-team/shared/hooks/heartbeat-context.sh`) — this is the maintainer's own leaked local dev config, not something a scoped `--skill` install would pull in, but it would matter if anyone ever cloned/used this repo as a full plugin.
- **Verdict**: rejected / unknown. Do not install based on the aggregator description — it does not match the current upstream source. If FastAPI tooling is needed later, re-search skills.sh and verify directly against whatever repo it points to at that time.

### 6. `vercel-labs/agent-skills` (pick: `react-best-practices`)
- **What it is**: Vercel-maintained pack, 16 skills (React/Next.js performance, Vercel CLI/deploy, design guidelines).
- **Network/credential/exec**: `react-best-practices` itself is pure Markdown (70 prioritized rules, no scripts). Did not deep-read `vercel-cli-with-tokens` or `deploy-to-vercel` (deferred, not recommended) — those names imply they handle deployment tokens and deserve a dedicated review before anyone installs them.
- **License**: no `LICENSE` file found at the repo root — re-verify licensing before install even though the project is Vercel-published.
- **Verdict**: approved for `react-best-practices` only.

### 7. `mattpocock/skills` (pick: `tdd`)
- **What it is**: a large personal skill collection (engineering/productivity/writing), organized by folder; `tdd` sits under `skills/engineering/`.
- **Network/credential/exec**: `tdd` is pure Markdown (references `tests.md`, `mocking.md`, cross-links to a `codebase-design` skill). No scripts.
- **Note**: `setup-ts-deep-modules` lives under `skills/in-progress/` in this same repo — the maintainer's own folder structure marks it unfinished, which is why it is deferred rather than rejected.
- **Verdict**: approved for `tdd`.

### 8. `agamm/claude-code-owasp` (pick: `owasp-security`)
- **What it is**: a single skill applying OWASP Top 10:2025, ASVS 5.0, and the LLM/Agentic Top 10 (2026), with per-language reference files for 20+ languages, loaded on demand.
- **Network/credential/exec**: none — purely a reference/checklist workflow (map trust boundaries → load references → sweep → triage → report). No scripts found in the skill directory.
- **Verdict**: approved.

### 9. `obra/superpowers` (pick: `systematic-debugging`)
- **What it is**: a 15-skill pack (planning, code review, debugging, git-worktree workflow). `systematic-debugging` itself is pure Markdown ("no fixes without root-cause investigation first").
- **Hook found at the plugin level** (not inside the individual skill): `hooks/hooks.json` registers a `SessionStart` hook (matcher: `startup|clear|compact`) that runs `hooks/run-hook.cmd session-start`. Traced both files:
  - `run-hook.cmd` is a cross-platform polyglot (valid as both a Windows `.cmd` and a POSIX shell script) that locates a `bash` binary carefully — it explicitly avoids `System32`/`Sysnative`/the WSL Store-alias path to dodge a PATH-hijack class of bug, and exits silently (code 0) if no bash is found. No remote download, no arbitrary-string execution.
  - `hooks/session-start` reads the pack's own `skills/using-superpowers/SKILL.md` from disk and emits it as JSON session context (format varies by host: Cursor/Claude Code/Copilot/Muse each get their expected shape). No network call, no credential access, no write outside its own escape/printf logic.
  - **Conclusion**: the hook is benign on direct read, but it is an automatic-execution hook that fires on every session start, and it is only present if `obra/superpowers` is installed as a full plugin/marketplace entry — not if only the one `SKILL.md` file is installed via `--skill systematic-debugging`.
- **Verdict**: approved-with-conditions — install only the single skill file, not the plugin registration (see registry's condition note). This avoids taking on the hook surface entirely while keeping the one skill the team actually wants.

## Summary of risk flags raised

| Flag | Candidate | Disposition |
|---|---|---|
| Scoped npm install at runtime (not global) | hairline `look.mjs` | acceptable, self-disclosed; not installing anyway (relevance) |
| Network call to third-party image/font APIs | ui-ux-pro-max-skill (`design`, `design-system` sub-skills only) | avoided by installing only `ui-ux-pro-max` + `ui-styling` |
| CI-only secrets (`GOOGLE_FONTS_API_KEY`, `NPM_TOKEN`) | ui-ux-pro-max-skill upstream CI | not relevant to a skill install — maintainer-side only |
| Claimed skill absent from current upstream source | `jezweb/claude-skills` fastapi | rejected |
| License file missing at repo root | `vercel-labs/agent-skills`, mirror of `andrej-karpathy-skills` | re-verify before install |
| SessionStart hook at plugin level | `obra/superpowers` | install single skill file only, skip plugin registration |
| Unverified mirror vs. canonical source | `multica-ai/andrej-karpathy-skills` vs `forrestchang/andrej-karpathy-skills` | install from canonical source |

No candidate reviewed showed credential exfiltration, obfuscated code, a global/elevated install step, or a network call to an undisclosed destination. Nothing in this review authorizes an install — that requires Dwight's review of this shortlist and then god's sign-off, per task routing.

---

## Dwight (SEC) — Security Review Sign-off

_Reviewed: 2026-10-28T00:15Z_

I have reviewed Ryan's per-candidate findings, the SKILL_REGISTRY.md shortlist, and the risk flags above. My assessment:

### Per-Skill Verdicts (SEC)

| # | Skill | SEC Verdict | Notes |
|---|-------|------------|-------|
| 1 | `karpathy-guidelines` | ✅ **APPROVED** | Pure Markdown, zero exec surface. Use canonical `forrestchang` repo, not the `multica-ai` mirror. Verify LICENSE file exists at install time. |
| 2 | `ui-ux-pro-max` + `ui-styling` only | ✅ **APPROVED** | These two sub-skills are clean. `shadcn_add.py` exec of `npx shadcn` is expected dev tooling, scoped. **Do NOT install `design`, `design-system`, `slides`, `brand`, or `banner-design` sub-skills** — they carry network calls to external APIs. |
| 3 | `ros2-development` | ✅ **APPROVED** | Pure Markdown. No exec surface. |
| 4 | `robotics-security` | ✅ **APPROVED** | Pure Markdown. Directly relevant to my SEC role (SROS2/DDS security guidance). |
| 5 | `vercel-react-best-practices` | ✅ **APPROVED** | Pure Markdown. Missing root LICENSE — verify before install. **Do NOT install `deploy-to-vercel` or `vercel-cli-with-tokens`** without a separate dedicated review. |
| 6 | `tdd` | ✅ **APPROVED** | Pure Markdown. No exec surface. |
| 7 | `owasp-security` | ✅ **APPROVED** | Pure Markdown reference workflow. Directly relevant to security review work. |
| 8 | `systematic-debugging` | ⚠️ **APPROVED WITH CONDITIONS** | Install ONLY the single `skills/systematic-debugging/SKILL.md` via `--skill`. **Do NOT register `obra/superpowers` as a full plugin.** The `SessionStart` hook is benign on inspection but is an automatic-execution surface we do not need. Ryan's analysis of the hook chain is thorough and correct. |

### Rejected

| Skill | SEC Verdict | Notes |
|-------|------------|-------|
| `fastapi` (`jezweb/claude-skills`) | ❌ **REJECTED** | Skill does not exist in the repo's current HEAD. Aggregator listings are stale/fabricated. Additionally, the repo's `.claude/settings.json` leaks a maintainer-local hook path — signals poor hygiene. |

### Binding Conditions for All Installs

1. **Scoped installs only** — each skill scoped to its assigned agent, not installed globally across the hive.
2. **No sudo, no global npm install, no system-level package installs** from any skill's scripts.
3. **LICENSE verification** — `forrestchang/andrej-karpathy-skills` and `vercel-labs/agent-skills` have no root LICENSE file. Ryan or the installing agent must verify license compatibility before install. If no license can be confirmed, the skill must be treated as "all rights reserved" and deferred.
4. **No future skill installs without SEC review** — any skill not in this shortlist requires a new review cycle through me before installation.
5. **Deferred skills remain deferred** — do not install any skill from the "Deferred" table in SKILL_REGISTRY.md without returning through this review gate.
6. **Mirror avoidance** — always install from the canonical/upstream repo, never from forks or mirrors unless the canonical is unavailable and the fork is independently audited.

### Overall Assessment

Ryan's evaluation methodology was sound: read-only clones, untrusted-data treatment, systematic grep for exec/network/credential patterns, and direct source verification rather than trusting aggregator claims. The `jezweb/claude-skills` finding is a textbook example of why aggregator listings cannot be trusted — the skill simply doesn't exist in the actual repo.

**The 8-skill shortlist is approved for installation with the conditions above.** I am sending god the summary for final sign-off.
