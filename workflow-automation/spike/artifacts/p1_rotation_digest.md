# Planner rotation digest — workflow-automation

This digest carries the load-bearing state from the prior
`--resume` session forward into a fresh planner instance.

## Current tracker

`TRACKER: WA1_status=done, WA2_status=specced_not_started, next_pass=WA2`

## Project

- **Project:** Liquid Democracy + workflow-automation track
- **Prod URL:** https://www.liquiddemocracy.us
- **Workflow track shipped:** WA1 (State & IPC Foundation)
- **In flight:** WA2 (this spike — architecture validation)

## Decisions established earlier this session

- **R1_seed:** Context absorbed. The workflow-automation track is a separate initiative from the website work, building a persistent autonomous planner/orchestrator that dispatches `claude -p` subprocesses (Max-subscription path, not Agent SDK) with continuity backed by a durable state layer plus session rotation. WA1 (state + IPC foundation: schema, atomic checkpoint writer, bootstrap/passdown renderers, file-I
- **R2_recall_seed:** TRACKER: WA1_status=done, WA2_status=specced_not_started, next_pass=WA2  - **Goal 3 (Max account, not API credits)** — directly hit. The entire architecture rests on `claude -p` CLI reusing the Max subscription's auth. A Max-OAuth-incompatible change kills the sanctioned path; the only fallback is metered Console API keys, which violates this goal explicitly. - **Goal 1 (Persistent planner)** — co
- **R3_decision_application:** TRACKER: WA1_status=done, WA2_status=specced_not_started, next_pass=WA2  - **WA1 cold-start reconstruction validation (B5).** The pytest harness that spawns a fresh `claude -p --dangerously-skip-permissions` against the generated bootstrap context must unset `ANTHROPIC_API_KEY` in the subprocess env, or the validation step silently flips to metered billing — corrupting both the "no metered spend" 
- **R4_cross_pass_dependency:** TRACKER: WA1_status=done, WA2_status=specced_not_started, next_pass=WA2  **WA1 deliverables WA4 depends on:** - **State schema (B1) + checkpoint writer (B2)** — WA4's daemon checkpoints loop/orchestration state mid-run and reloads it on restart; the schema + atomic-write API is the substrate that makes the daemon crash-safe and the planner session rotatable. - **Bootstrap/recovery routine (B3)** —
- **R5_synthesis:** You're out of extra usage · resets 12:30pm (America/Port-au-Prince)
- **R6_update_tracker:** You're out of extra usage · resets 12:30pm (America/Port-au-Prince)
- **R7_recall_post_update:** You're out of extra usage · resets 12:30pm (America/Port-au-Prince)
- **R8_long_context:** You're out of extra usage · resets 12:30pm (America/Port-au-Prince)
- **R9_recall_drift_check:** You're out of extra usage · resets 12:30pm (America/Port-au-Prince)
- **R10_planning_judgment:** You're out of extra usage · resets 12:30pm (America/Port-au-Prince)

## What the fresh planner should do

- Confirm you can restate the tracker line.
- Name the next pass + brief rationale.
- Confirm you can continue planning from this digest alone.
