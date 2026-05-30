# WA1 — State & IPC Foundation

**Status:** Spec, dispatched [pending]. Written 2026-05-30. Workflow-automation track (see `workflow-automation/workflow_automation_overview.md` — read it first).

Combined dispatch framing (top) + spec body (below), per the repo's spec convention. This is the **no-regret bedrock** of the workflow-automation track: the durable-state, checkpoint, passdown, and file-IPC layer the persistent planner and orchestrator daemon will sit on. It needs no Agent SDK, no Max-vs-API decision, and no network LLM calls except a free `claude -p` validation step. It is buildable and mergeable today, and it independently improves passdown for the *current* manual planner workflow.

---

## Dispatch framing

### Goal

Build the persistent planner's memory substrate and the daemon↔Code-wrapper communication contract:

1. A **durable planner-state schema** on disk — the structured record a fresh planner instance reads to reconstruct full working context (project state, decisions, loop status, conversation digest).
2. An **atomic checkpoint writer** — a small Python API the (future) orchestrator uses to update state safely (no torn writes on crash).
3. A **bootstrap/recovery routine** — given the state dir, produce the "come up to speed" context a fresh planner session is handed, and prove a cold `claude -p` reconstructs the project's situation from it.
4. A **passdown generator** — produce a human-readable passdown doc from the state (goal 5), replacing the current hand-written passdown effort.
5. The **file-IPC contract** — the on-disk directory layout + marker conventions for orchestrator↔Code-wrapper handoff (spec inbox, closeout outbox, signals, state dir), documented so WA4+ build against a fixed contract.

This pass writes the layer + tests; it does NOT build the daemon, the planner loop, the dashboard, or any dispatch. Those are later WA passes.

### Branch + merge

Branch: `wa-1/state-foundation`. `--no-ff` merge to master per repo convention. No Railway deploy (this track never deploys to the website infra).

### Verification matrix

| Check | Required | Notes |
|---|---|---|
| WA-track unit tests (new) | ✅ | New `workflow-automation/tests/` (pytest). Cover: schema validation, atomic-write (incl. simulated mid-write crash → no corruption), round-trip read, passdown generation, recovery routine. |
| **State round-trip test** | ✅ | Write a representative state → read back → assert structural + value equality. |
| **Atomicity test** | ✅ | Simulate interruption during write (write-temp-then-rename pattern); assert the prior good state survives and no partial file is read. |
| **Cold-start reconstruction validation** | ✅ | Reuse Phase 42's method: point a fresh `claude -p --dangerously-skip-permissions` at the generated bootstrap context + state dir; confirm it accurately restates the project's current situation (phase, pending, key decisions). Runs on Max — no metered spend (`ANTHROPIC_API_KEY` unset). Capture transcript excerpt. |
| Passdown generation test | ✅ | Generate a passdown from sample state; assert it contains the load-bearing fields and is human-readable. |
| Backend (website) pytest | ✅ | Run once to confirm this track's additions didn't perturb the website suite (expected unchanged at the 1476/27 baseline). No website code is touched. |
| PG smoke / Railway / frontend bundle | ❌ N/A | This track touches no website app code, migrations, or deploy. State explicitly in closeout. |
| File-count | ✅ | New files under `workflow-automation/` only. |

### Suggested team structure

Single backend-capable dev + lead (or single full-stack agent). ~2–4 hours. **Continuing dev team** is the right fit — they hold the repo's Python/scripts conventions and the Phase 42 `claude -p` patterns this reuses. No QA-teammate cluster (the "QA" is the cold-start reconstruction validation, run by the dev).

### Sequence

1. Define the state schema (B1) — agree the fields + format before writing code.
2. Implement the checkpoint writer + atomic-write (B2).
3. Implement bootstrap/recovery + passdown generator (B3).
4. Define + document the file-IPC contract (B4).
5. Tests, incl. the cold-start reconstruction validation (B5).
6. Merge.

### Load-bearing decisions

- **This is a library + conventions pass, not a daemon.** No long-running process, no LLM orchestration, no dispatch. Resist scope creep toward "just wire up the loop while we're here" — WA4 owns that, and it depends on WA2's findings.
- **State format: human-readable + machine-parseable.** Recommend JSON for machine state + a generated Markdown view for human/`claude -p` consumption (the cold-start session reads Markdown well; Phase 42 showed it orients from Markdown docs in seconds). Dev picks the exact split; document it.
- **Atomic writes via write-temp-then-rename** (POSIX-atomic; on Windows use the documented atomic-replace pattern). Crash-safety is a real requirement — the daemon will checkpoint mid-loop and Windows can reboot under it.
- **The IPC contract is a documented spec, even though the wrapper isn't built here.** WA4 and the Phase 42 wrapper both bind to it; fix it now so later passes don't drift. Mirror Phase 42's findings on cwd-slugging and env hygiene where relevant.
- **No secrets, no tokens in state files.** State is project/loop context only. (Slack tokens etc. live in env/config, handled in their own passes.)

### Operational watch-outs

- **Windows path + atomic-rename semantics.** Test the atomic-write on Windows specifically (the dev runs there). `os.replace` is atomic on Windows for same-volume; confirm.
- **`claude -p` for the validation step uses Max, not API.** Unset `ANTHROPIC_API_KEY` in the validation subprocess env (Phase 42 lesson). The validation is read-only — the cold session reports what it understands; it must not modify repo state (instruct it explicitly, as Phase 42's spike-test dispatch did).
- **Keep the schema small and evolvable.** Version the schema (a `schema_version` field) so later WA passes can migrate it. Don't over-design fields we can't yet justify; cover the goal-5 passdown needs + the loop-state the daemon will obviously need (current phase, pending, blocked, last Code activity, decisions log, project digest).

### Closeout reports back

- The state schema (fields + format split) with rationale.
- Checkpoint-writer API surface; atomicity approach + the crash-simulation test result.
- Bootstrap/recovery + passdown generator behavior.
- The file-IPC contract (the directory layout + markers) as a documented artifact.
- **Cold-start reconstruction result** — did a fresh `claude -p` accurately restate the project situation from the generated bootstrap? Transcript excerpt (the goal-5 proof).
- Test results; confirmation the website suite is unperturbed; file list (all under `workflow-automation/`); branch + commit SHAs.
- Explicit "no migration / no Railway / no bundle — N/A this track."

---

## Status block

The workflow-automation track's first build pass. The overview doc establishes that the persistent planner is delivered as a long-lived `claude -p --resume` session plus an orchestrator daemon, with continuity backed by a durable checkpoint layer that also enables low-effort passdown and safe session rotation. WA1 builds *that layer* and nothing else — deliberately, so it's mergeable, testable, and immediately useful (a better passdown for the current manual planner) regardless of when the daemon itself gets built.

It reuses two Phase 42 findings as settled fact: a fresh `claude -p` cold-starts from checked-in docs accurately and fast (the basis for the recovery model), and `--resume`/`-p` run on Max with `ANTHROPIC_API_KEY` unset (the basis for the free validation step).

## Locked decisions

- **D1 — Library + conventions only.** No daemon, no loop, no dispatch, no dashboard, no Slack.
- **D2 — JSON machine state + generated Markdown view** (dev finalizes the split; document it).
- **D3 — Atomic write via temp-then-`os.replace`;** crash-simulation test required.
- **D4 — Schema is versioned** (`schema_version`) for later migration.
- **D5 — The file-IPC contract is documented here** as the fixed interface WA4 + the Phase 42 wrapper bind to.
- **D6 — Validation `claude -p` runs read-only on Max, env `ANTHROPIC_API_KEY` unset.**

## What this pass IS

A self-contained Python package under `workflow-automation/` providing: a versioned planner-state model, an atomic checkpoint writer, a bootstrap/recovery routine, a passdown generator, a documented file-IPC contract, and a pytest suite including a cold-start reconstruction validation.

## What this pass is NOT

- Not the orchestrator daemon or planner loop (WA4).
- Not the dashboard (WA3), QA agent (WA5), or Slack channel (WA6).
- Not any `claude -p` *dispatch* of Code (just the read-only validation probe).
- Not a touch of website app code, migrations, or deploy infra.

## Cluster B — Build

### B1 — State schema

Define a versioned schema capturing what a fresh planner needs to reconstruct full context. At minimum: `schema_version`; project digest (what the project is, current platform state pointer); loop state (current WA or website phase in flight, pending items, blocked items, last Code activity + result); a decisions log (append-only, dated); and a conversation/working-context digest (rolling summary of recent planner↔Z strategy that isn't yet a formal decision). Keep it small and justified.

### B2 — Checkpoint writer

A small API (e.g., `state.update(...)`, `state.append_decision(...)`, `state.snapshot()`) that persists atomically (temp-then-`os.replace`). Must be safe against mid-write interruption. Include the crash-simulation test.

### B3 — Bootstrap/recovery + passdown

- **Bootstrap:** given the state dir, render the "come up to speed" context (Markdown) a fresh planner session is handed at start/rotation.
- **Passdown generator:** produce a human-readable passdown doc from current state — the automated replacement for today's hand-written passdown (goal 5). Should read like the planning-agent passdowns already in the repo.

### B4 — File-IPC contract

Document (and stub the directory layout for) orchestrator↔Code-wrapper handoff: spec-inbox (planner writes specs the wrapper picks up), closeout-outbox (wrapper writes Code closeouts the daemon reads), signal/marker files (state transitions), and the state dir. Specify cwd discipline + env hygiene per Phase 42. This is a written contract + directory scaffolding, not a running wrapper.

### B5 — Tests + cold-start validation

Pytest under `workflow-automation/tests/`: schema validation, round-trip, atomicity/crash-sim, passdown generation, recovery. Plus the **cold-start reconstruction validation**: generate bootstrap context from a representative state, run a read-only `claude -p` against it, assert (and capture) that it accurately restates the project situation. This asserts the *side effect* (the layer actually enables reconstruction), not just that functions return values.

## Operational notes

- Run from the repo root or `workflow-automation/`; match the repo's Python invocation style (see `backend/scripts/poll_deploy.py`).
- The cold-start validation is the one step that calls `claude -p`; everything else is local and offline.
- Keep all artifacts under `workflow-automation/`. Nothing in `backend/` or `frontend/`.

## Followups

- WA2 (architecture validation spike) runs in parallel or right after; it does not depend on WA1, but WA1's state format is what WA2's planner-continuity test will bootstrap from, so landing WA1 first is mildly preferable.
- WA4 (daemon + planner core) binds to WA1's state layer + IPC contract; any schema gaps surfaced there fold back as a small WA1 revision.
