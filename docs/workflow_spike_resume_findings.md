# Phase 42 — Workflow Automation Viability Spike Findings

**Date:** 2026-05-29
**Pass:** Phase 42 (investigation spike, no app code)
**Source spec:** `phase42_workflow_viability_spike_spec.md`
**Branch:** `phase-42/workflow-viability-spike`

## Headline recommendation

**GO** on the wrapper architecture as currently designed. Both empirical unknowns the spike targeted came back clean:

- **S1 (PRIMARY) — Headless cold-start viability: PASS.** A fresh `claude -p` session, given only a dispatch line + the checked-in docs, came up to speed in ~57 seconds and produced coherent, convention-following output. It read CLAUDE.md, located the right files, and answered convention-following questions correctly. The spec-self-sufficiency design works as advertised.
- **S2 (SECONDARY) — `--resume` durability: PASS.** All 12 fresh-process `--resume` rounds (plus the seed) recalled every prior fact with zero failures. Latency held flat at 3.5–4.6 s per round. Context budget remained well within limits — cache-read growth was linear and modest. Cross-invocation resume from a completely separate shell (no harness parent) also recalled all 15 facts.

**State-model recommendation:** **fresh-session-per-pass as the wrapper's default**, consistent with the spec's working assumption (D1.5). `--resume` is solid enough to use for within-pass back-and-forth rounds (QA→fix→re-verify, follow-up clarifications) — no rotation trigger surfaced in 12 rounds at the small-prompt scale of this spike. Keep `--resume` as the within-pass tool; rotate between passes by simply not threading a session ID forward.

**Chrome MCP contention (S3):** deferred to the Cowork-QA build pass. Protocol documented below.

---

## S1 — Headless cold-start viability + `-p` non-negotiables

### S1.1 — Cold-start run (the gate)

**Setup:** A throwaway low-risk dispatch was created at the repo root (`phase42_spike_test_dispatch.md`) asking a fresh session to read CLAUDE.md + PROGRESS.md and answer five convention-following questions. The dispatch is read-only — explicitly instructs the session NOT to commit, branch, or modify anything.

**Command (run from a scratch cwd outside the repo):**

```bash
unset ANTHROPIC_API_KEY
claude -p --dangerously-skip-permissions --output-format json \
  --add-dir /c/Users/zachk/liquid-democracy \
  -- "Read and execute the dispatch in /c/Users/zachk/liquid-democracy/phase42_spike_test_dispatch.md"
```

**Result:** exit 0 in 57 seconds, 11 turns, no errors, no permission denials, no API key set.

**Quality assessment (qualitative):** The session correctly identified:

1. Project domain ("multi-tenant web platform for liquid-democracy governance — orgs run proposals with delegation-based voting (binary / approval / RCV / STV)…")
2. Most-recent shipped phase ("Phase 41 — Tech Debt Audit Refresh + Bundled Tier-1 Fixes, closed 2026-05-28")
3. Branch convention for Phase 99 ("`phase-X-Y/short-name` … `phase-99/<short-name>`, sub-pass `phase-99a/<short-name>`")
4. Migration pre-merge requirements (reversible + cycle test + PG smoke + named prior revision)
5. Tier-1 audit doc location (`docs/tech_debt_audit_2026-05.md`)

It also accurately observed that "PROGRESS.md itself stops at Phase 8.6 in the leading section — recent phase state lives in the per-phase spec/closeout files and the audit doc." That's a real fact about the project (PROGRESS.md is stale at the leading section), and noticing it required actually reading the file rather than guessing — strong evidence the cold-start session is doing the work, not pattern-matching from a generic prior.

**Transcript excerpt (verbatim, head of result):**

> # Phase 42 cold-start probe — report
>
> **1. What does this project do?**
> A multi-tenant web platform for liquid-democracy governance — orgs run proposals with delegation-based voting (binary / approval / RCV / STV), sub-org scopes, and configurable sustained-majority windows.
>
> **2. Most recent shipped phase**
> **Phase 41 — Tech Debt Audit Refresh + Bundled Tier-1 Fixes**, closed 2026-05-28 (per `docs/tech_debt_audit_2026-05.md` header + `phase41_closeout.md`). PROGRESS.md itself stops at Phase 8.6 in the leading section — recent phase state lives in the per-phase spec/closeout files and the audit doc.

**Verdict:** **PASS** — the headless cold-start is viable. The cold session orients from the docs and produces convention-following output without any priming or session continuity.

### S1.2 — The three `-p` non-negotiables

Each confirmed in the same run + a follow-on MCP probe:

| Non-negotiable | Status | Evidence |
|---|---|---|
| `--dangerously-skip-permissions` headless | ✓ PASS | Both S1 runs completed with `permission_denials: []`, no prompts (stdin closed). The flag works in non-interactive mode. |
| `.mcp.json` MCP loads + tool callable in `-p` | ✓ PASS | A minimal `.mcp.json` in the cwd defined the `@modelcontextprotocol/server-everything` server. The fresh `-p` session listed the `everything` server's 13 tools (including `get-sum`) alongside the user-level Gmail/Google Calendar/Drive MCPs, then called `mcp__everything__get-sum` with `a=2, b=3` returning `5`. Project-local `.mcp.json` loading works in `-p` mode. |
| Max OAuth path, `ANTHROPIC_API_KEY` UNSET, no `--bare` | ✓ PASS | Subprocess env confirmed unset. Both runs succeeded with exit 0. CLI version 2.1.119. The `total_cost_usd` field appears in the JSON output (~$0.54 for the cold-start run) but is computed for telemetry — not actually billed via API since Max OAuth was the auth path. |

Built-in Chrome MCP was absent from `-p` mode's tool list (expected per prior findings; QA moves to the Cowork side).

---

## S2 — `claude -p --resume` durability harness

**Harness:** `backend/scripts/workflow_resume_spike.py` (committed). Drives:

1. **Seed round** — establishes 3 distinctive facts (`codename=Borealis`, `magic_number=47`, `liaison_name=Quill`) and parses `session_id` from the JSON output.
2. **12 resume rounds** — each is a fresh `claude -p --resume <session-id>` subprocess invocation. Each round (a) asks the model to restate every fact established so far as a `key=value` list with no commentary, and (b) introduces one new fact for future rounds.

Each round's recall is graded by case-insensitive substring match of each expected fact's value in the result text. Output captured as CSV + JSON (`/tmp/p42_spike/workflow_resume_results.{csv,json}`).

**Non-negotiables enforced in the harness:**

- `ANTHROPIC_API_KEY` explicitly removed from the subprocess env (so Max OAuth path is used, not API).
- `--bare` is NOT passed.
- Each round is a separate `subprocess.run([...])` — no long-lived parent process spans rounds.

### S2.1 — Per-round results

`session_id`: `b4fe0115-f607-4f62-b79b-afd03c5ca709`

| Round | What it adds | elapsed_s | input_tok | cache_create | cache_read | output_tok | Recall |
|---|---|---|---|---|---|---|---|
| 0 (seed) | 3 seed facts | 3.53 | 6 | 8296 | 19263 | 31 | 3/3 ✓ |
| 1 | city=Rivendell | 4.36 | 6 | 148 | 27559 | 36 | 3/3 ✓ |
| 2 | drink=petrichor | 3.65 | 6 | 153 | 27707 | 44 | 4/4 ✓ |
| 3 | color=vermilion | 3.76 | 6 | 160 | 27860 | 51 | 5/5 ✓ |
| 4 | animal=axolotl | 4.32 | 6 | 168 | 28020 | 59 | 6/6 ✓ |
| 5 | ship=Gossamer | 3.84 | 6 | 177 | 28188 | 68 | 7/7 ✓ |
| 6 | instrument=theorbo | 4.52 | 6 | 186 | 28365 | 77 | 8/8 ✓ |
| 7 | season=Solstinox | 3.83 | 6 | 194 | 28551 | 85 | 9/9 ✓ |
| 8 | constellation=Cor Caroli | 4.15 | 6 | 206 | 28745 | 97 | 10/10 ✓ |
| 9 | flower=Hellebore | 4.28 | 6 | 215 | 28951 | 106 | 11/11 ✓ |
| 10 | library=Codex Atlanticus | 4.33 | 6 | 383 | 29166 | 118 | 12/12 ✓ |
| 11 | month=Brumaire | 4.59 | 6 | 235 | 29549 | 126 | 13/13 ✓ |
| 12 | river=Limmat | 4.50 | 6 | 242 | 29784 | 133 | 14/14 ✓ |

**Aggregates:**

- **Recall: 12/12 PASS.** Every round recalled every prior fact exactly. Zero misses across the run.
- **Latency: stable.** Range 3.65–4.59 s, median ~4.2 s. No drift across rounds.
- **Token usage growth: linear, modest.** `cache_read_input_tokens` grew from ~19k (seed) to ~30k (round 12). `cache_creation_input_tokens` stayed small (~150–235) after the seed (8296), meaning most context is cache-hit and cheap. No truncation or context-limit warning surfaced.
- **Errors: zero.** Exit code 0 for all 13 invocations. No rate-limit hit. No timeouts.
- **Cost: trivial.** Total `total_cost_usd` across all 13 invocations was well under $1. Note: `--bare` was deliberately NOT used, so this exercises the same auth + caching the wrapper will use.

### S2.2 — Cross-invocation resume (post-harness)

After the harness exited, a single manual `claude -p --resume <session-id>` was run from a completely separate shell (the harness parent process gone). Result:

```
codename=Borealis
magic_number=47
liaison_name=Quill
city=Rivendell
drink=petrichor
color=vermilion
animal=axolotl
ship=Gossamer
instrument=theorbo
season=Solstinox
constellation=Cor Caroli
flower=Hellebore
library=Codex Atlanticus
month=Brumaire
river=Limmat
```

All 15 facts (3 seed + 12 round-introduced) recalled perfectly in 5 seconds. Cross-invocation resume is confirmed — the session is persisted to disk and any future process can resume it given the session_id.

### Session file location (for the wrapper to manage)

Sessions persist as JSONL files under:

```
~/.claude/projects/<cwd-slug>/<session_id>.jsonl
```

For this spike's cwd of `/tmp/p42_spike/` (Windows: `C:\Users\zachk\AppData\Local\Temp\p42_spike`), the slug was:

```
~/.claude/projects/C--Users-zachk-AppData-Local-Temp-p42-spike/b4fe0115-f607-4f62-b79b-afd03c5ca709.jsonl
```

Per-cwd slugging means the wrapper must invoke `claude` from the same cwd it seeded the session in — or pass `--add-dir` explicitly, but the resume lookup still uses the cwd to find the session. If the wrapper runs from a stable per-pass cwd (e.g., the project root), this is automatic; if it changes cwd between passes, sessions may not resolve.

### Degradation projection

No degradation surfaced at 12 rounds with small prompts. Extrapolating linearly:

- `cache_read_input_tokens` grew ~1k per round (after the seed bump). At ~200k/round (the typical Claude context limit at the cache-read tier), that's ~200 rounds before any structural concern — well beyond the per-pass scale we care about.
- The ~10s budget the spike's prompts used per round is dwarfed by typical workflow-pass costs (which run minutes to hours). `--resume` overhead is negligible.

**No rotation trigger surfaced.** If the wrapper does need a rotation policy (defensive), the natural triggers are: (a) any round with elapsed_s > 30 s (suggests context bloat or cache miss), or (b) any round where the JSON `usage.cache_read_input_tokens` exceeds a configurable threshold (e.g., 150k). Neither came close in the 12-round run.

---

## S3 — Chrome MCP contention (deferred)

**Status:** DEFERRED to the Cowork-QA build pass per spec D6 (best-effort, not a blocker).

**Reason:** The contention check requires coordinated probing from BOTH the Code-side session (this one) AND the Cowork-side session against the same Chrome extension. The Cowork side requires Z to drive it; that wasn't part of this single-Code-session pass.

**Protocol — first task of the Cowork-QA build pass:**

1. **Setup.** Z launches an interactive `claude code` session in one terminal. In another window, Z's Cowork planner is loaded with the Chrome MCP enabled.
2. **Code holds a tab.** The Code session calls `mcp__claude-in-chrome__tabs_create_mcp` to create Tab A, then calls `mcp__claude-in-chrome__navigate` to send it to a known URL (e.g., `https://www.liquiddemocracy.us/`). Code writes a marker file `/tmp/code_holding.flag` after the call succeeds, with the Tab A ID inside.
3. **Cowork acts on a different tab.** Z asks the Cowork planner to (a) call `tabs_create_mcp` to create Tab B, (b) navigate Tab B to a different URL, and (c) read the page text of Tab B. Cowork should explicitly NOT touch Tab A.
4. **Probe.** From the Code session, immediately re-call `mcp__claude-in-chrome__read_page` on Tab A. Record whether: the tab is still focused, the read returns the expected URL's content, any error surfaces.
5. **Reverse.** Now have Cowork act on Tab B again while Code is idle. Record any focus theft or extension lock.
6. **Stress.** Have both sides call MCP tools simultaneously (using Z's terminal to fire them within a 1-second window). Record any race-condition errors, lock contentions, or tab confusion.

**Expected outcomes (working hypothesis from the broader handoff doc):** Chrome MCP uses per-tab IDs as the addressing scheme. As long as each side uses a dedicated tab, no contention should surface. The protocol exists to confirm this empirically before the wrapper architecture relies on it.

**Mitigation if contention DOES surface:** dedicate one tab per agent at session start. Code holds Tab "code-primary"; Cowork holds Tab "cowork-qa". Neither side touches the other's tab. If the extension can't disambiguate, fall back to single-side QA (Code does its own QA in interactive mode; Cowork-driven QA reserved for async passes).

---

## Recommendations

### Wrapper architecture: GO

The PRIMARY gate (S1 cold-start viability) passed cleanly. Fresh `claude -p` sessions can do what the wrapper will ask of them on every pass. The wrapper can be designed simply:

```text
for each pass in inbox:
    spec_path = pass.spec_path
    cwd = project_root
    # No --resume — cold-start each pass.
    result = run_claude_p(
        cwd=cwd,
        prompt=f"Read and execute {spec_path}",
        flags=["--dangerously-skip-permissions",
               "--output-format", "json"],
        env=os_environ_without("ANTHROPIC_API_KEY"),
    )
    closeout_path = parse_closeout_path(result)
    notify_planner(closeout_path)
```

No session state to thread between passes. No rotation logic needed at the wrapper layer. Each pass is independent — the spec-self-sufficiency design carries the load.

### State model: fresh-per-pass default; `--resume` as the within-pass tool

- **Cross-pass:** **fresh session per pass.** The wrapper does NOT thread session IDs forward between passes. Each pass is a clean cold-start. Consistent with the project's design principle (spec self-sufficiency) and Z's signal (no quality difference observed with fresh instances).
- **Within-pass:** **`--resume` is solid and usable** for back-and-forth rounds within a single pass (e.g., QA-found-bug → Code-fixes-it → QA-re-verifies). The harness proved 12 fresh-process resume rounds work flawlessly with no drift and no usage concern.
- **Rotation policy:** None needed at this scale. If the wrapper ever wants defensive rotation, the natural triggers are `elapsed_s > 30s` (suggests degradation) or `cache_read_input_tokens > 150k` (suggests bloat). Neither hit in the 12-round spike.

### Cwd discipline

The wrapper MUST invoke `claude -p` from a stable cwd per pass — preferably the project root. Sessions are slugged by cwd in `~/.claude/projects/<cwd-slug>/`; changing cwd between resume invocations may cause the session lookup to fail.

If the wrapper wants pass-isolated cwds (e.g., to prevent one pass's failed work from polluting another's session history), it can use per-pass scratch directories, BUT each round of that pass must run from the same scratch cwd. The wrapper should manage this explicitly.

### Cowork-QA build pass: blocked-on-nothing

The Chrome MCP contention check is the first task of that pass (protocol above). Otherwise the build can proceed.

### Slack auth durability

Out of scope for this pass per spec. Still untested. Should be the first task of the file-conventions/Slack build stage.

---

## What this pass produced

| Artifact | Location | Purpose |
|---|---|---|
| Findings doc (this file) | `docs/workflow_spike_resume_findings.md` | Recommendation + evidence for the wrapper architecture. |
| Harness script | `backend/scripts/workflow_resume_spike.py` | Reproducible. Re-run anytime with `python backend/scripts/workflow_resume_spike.py --rounds N --cwd PATH --out PATH`. |
| Cold-start dispatch (throwaway) | `phase42_spike_test_dispatch.md` | The dispatch the S1 cold-start session was pointed at. Read-only target. |
| Per-round metrics | `/tmp/p42_spike/workflow_resume_results.{csv,json}` | Raw data from the 12-round run (not committed; reproducible via harness). |

**Not produced:** wrapper script, scheduled task, file conventions doc, QA scenario format, Slack notification format — all reserved for the future build passes per the broader handoff doc.

## Operational notes

- **Subprocess env hygiene is load-bearing.** The harness explicitly removes `ANTHROPIC_API_KEY` from the subprocess env. The wrapper must do the same — otherwise it silently switches to API billing AND a different auth path than Max OAuth, invalidating the entire architecture. This is one line of code; easy to miss.
- **Prompt-as-positional-after-`--`** is the safest invocation shape, especially with `--add-dir`. Forms like `claude -p "prompt"` work but flag/positional ordering is brittle. Use `claude -p ... -- "prompt"`.
- **CLI version pinned for evidence:** Claude Code 2.1.119. Behavior may differ on later versions; if the wrapper ever sees recall failures, the first diagnostic is to re-run this harness on the new CLI version.
