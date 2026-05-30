# File-IPC contract — orchestrator daemon ↔ Code wrapper

**Status:** Stable contract, written 2026-05-30 as part of WA1 B4. WA4 (orchestrator daemon) and any descendant of the Phase 42 Code wrapper bind to this. Schema-versioned via the field below; any incompatible change bumps the version + writes a migration note here.

Contract version: **1**

The executable expression of this contract lives in `workflow-automation/planner_state/ipc.py` (`IPCLayout`); this doc is the prose description and rationale.

---

## Directory layout

The orchestrator daemon owns an IPC root directory (typically a sibling of the planner state dir — call it `{ipc_root}`). Inside that root:

```
{ipc_root}/
├── inbox/      planner → Code wrapper        (specs to pick up)
├── outbox/     Code wrapper → planner        (closeouts to read)
├── signals/    transient state-transition markers (planner + wrapper both write here)
└── workdir/    per-pass scratch cwd for the Code wrapper
```

`workdir/` is the cwd the Code wrapper invokes `claude -p` from (Phase 42's "per-cwd session slugging" finding requires a stable cwd per pass — `workdir/{spec_id}/` is the recommended sub-layout).

## Marker discipline (the load-bearing convention)

Spec/closeout file writes are split into TWO file operations:

1. The **data file** (`{spec_id}.md` or `{spec_id}.closeout.md`) is written via the atomic temp-then-`os.replace` dance. The data file's presence does NOT signal readiness — only that *some* version of it exists.
2. A **marker file** (`{spec_id}.ready` or `{spec_id}.closeout.done`) is written as a zero-byte file AFTER the data file is durable. The marker's presence is the load-bearing signal "this data is ready to consume."

The polling consumer (wrapper for inbox, daemon for outbox) MUST look only at marker files when deciding whether to act. This is what guarantees the consumer never picks up a half-written spec/closeout — the data file is durable before the marker exists, and the marker is atomic-creation.

After consuming, the reader removes the marker (`claim_spec` / `consume_closeout`). The data file is left in place for audit; an archive/retention policy is a later WA concern (don't delete data files in WA1).

## Signals

`signals/` carries transient one-shot markers for state transitions outside the spec-closeout lifecycle. Examples (illustrative — the actual signal namespace gets locked in WA4):

- `planner.rotated.signal` — the planner session was rotated; the new session id is in the signal's JSON detail.
- `daemon.shutdown_requested.signal` — graceful-shutdown request from elsewhere.
- `wrapper.heartbeat.signal` — heartbeat for the dashboard.

Signals follow the same marker-suffix discipline (`.signal`). The reader is responsible for calling `clear_signal` after acting. Signals are NOT a message queue — losing a signal because two writers race to overwrite is acceptable. If a feature needs guaranteed delivery, it goes in inbox/outbox.

## Concurrency stance

- **Single-writer per direction.** The planner is the sole writer to `inbox/`; the wrapper is the sole writer to `outbox/`. Each side is read-only on the other's dir. No locks needed.
- **`signals/` allows multiple writers** but each signal name has at most one writer — name conflicts are a contract bug, not a race.
- **`workdir/` is owned by the wrapper.** The daemon writes nothing here; it reads only for audit / dashboard display.

## Atomicity guarantee

All data-file writes go through `_atomic_write_text` in `ipc.py`:
1. Open a temp file in the same directory (sibling of the target).
2. Write + flush + fsync.
3. `os.replace` the temp over the target.

`os.replace` is atomic on POSIX and on Windows when source + destination are on the same volume — which they always are in this layout. A crash mid-write leaves the prior target file unchanged + an orphan temp file (cleaned by the next successful write).

## cwd discipline (Phase 42 carry-forward)

The Code wrapper invokes `claude -p` from a stable cwd per pass. Phase 42's `docs/workflow_spike_resume_findings.md` documents the per-cwd session slugging behavior — sessions persist at `~/.claude/projects/<cwd-slug>/<session_id>.jsonl`, so a stable cwd is required for `--resume` to find the same session across invocations.

Recommended layout: `{ipc_root}/workdir/{spec_id}/` — the spec is identified by `spec_id`, the wrapper cd's there, claude sessions for that pass live under that cwd slug.

## Env hygiene (Phase 42 carry-forward)

Any process spawning `claude -p` MUST `del env["ANTHROPIC_API_KEY"]` (or otherwise unset it) before the subprocess call. Phase 42 found that a stray `ANTHROPIC_API_KEY` silently switches `claude -p` to metered API billing AND a different auth path. The Phase 42 spike harness (`backend/scripts/workflow_resume_spike.py::_claude_env`) is the canonical reference; copy that pattern.

## What's NOT in the contract

- **Authentication tokens.** No Slack tokens, Anthropic API keys, etc., go in IPC files. Auth lives in env/config (WA6 / phone-channel pass).
- **Cross-host transport.** This is a local-filesystem contract. Cross-machine orchestration is a future concern that would either ride on a shared mount or require a different transport layer.
- **A message-queue replacement.** Signals can be lost under contention; if you need queue semantics, use inbox/outbox.

## Evolution policy

- Backwards-compatible additions (new signal names, new marker suffixes that don't collide with existing ones) ship without a contract version bump but DO get added to this doc.
- Renames or semantic changes bump the contract version and ship with a migration note. Both sides (orchestrator daemon + Code wrapper) version-check on startup; mismatched versions refuse to interoperate (loud failure, not silent drift).
