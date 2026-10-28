# Backend core verification report (MD-TEST-002)

Verifier: Angela (Tester). Target: Pam's `backend/app` (MD-DEV-001), as it stood on 2026-10-28 around 00:30 IST. The backend changed while I was testing (Pam added `app/security.py`, the 2048-character input cap and log redaction; the tokenizer gained offsets). Everything below was re-run against the code on disk at the end.
Environment: Python 3.12.3, venv outside the repo (pytest 9.1, pydantic 2, httpx, pytest-timeout, tiktoken). No ROS, no network, no real model calls (HTTP is mocked with `httpx.MockTransport`).

## 1. Verdict
**Update 2026-10-28 (MD-TEST-003): BE-1 to BE-5 are all fixed and independently re-verified, see section 6.** The text below is the original verdict.

Core is sound for the happy path and for rejection of unknown/ambiguous input. **Not ready to be trusted as the safety layer yet**: five confirmed defects, two of them (BE-1 negation, BE-2 silent multi-step truncation) turn a command the user did not give into an executable plan. All are pinned as strict `xfail` tests, so they flip to failures when fixed.

## 2. Claims checked

| # | Claim | Result | Evidence |
|---|---|---|---|
| C1 | Pam's suite: 64 pass, 1 skip | **Reproduced** (64 passed, 1 skipped: tiktoken missing). Suite has since grown: now **104 passed** with tiktoken installed | `pytest -c backend/pytest.ini backend` |
| C2 | Angela's L0 suite: 71 pass, 10 skip, 2 xfail | **Reproduced** exactly. With this report's tests added: **104 passed, 10 skipped, 13 xfailed** (the 13 xfails = 2 known-gap markers + 11 parametrised cases pinning BE-1 to BE-5) | `pytest -c tests/pytest.ini tests` |
| C3 | Spec s5: every stage emits observable events with the 7 UI states | **Partial**. Events and states are correct for the 4 stages that exist (tokenization, ambiguity_check, parsing, validation); 10 of the 14 spec stages are absent. Events are ordered, share one run id, timestamps never go backwards, skipped stages are marked cancelled | `test_acceptance_i_*` |
| C4 | Spec s6: strict schema, ambiguity asks for clarification, nothing invented | **Pass** for the schema (extra/missing/typed-wrong fields, injection-shaped ids, same object/destination, duplicate avoid all rejected). "Move the box to the left" -> clarification. Pronoun-only, empty and meaningless input -> no plan | `test_task_schema`, `test_acceptance_d_*` |
| C5 | Spec s7: tokenizer panel data is honest | **Pass**. Offsets reslice the original text exactly; approximate tokens carry no IDs; a real tokenizer (tiktoken cl100k_base) gives IDs; the note states tokenization does not decide physical action. I ran the exact-tokenizer path (it was not run in the earlier report) | `test_acceptance_i_*` |
| C6 | Spec s14: raw model output never drives the robot; deterministic validation | **Partly**. Unknown object/destination/avoid object, non-graspable object, schema violations from a model are all rejected. But a model plan that is valid yet different from what the user asked is accepted (BE-3) | defects below |
| C7 | Spec s15: provider errors, malformed JSON, bounded retries, fallback | **Partly**. Malformed JSON (10 shapes incl. arrays, extra keys, wrong action, unterminated nesting) is retried at most 3 times then handed to the fallback; fallback use is labelled `warning`. A provider raising anything other than `ProviderError` crashes the pipeline (BE-4) | `test_backend_adversarial` |
| C8 | API keys never appear in status/repr/errors | **Pass** in 5 hostile server behaviours (key echoed in 200 body, 401 body, 500 body, HTML body, key inside returned JSON) across result, events, `repr(provider)`, status JSON, `health_check()`, `chain.statuses()`, raised exceptions and captured log records. Note: `ProviderUnavailable` keeps the original exception as `__cause__`; if an HTTP library ever put header values in its message, a traceback printer would show them. Realistic httpx messages do not | `test_backend_adversarial` |
| C9 | Huge input handled | **Pass** for user input: capped at 2048 characters (after whitespace normalisation) and 64 characters per word, rejected with a clear reason in under 50 ms. **Fail** for model output (BE-5) | |
| C10 | Prompt injection in the instruction | **Pass**. "Ignore previous instructions / admin mode / disable the safety validator / SYSTEM: ... / rm -rf" never produced an unvalidated plan or a new object; the only plan targets are scene ids and the validator rejected invented ones (e.g. destination `admin_mode`). Extra instructions in the text are ignored, not obeyed | |
| C11 | Cancellation | **Pass** at all four stage boundaries: state `cancelled`, no plan | |

## 3. Defects (repro commands run from `munder_difflin/`, venv with backend requirements)

All repros use the default world: `v = SafetyValidator(default_world())`, `run_pipeline(cmd, ProviderChain([]), v)`.

| ID | Severity | Defect | Repro and observed result | Expected |
|---|---|---|---|---|
| BE-1 | **High** | Negated commands are executed as the positive command | `"Do not move the red box to the bin"`, `"Never pick the red box and put it on shelf a"`, `"Don't put the red box on shelf a"` -> state `warning`, plan `red_box -> bin / shelf_a`, `report.ok = True` | needs_clarification or failed; never an executable plan. (`_AVOID_RE` handles only "don't touch/hit/bump".) |
| BE-2 | **High** | Multi-step commands silently keep only step 1 | `"Move the red box to the bin and then move the blue box to shelf a"` and `"Move the red box to the bin, then to shelf a"` -> plan `red_box -> bin`, ok. Only the "pick ..., then pick ..." wording sets `multi_step` | the "one task at a time" clarification |
| BE-3 | **Medium** | A model plan is never compared with the user's words | Provider returns `blue_box -> bin` for `"Move the red box to shelf a"` -> ok=True, executable. Provider drops the avoid constraint for `"... without touching the blue box"` -> ok=True. The deterministic analysis of the user's text exists (`analyze_command`) but is not used to cross-check the model | reject or downgrade to clarification when plan object/destination/avoid disagree with the unambiguous mentions in the command |
| BE-4 | **Medium** | Non-`ProviderError` exceptions escape the pipeline | A provider whose `parse` raises `RuntimeError`/`TimeoutError`/`ValueError` -> `run_pipeline` raises; no `failed` event, no fallback, UI would see an unhandled error. `ProviderChain.parse` catches only `ProviderError` | catch `Exception` per provider, record `failed`, continue to fallback; pipeline always ends with a terminal event |
| BE-5 | **Low-Medium** | `extract_json_object` is O(n^2) on untrusted model output | `extract_json_object("{" * 20000)` takes ~12 s (5000: 0.8 s; 10000: 3 s). Cloud output is bounded by `max_tokens`, but local (Ollama) and NVIDIA output are not capped | cap model output length before parsing and/or make the scan linear |

Also observed, not filed as defects (judgement calls for Jim/Pam):
- `"Move the red box to the left side of shelf a"` -> plan to `shelf_a`; the spatial qualifier is dropped. `"... without touching the red box"` / `"... avoiding shelf a"` drop nonsense avoid targets silently.
- A model plan with confidence 0.0 validates `ok=True` with only a `LOW_CONFIDENCE` warning (state `warning`). Whether a low-confidence plan may execute without confirmation is a policy decision.
- Any approximate tokenizer makes every run end `warning`, even a fully valid plan; a UI that treats `warning` as "needs attention" will always show it when tiktoken is absent.
- `LocalInferenceProvider.status()` does a blocking HTTP call each time the chain runs (up to the 30 s client timeout when Ollama is down).

## 4. Gaps (carried from TEST_PLAN s8, still open)
1. `default_world()` is red_box/blue_box + shelves/bin/tray; spec commands with "red cube" and "storage box" cannot produce a plan.
2. Pipeline implements 4 of 14 spec stages; stage names differ from `INTERFACE_CONTRACTS.md` s3.1 (settled by Jim in MD-ARCH-002).
3. No reachability or workspace check; no object poses.
4. No FastAPI app (`app.main`), so REST/WebSocket contracts (s7 of the contracts) are untested.
5. Not executed: anything involving ROS 2, Gazebo, MoveIt, a real model API, or the desktop wrapper.
6. `security.py` (SEC-001/SEC-010) was reviewed only through its observable effects (length cap, control/zero-width stripping, log redaction). Dwight owns its security review.

## 5. Tests added (tests/ only)
`tests/unit/test_backend_adversarial.py` (parametrised; see `-rA`): BE-1 to BE-5 as strict xfail, plus passing tests for injection, odd Unicode, length cap and boundaries, long word, control characters, huge-input speed, cancellation at each stage, key leakage matrix, log leakage, 9 malformed-JSON shapes, prose-wrapped valid JSON.
Run: `python -m pytest -c tests/pytest.ini tests -m unit` (the BE-5 test takes ~12 s; it is marked `slow`).

## 6. Re-verification after fixes (MD-TEST-003, 2026-10-28)
Scene is now `config/scene.json` (red_cube, blue_cube, green_cylinder, storage_box, platform, table). Stage names follow ADR-009. I re-probed each defect with fresh inputs (a script outside the repo), not only with the old repros, then converted the strict xfails into regression tests.

| ID | Result | Evidence (new scene) |
|---|---|---|
| BE-1 negation | **Fixed** | 6 wordings ("Do not move...", "Never pick...and put...", "Don't put...", "Please don't move...", "Stop, do not pick up...") -> `needs_clarification`, no plan |
| BE-2 multi-step | **Fixed** | 6 wordings ("and then move", ", then to", ", after that", "X to A and Y to B", "First...next...", "the red cube and the blue cube...them") -> `needs_clarification`, no plan |
| BE-3 plan vs words | **Fixed** | wrong object -> `PLAN_MISMATCH`; wrong destination -> `PLAN_MISMATCH`; dropped "without touching" or "keep it upright" -> `CONSTRAINT_DROPPED`. Controls: a matching plan, and a plan that adds an extra avoid, still validate |
| BE-4 provider exception | **Fixed** | RuntimeError, TimeoutError, ValueError, KeyError, RecursionError, MemoryError from `parse` -> attempt recorded `failed: unexpected <Type>`, fallback used, run ends `warning` with a plan |
| BE-5 quadratic JSON | **Fixed** | `{` x 20k: 1 ms (was ~12 s); `{` x 2M, `"` x 50k, `{"a":` x 50k, `[` x 100k, 3 MB junk, 3 MB string: all under 6 ms, all `ValueError`. A valid nested object with a `}` inside a string still parses |

Other re-checks: reachability callback (`UNREACHABLE` stops the run, later stages cancelled; `None` -> `REACHABILITY_UNCONFIRMED` warning; scene `reachable: false` honoured); all 14 stages announced in canonical order; after a failure every later stage is `cancelled`; headless success closes grounding..verification as `cancelled` (`headless_run_complete`).

New observations (not defects, for Pam/Jim):
- With no model provider every run uses the deterministic fallback, so a fully valid headless run ends `warning`, never `success`.
- Scene poses and `reachable` are all `null`, so reachability is never actually decided until Gazebo supplies data.
- While I was testing, `pipeline.py` briefly raised `TypeError: event() got multiple values for argument 'message'` for 49 of my tests and 3 of Pam's (mid-edit; fixed within minutes). Not filed.

Counts at the end: my suite **146 passed, 10 skipped, 0 xfailed**; backend suite **148 passed**.
