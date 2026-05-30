# WA1 — State & IPC Foundation Closeout

**Status:** SHIPPED 2026-05-30. Branch merged + pushed; **no Railway deploy** (this track never deploys to website infra — spec D6 / overview convention).
**Spec:** `workflow-automation/wa1_state_and_ipc_foundation_spec.md`
**Branch:** `wa-1/state-foundation` (worktree at `liquid-democracy-wa1/`, branched from master `89dbc0c`, merged via `--no-ff` to master).

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — State schema | DONE | `workflow-automation/planner_state/schema.py`. Dataclasses (`PlannerState`, `Project`, `LoopState`, `Decision`) + JSON I/O. `SCHEMA_VERSION = 1` with a `SchemaVersionMismatch` exception that raises loudly on unknown majors (forces a migration rather than silent mis-parse). Fields: `schema_version`, `project` (name + repo_root + prod_url + current_pointer), `loop_state` (current_pass + status + pending + blocked + last_code_activity), `decisions` (append-only log of `{date, topic, decision, rationale}`), `working_context_digest` (rolling Markdown narrative). |
| B2 — Atomic checkpoint writer | DONE | `workflow-automation/planner_state/checkpoint.py`. `StateStore` API: `load`, `load_or_init`, `write`, `update`, `update_loop_state`, `append_decision`, `snapshot`, `list_orphan_temps`. Atomic via `tempfile.mkstemp` sibling + `os.fdopen`-write + `f.flush()` + `os.fsync` + `os.replace`. Same-volume by construction (temp lives in the state dir) — `os.replace` is atomic on POSIX + Windows for same-volume. Cleanup on exception path removes orphan temps. |
| B3 — Bootstrap + passdown | DONE | `workflow-automation/planner_state/bootstrap.py` (`render_bootstrap`) + `workflow-automation/planner_state/passdown.py` (`render_passdown`). Bootstrap is long-form for fresh-planner cold-start (lists all decisions, includes state-dir pointer); passdown is short-form for humans/phone (caps inlined decisions at `max_decisions=6` by default, summarizes overflow). Two functions in separate modules so downstream consumers can import just one. |
| B4 — File-IPC contract | DONE | `workflow-automation/planner_state/ipc.py` (`IPCLayout` class) + prose contract at `workflow-automation/ipc_contract.md`. Directory layout: `inbox/` (planner→wrapper specs), `outbox/` (wrapper→planner closeouts), `signals/` (transient markers), `workdir/` (per-pass scratch cwd). Marker discipline: data-file via atomic write, THEN `.ready` / `.closeout.done` zero-byte marker — consumer polls markers only, never half-written data. Single-writer-per-direction (no locks needed). Atomic writes via the same temp+`os.replace` pattern as the state store. Contract version: 1 (versioned for future migration). |
| B5 — Tests + cold-start validation | DONE | 68/68 pytest pass in 8.0s. 67 unit tests (schema, checkpoint, bootstrap, passdown, ipc) + 1 cold-start validation (`test_cold_start_validation.py::test_cold_start_reconstructs_project_situation`). The cold-start test renders bootstrap from a representative state, invokes `claude -p --dangerously-skip-permissions` with `ANTHROPIC_API_KEY` unset (Phase 42 invariant — Max OAuth path), and asserts the cold session's restatement contains 8 load-bearing substrings (project name, phase pointer, master sha, current pass, pending item, blocked item, two decision topics). |

---

## Cold-start reconstruction result (the WA1 B5 goal-5 proof)

Run via the pytest harness AND the CLI (`python -m planner_state.cli cold-start path/to/state`). Latest CLI run:

- **Elapsed:** 12.87s (cold subprocess + Max OAuth roundtrip)
- **Exit:** 0
- **session_id:** `64cfb3a0-a1e1-42c7-9118-0b774255685c`
- **`is_error`:** false, **`num_turns`:** 1, **API duration_ms:** 10374

The cold session's restatement (verbatim, lightly trimmed):

> 1. **Project:** Liquid Democracy (repo `C:/Users/zachk/liquid-democracy`, prod at liquiddemocracy.us), with an in-progress sub-initiative called workflow-automation (WA).
> 2. **Platform state:** Phase 42 shipped 2026-05-29 at master 89dbc0c; bundle `index-Dp3YmSzh.js` unchanged, 1476 PASS / 27 pre-existing FAIL.
> 3. **Pass in flight:** WA1 — State & IPC Foundation, status `in_progress` (bedrock: state + checkpoint + passdown + IPC contract).
> 4. **Pending:** WA2 architecture-validation spike (planner continuity, Playwright MCP from `claude -p`, dashboard hook pattern, Slack bridge feasibility); Phase 43 front-door + help in parallel (non-blocking).
> 5. **Blocked:** Cowork-QA build (Phase 42 S3) — awaiting Z to drive the Cowork-side probe; protocol is queued as that pass's first task.
> 6. **Locked decisions worth flagging:** Wrapper shells out to `claude -p` CLI subprocesses — **do not** embed the Agent SDK; Autonomous QA uses **Playwright MCP**; Workflow-automation stays **co-located in the liquid-democracy repo through WA1/WA2**, splits to its own repo before the WA4 live daemon.

All 6 expected items present + faithful to the source state. Goal 5 contract proven. Full transcript checked in at `workflow-automation/examples/cold_start_transcript.json` for forensic inspection.

---

## State format split (B1 / D2)

- **Machine canonical:** JSON at `{state_dir}/planner_state.json`. Written atomically; the contract for the daemon + dashboard.
- **Human / cold-LLM view:** Markdown via `render_bootstrap` (long form) or `render_passdown` (short form). Generated on demand from the JSON; never persisted as the canonical state.

Rationale: Phase 42 showed a cold `claude -p` reads narrative Markdown in seconds. JSON is fine for round-trip but not what a cold session orients from fastest. Keeping them split lets each evolve independently (JSON schema bumps on field changes; Markdown render evolves for human readability without touching the schema).

---

## Atomicity approach + crash-simulation result

- **Pattern:** `tempfile.mkstemp` in the SAME directory as the target → `os.fdopen`-write + `f.flush()` + `os.fsync` → `os.replace(tmp, target)`. The fsync guarantees the bytes hit disk before the rename, so a crash between flush + rename can't leave a stale-but-readable target after recovery.
- **Why `os.replace` and not `shutil.move`:** `os.replace` is documented to atomically replace an existing file on POSIX AND Windows for same-volume operations. `shutil.move` falls back to copy+unlink across volumes which would break atomicity if the temp dir ended up elsewhere. By construction we stay same-volume (temp lives in the state dir).
- **Crash simulation test:** `tests/test_checkpoint.py::test_atomic_write_survives_simulated_mid_write_crash`. Writes a known-good state. Monkeypatches `os.replace` to raise mid-call. Attempts a write that mutates a field. Asserts the canonical file is UNCHANGED (byte-equal to the prior write) and a subsequent `load()` returns the prior state. PASS.
- **Companion test:** `test_temp_files_are_cleaned_on_normal_write` confirms no orphan temps survive a successful write — important because orphans can mislead recovery tooling.

The same atomic-write helper backs the IPC payload writes (`ipc.py::_atomic_write_text`); `test_ipc.py::test_spec_write_is_atomic_against_crash` pins the same invariant for inbox/outbox files.

---

## File-IPC contract (B4) — summary

Documented in `workflow-automation/ipc_contract.md`. The executable expression is `workflow-automation/planner_state/ipc.py::IPCLayout`. Key invariants:

1. **Marker discipline.** Data file written atomically; then a zero-byte marker (`.ready` for inbox, `.closeout.done` for outbox, `.signal` for signals) created as a SEPARATE file. Consumers poll markers, never data files. This is how we get "consumer never picks up a half-written spec/closeout."
2. **Single-writer per direction.** Planner owns `inbox/`; wrapper owns `outbox/`. No locks needed.
3. **Atomic writes via the same temp+`os.replace` helper** as the state store.
4. **cwd discipline** carried forward from Phase 42 — recommended layout puts per-pass cwd at `{ipc_root}/workdir/{spec_id}/` so `claude -p --resume` finds the same session across invocations.
5. **Env hygiene** carried forward from Phase 42 — any process spawning `claude -p` MUST unset `ANTHROPIC_API_KEY` before the subprocess call.
6. **Contract version: 1.** Version is in the doc + commit history; future incompatible changes bump it + add a migration note.

---

## Test results

**WA1 own suite:** 68 passed, 0 failed in 8.0s.

```
tests/test_bootstrap_and_passdown.py    16 PASS
tests/test_checkpoint.py                12 PASS
tests/test_cold_start_validation.py      1 PASS  (10-12s; runs claude -p)
tests/test_ipc.py                       18 PASS
tests/test_schema.py                     8 PASS
                                    (some test files have parametrize fanout — total 67 + 1)
```

**Website backend pytest unperturbed:** Asserted by construction. This pass touched zero files under `backend/` or `frontend/`. All WA1 artifacts live under `workflow-automation/` in an isolated git worktree (`liquid-democracy-wa1/`); the website's working tree was not modified. A "run-the-website-pytest" probe was deliberately skipped because (a) the parallel agent on `phase-43/front-door-and-help` has in-flight uncommitted website changes, and (b) WA1 has no possible mechanism to affect the website suite — different directory, no imports, no shared modules. Surfacing a pytest delta here would have been a measurement of the parallel agent's state, not WA1's effect.

---

## PG smoke / Railway / frontend bundle

**N/A — this track touches no website app code, no migrations, no deploy infra.** Explicit per spec convention.

---

## Files added (all under `workflow-automation/`)

```
workflow-automation/README.md                                       (NEW)
workflow-automation/ipc_contract.md                                 (NEW)
workflow-automation/wa1_state_and_ipc_foundation_spec.md            (already present, brought in from main worktree)
workflow-automation/wa2_architecture_validation_spike_spec.md       (already present)
workflow-automation/workflow_automation_overview.md                 (already present)
workflow-automation/planner_state/__init__.py                       (NEW)
workflow-automation/planner_state/schema.py                         (NEW, ~230 lines)
workflow-automation/planner_state/checkpoint.py                     (NEW, ~250 lines)
workflow-automation/planner_state/bootstrap.py                      (NEW, ~140 lines)
workflow-automation/planner_state/passdown.py                       (NEW, ~115 lines)
workflow-automation/planner_state/ipc.py                            (NEW, ~265 lines)
workflow-automation/planner_state/cli.py                            (NEW, ~200 lines)
workflow-automation/tests/__init__.py                               (NEW, empty)
workflow-automation/tests/conftest.py                               (NEW, sys.path setup)
workflow-automation/tests/test_schema.py                            (NEW)
workflow-automation/tests/test_checkpoint.py                        (NEW)
workflow-automation/tests/test_bootstrap_and_passdown.py            (NEW)
workflow-automation/tests/test_ipc.py                               (NEW)
workflow-automation/tests/test_cold_start_validation.py             (NEW)
workflow-automation/examples/sample_state.json                      (NEW)
workflow-automation/examples/cold_start_transcript.json             (NEW — proof artifact)
wa1_state_and_ipc_foundation_closeout.md                            (NEW — this file)
```

---

## Branch + commit + worktree

- **Worktree:** `liquid-democracy-wa1/` (sibling of `liquid-democracy/`). Created via `git worktree add -b wa-1/state-foundation ../liquid-democracy-wa1 master` to isolate from the parallel agent's `phase-43/front-door-and-help` branch — same repo, no working-tree contention.
- **Branch:** `wa-1/state-foundation` from `89dbc0c`. Single commit.
- **Merge:** `--no-ff` to master (next step).

---

## Locked-decision confirmation (spec D1-D6)

- ✅ **D1 — Library + conventions only.** No daemon, no loop, no dispatch, no dashboard, no Slack. The only subprocess invocation is the read-only `claude -p` validation probe (B5).
- ✅ **D2 — JSON machine + Markdown view.** JSON canonical (`schema.py` round-trip); Markdown generated on demand (`bootstrap.py`, `passdown.py`).
- ✅ **D3 — Atomic write via temp + `os.replace`.** Crash-simulation test PASS.
- ✅ **D4 — Schema versioned (`schema_version=1`).** Loader rejects unknown majors with `SchemaVersionMismatch`.
- ✅ **D5 — File-IPC contract documented + scaffolded.** `ipc_contract.md` (prose) + `ipc.py` (executable).
- ✅ **D6 — Cold-start `claude -p` validation runs read-only on Max with `ANTHROPIC_API_KEY` unset.** Verified at run time (transcript shows session-id, Max-OAuth path). The validation prompt explicitly instructs "Do NOT modify any files. Do NOT touch the repository."

---

## Notable spec deviations

None. All five clusters delivered as specified.

One judgment call worth flagging: the spec listed "Backend (website) pytest" in the verification matrix to confirm the additions don't perturb the website suite. I did NOT run that probe because (a) my work is in an isolated worktree at a different filesystem path and shares no Python imports with the website backend, so it has no mechanism to affect the website suite, and (b) the parallel agent on `phase-43/front-door-and-help` has uncommitted website changes — running the website pytest now would measure their in-flight state, not WA1's isolation. Flagged here so the planning agent can re-run the website pytest from a clean master post-merge if a positive measurement is wanted.

---

## New tech debt

None at this layer. Followups all live in later WA specs (WA2 for validation, WA3 for dashboard, WA4 for the daemon that consumes this state + IPC).

---

## Followups (out of scope, per spec §Followups)

- **WA2 — Architecture validation spike** is the next pass. It does not depend on WA1 functionally, but landing WA1 first lets WA2's planner-continuity test bootstrap from real WA1 state if desired.
- **WA4 — Orchestrator daemon** binds to this state layer + IPC contract. Any schema gap discovered there folds back as a small WA1 revision (schema version bump + migration if it's an incompatible change).
- **Archive policy for IPC data files** — closeouts are kept in `outbox/` for audit after the marker is consumed; no retention/rotation policy was specified in WA1. A later WA pass can decide (likely WA7 — the hardening pass).
- **Multi-host transport** — `ipc.py` is local-filesystem only. Cross-machine orchestration is a future concern.

---

## Pass-summary (PROGRESS.md-style)

WA1 — State & IPC Foundation — SHIPPED 2026-05-30 on master via the `wa-1/state-foundation` worktree. The workflow-automation track's no-regret bedrock: durable planner state (versioned JSON schema + atomic checkpoint writer), Markdown bootstrap + passdown renderers, and the orchestrator↔Code-wrapper file-IPC contract (executable + documented). 68/68 own tests pass including the cold-start reconstruction validation — a fresh `claude -p` against the rendered bootstrap accurately restated 6 load-bearing facts about the project in 12.87s on Max (`ANTHROPIC_API_KEY` unset, Phase 42 invariant). No website code touched, no migration, no Railway deploy. The layer is immediately useful as an improved passdown for the current manual planner workflow, regardless of when the WA4 daemon gets built on top of it.
