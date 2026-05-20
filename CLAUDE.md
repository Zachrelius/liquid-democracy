# CLAUDE.md — Team Operating Conventions

This file is loaded automatically by Claude Code at session start. Keep it under 200 lines. Project context lives in PROGRESS.md and the active spec; this file is for working-style conventions only. When a dispatch says something different from this file, the dispatch wins for that pass.

## Operating mode

This project runs Claude Code with `--dangerously-skip-permissions` enabled. There is no permission prompting; every bash command runs immediately. The safety net is git history + Railway rollback + the conventions in this file (one branch per phase, no-ff merges to master, no force-pushes, never `alembic downgrade base` in production, never destructive SQL against prod). Operate with appropriate care; treat the absence of prompts as trust to be earned, not as license. If you're about to run something genuinely irreversible (force-push, hard reset, schema drop), pause and surface it to the closeout for explicit Z review BEFORE running it.

## Reading order at session start

1. The active phase doc for the pass you're working on (e.g., `phase19_public_delegate_pages_spec.md`). As of Phase 19 this is one merged dispatch+spec doc — read it FIRST and read it FULL before touching code.
2. `PROGRESS.md` — canonical session passdown, what's shipped through the most recent phase
3. `TECHNICAL_SUMMARY.md` — architecture overview if you need orientation
4. `future_improvements_roadmap.md` — forward-looking scope; reference but don't assume anything in it is being built unless a spec says so

## Spec format convention (Phase 19+)

Each pass ships as **one document** at the repo root:

- **X.0 passes:** `phaseXX_<short-name>_spec.md` (e.g., `phase19_public_delegate_pages_spec.md`).
- **Sub-numbered passes:** `phaseXX_Y_<short-name>_spec.md` with an **underscore** between the major and minor — `phase18_5_*`, **not** `phase18.5_*`. Dots in filenames make tab-completion + grep noisy; the underscore convention is locked here.

The doc carries both dispatch framing and the full spec body. Top half: goal, branch + merge, **verification matrix** (a dedicated table with rows for each pre-merge check + columns for "required" / "notes" — replaces the older scattered "Pre-merge gate set" + "Operational notes" treatment), suggested team structure, sequence, load-bearing decisions, operational watch-outs, closeout reporting. Bottom half: status block, locked decisions, what-IS / what-ISN'T, clusters (B / F / D / G / etc.), operational notes, followups.

Code-team session start reads the phase doc first (see the reading order above). The pre-Phase-19 convention of a separate ephemeral chat-only "dispatch prompt" is **deprecated** — don't write a separate dispatch artifact for new passes. Existing pre-Phase-19 specs are not retroactively converted; they continue to ship as-is until each gets retired.

Worked examples to look at when authoring or reviewing a new spec: `phase19_public_delegate_pages_spec.md` and `phase18_5_infrastructure_spec.md`.

## Default team structure

Most passes use four roles:

- **Lead** in delegate mode (Shift+Tab). Coordinates, doesn't implement directly. Writes the closeout report.
- **Backend dev.** Touches `backend/`, writes pytest tests, runs migrations.
- **Frontend dev.** Touches `frontend/`, browser-verifies their own UI changes during dev.
- **QA teammate.** Browser-verifies load-bearing user-facing changes on prod after deploy. Writes verification notes for the closeout. Doesn't write app code.

Variations: very small passes (under ~3 hours of total work) sometimes collapse to lead + one full-stack dev + QA. Large passes occasionally need two backend or two frontend devs. The dispatch will say if the structure differs from the default.

## Branch and merge convention

- One branch per phase: `phase-X-Y/short-name` (e.g., `phase-9-7/invitation-flow`).
- All work commits to that branch during the session.
- At session close: `git merge --no-ff` to master. Never fast-forward merges to master.
- Never force-push master or main. With permissions off, this is enforced by convention only — the absence of a prompt is not permission to do it.
- Push to origin after merge so Railway picks up the deploy.

## Production deploy convention

Railway auto-deploys on push to master. The deploy sequence:

1. Merge phase branch to master with `--no-ff`
2. Push master to origin
3. Wait for Railway to build + redeploy (usually 4-6 minutes for bundle, +1-2 minutes for backend warmup)
4. QA teammate runs prod sanity once both bundle hash has changed AND backend returns non-502 on a known endpoint
5. Lead includes Railway URL, new bundle hash, and prod sanity result in the closeout

Do not mark a pass complete until the prod deploy has been verified. "Merged to master" is not "deployed and working."

**Backend auto-deploy has been unreliable across recent passes (Phase 32 / 32.1 / 32.2 lesson).** Multiple deploys required manual intervention — `railway up`, empty-commit pushes, or manual Redeploy clicks on the Railway dashboard. Frontend service auto-deploys reliably; the backend service does not. Convention: verify deploy success AFTER push by checking BOTH (a) the Railway dashboard / `railway deployment list --service backend` for a deployment row matching the pushed commit AND (b) a backend smoke endpoint returns the expected response — NOT to assume push triggered a successful deploy. If the deploy doesn't appear within ~5 minutes of push, fall back to manual trigger. Manual fallbacks, in order of preference: `railway up --service backend` (uploads current source directly; works even when push-trigger is stuck), empty commit push, or dashboard "Redeploy" button.

## Database migration convention

When a workstream adds an Alembic migration:

- The migration must be reversible (down() implemented)
- Include a subprocess test that runs upgrade → downgrade → upgrade on SQLite to prove reversibility (pattern: `test_phase_X_Y_migration_cycle`)
- Run a PG smoke test before merge: `python backend/scripts/pg_smoke.py --mode both --prior-revision <prior_revision_id>`. The prior revision is the most-recent migration before this pass; check `backend/migrations/versions/` for the chain.
- The pass-specific dispatch will name the prior revision when migrations are expected.

When no migration is added in a pass, the PG smoke is not required. Mention this explicitly in the closeout.

## Testing strategy

**Tests grow with surface added.** Every new endpoint, every new permission gate, every new behavior change gets tests. The PROGRESS.md test count is tracked across phases as a rough health metric, but the principle is: don't ship a workstream with new code paths and unchanged tests.

**Assert side effects, not just API contracts.** This is the lesson from Phase 9.6 (missing email send) and Phase 9.7 (missing user-journey wiring) — both shipped with green test suites because the tests verified the API returned 201 without verifying the side effect (email actually sent, user actually ended up in the right org). When a feature involves anything beyond a database row mutation — emails, OAuth callbacks, webhooks, auto-join behavior, redirect targets — the test must assert the downstream effect, not just the immediate API response. Use mocking to inspect what would have been called if the side effect can't be safely exercised in test.

**Browser verification is required for load-bearing user-facing changes.** Routine surface (e.g., a renamed button, a copy tweak) can ship as PASS-by-source — the lead source-reviews and notes "PASS-by-source" in the closeout. Anything a user actually clicks through (registration flows, vote casting, delegation creation, admin actions) gets browser-verified by the QA teammate on prod after deploy.

**Browser verification uses the Claude in Chrome MCP.** The QA teammate runs scenarios via the `mcp__claude-in-chrome__*` tools — DOM-aware navigation, page-text reads, form input, screenshots. Faster and more precise than computer-use pixel clicks, and the standard QA path for this project. Computer-use is the fallback only for native-desktop interactions outside the browser (not relevant for this codebase's surfaces). If the Chrome extension isn't connected at QA time, the lead flags this in the closeout rather than skipping verification or silently falling back to source review. Specs going forward can reference "QA per CLAUDE.md" rather than restating this convention.

**Use SQLite for unit tests, Postgres for migration smoke.** Unit tests run fast on SQLite; migrations need PG smoke before merge because some bugs only surface on Postgres (the Phase 4c JSON mutation bug is the canonical example).

**Test fixtures must mirror production storage shape.** When you mock or stub a model object, use the same field shapes the production code reads — not a convenient adjacent shape. Phase 17's `_resolve_earliest_decisive_vote` ballot-shape bug is the canonical example: the resolver read `getattr(v, "approvals", None)` directly off Vote rows but production stores ballot data in `v.ballot["approvals"]` JSON dict. Unit tests passed because `SimpleNamespace` shims used the wrong shape; the bug would have silently broken one of four advertised methods in production. When tests use shims, include at least one regression test against real model objects with production storage shape.

**Phase 4c multi-tenancy retrofit is closed (Phase 18, 2026-05-10).** Phase 18 retrofitted `org_id` onto the four relationship tables (`Delegation`, `DelegationIntent`, `FollowRelationship`, `FollowRequest`) that the original Phase 4c migration skipped — closing the gap surfaced in `delegation_org_scoping_diagnostic_2026-05.md`. Any future relationship table added to the schema must carry `org_id` from day one (or document a deliberate exemption with rationale, mirroring how `User`, `Topic`-precedence, and `Vote` handle their multi-tenancy concerns). The "treat any cross-org / org-scoped feature as suspect until verified" check applied during diagnostic should now find no instances; if a future audit surfaces a new instance, treat as a regression.

**Verify schema round-trip when adding new model fields (Phase 32.1 lesson).** When a phase adds nullable override columns or any new field at the model layer, the verification matrix MUST include round-trip checks at (a) the create endpoint(s) — both `/api/proposals` and the org-scoped `/api/orgs/{slug}/proposals` for proposal fields; both ends of any other dual-create path for other models, (b) the response builder / serializer (Pydantic schema present + explicit constructor call in `_build_*_out` if the builder lists fields rather than relying on `from_attributes`), (c) any seed pipeline path that writes to the model directly. Phase 32 + 32.1 needed four hotfixes because the override fields propagated through the schema but not through `create_org_proposal`, the response builder, or the seed pipeline simultaneously. Each of these is an independent place a new field can be silently dropped.

## Bash command style

With permissions off, you can write bash commands in whatever shape works best — compound chains, heredocs, polling loops, all fine. A few style preferences that stay useful for non-permission reasons:

- **Prefer separate commands for distinct logical steps** (verify state → run tests → commit) so a failure in one step doesn't carry forward into the next under a swallowed exit code. Atomicity matters for correctness, not just for permissions.
- **For long polling loops** (waiting on Railway deploys, etc.), prefer a small Python script over an inline bash `until/while` loop. Python is more readable, easier to debug, and easier to amend with timeout handling. See "Polling Railway deploys" below.
- **For multi-paragraph commit messages**, both heredoc (`git commit -m "$(cat <<'EOF' ... EOF)"`) and `-F /tmp/msg.txt` work fine. Pick whichever fits the moment.
- **When in doubt about what a command will do** — especially anything that touches prod, deletes files, or rewrites git history — write what you intend to run into the closeout report BEFORE running it, even if you don't need approval, so Z can flag concerns post-hoc.

## Polling Railway deploys

For the deploy-poll pattern (wait for bundle hash to change + wait for backend to return non-502), use a single-shot Python script instead of a bash loop:

```python
# Inline or in backend/scripts/poll_deploy.py
import re, time, urllib.request

def get_bundle():
    html = urllib.request.urlopen("https://www.liquiddemocracy.us/").read().decode()
    m = re.search(r'index-[A-Za-z0-9_-]+\.js', html)
    return m.group(0) if m else None

# ... full polling logic, return when bundle changes + backend non-502 ...
```

Then `python backend/scripts/poll_deploy.py` is a single bash call that matches `Bash(python *)`. Same outcome, no permission friction.

## Git commit message style

Continue the existing pattern: `Phase X.Y W#: <short summary>` first line, blank, then body explaining what changed and why, with optional `Spec: <spec_filename>` reference at the end. Use whichever delivery mechanism is convenient — heredoc, `-F /tmp/msg.txt`, or stacked `-m` flags.

## Closeout report shape

When the pass is done, the lead reports back to the planning agent (Z's chat) with:

- Per-workstream status: DONE / blocked / scoped-up
- Root cause + specific fix for any diagnostic workstreams
- Backend test count delta (e.g., "491 → 500, +9")
- PG smoke status if a migration was added (or "no migration, smoke not required")
- Browser verification of each load-bearing user-facing change (or PASS-by-source with rationale for routine surface)
- Files added/modified across all workstreams
- Branch state and commit list (commit SHAs)
- Production deploy status: Railway URL, new bundle hash, prod sanity result
- Any new tech debt found
- Backfill script output if a backfill was part of the pass

The planning agent reviews the closeout and decides what (if anything) needs follow-up. Don't ship work and assume it's done — the closeout is the contract.

## Working with Z

Z is the project owner. Non-developer by background but works fluently with the multi-agent workflow. Time is the constraint: anything the team can do without manual Z approval is preferred. The Q&A flow is: planning agent (chat) writes specs and dispatches → Z dispatches the team in Code → team executes and closes out → planning agent reviews. The team doesn't talk to Z directly except through the closeout report and any blocking questions surfaced via the Code interface.

With permissions off, the lead's responsibility for safe operation goes up, not down. The bar shifts from "would Z approve this if asked?" to "would Z be glad I did this without asking?" When the answer might be no, surface the action in the closeout BEFORE running it (or pause and ask via the Code interface for genuinely irreversible operations) — the rules of thumb are: anything touching prod data destructively, anything that rewrites shared git history, anything that costs money beyond normal Railway/Resend usage, anything that changes deploy infrastructure (Railway env vars, DNS, secrets).

## MCP filesystem timeout recovery

The Claude Desktop client has a known bug where it unilaterally cancels MCP tool calls at the 4-minute mark regardless of server state. Empirically observed in this project (2026-05-10): writes around 3-4KB and up can trigger it; the threshold is lower than the GitHub-issue docs suggest and isn't a clean cutoff. Once a timeout fires, the per-conversation MCP connection can wedge for subsequent calls. Sometimes the write succeeded on disk and only the ack was lost; sometimes the write never landed at all. Don't assume either.

Applies to any agent in this project that uses the filesystem MCP (planning agent, content agent, future agents). Not relevant to Claude Code itself, which uses bash, not MCP. Reads of similar size are reliable; the bug is concentrated on writes.

If a `filesystem:*` write returns "No result received from the Claude Desktop app after waiting 4 minutes" or similar:

1. **Do not retry the same call immediately.** Retrying queues another 4-minute wait and often wedges further.
2. **Verify on-disk state.** Wait ~30 seconds, then issue a small read like `filesystem:get_file_info` on the target. Two outcomes:
   - Metadata returns and matches what you intended to write → the write succeeded, only the ack was lost. Proceed.
   - Metadata returns showing the file is missing, empty, or smaller than expected → the write did not land. Switch to the fallback (step 4) rather than retrying.
3. **If the verification read also times out**, the connection is wedged. Stop and surface to Z:
   > "The filesystem MCP connection is wedged. To recover: Task Manager (Ctrl+Shift+Esc) → Processes → find 'Claude' → End task. Then reopen Claude Desktop from the Start menu. Closing the window alone is not enough."
   The wedge is per-conversation, not per-app: other Claude Desktop conversations may keep working fine, but the wedged one needs a full app restart to recover.
4. **Fallback for unreliable writes — route through Google Drive.** For any new-file authoring above ~2KB, or after a wedge has fired, write to Google Drive instead of the local filesystem MCP. The Drive MCP uses a different transport (Google's API) and is not subject to the desktop client's 4-minute cap. Author the file in Drive, then surface it in chat as a downloadable link so Z can pull it into the repo at the appropriate path. This adds one human step at hand-off time but takes the write reliability out of the critical path.
5. **For targeted edits to existing files**, local MCP `edit_file` with small deltas usually works fine — the bug is concentrated on `write_file` and on large new-file creation, especially in freshly-created directories. Keep using local MCP for spec updates, CLAUDE.md edits, and similar surgical changes.
6. **After any recovery, verify on-disk state before continuing.** Don't assume the pre-timeout state matches what you expect.

## Demo daily reset (Phase 23+)

Three demo orgs (`demo-cedar-hollow`, `demo-local-4021`, `demo-westgate-coalition`) get wiped and re-seeded daily from checked-in Python bibles at `backend/demo_content/`.

- **When it runs.** Once daily at the time set by env var `DEMO_RESET_TIME_PACIFIC` (default `"00:00"` midnight Pacific). The reset job is a periodic task inside `digest_scheduler.run_one_tick` — same scheduler that runs Phase 13's digest, Phase 21's halfway-deadline check, and Phase 22's snapshot worker. It short-circuits cheaply when not due.
- **What `is_demo=True` means.** It's the load-bearing safety boundary: the wipe step ONLY touches rows scoped to orgs with this flag. Real orgs are immune regardless of name collision. Never set `is_demo=True` on a real org.
- **Manual trigger.** `POST /api/admin/demo/reset` (platform admin role required) runs an immediate reset. Useful after a bible update or for ad-hoc recovery if a scheduled reset fails.
- **Bible updates.** The bible content is Python code at `backend/demo_content/{hoa_bible.py, union_bible.py, activist_bible_part{1,2,3}.py, trajectory_waypoints.py, schema.py}`. Updating a bible requires a code change + redeploy; the next scheduled (or manual) reset picks up the new content. See `docs/demo_content_integration.md` for the bible → DB pipeline.
- **Reset preserves real user accounts.** The `users` table is never touched. Real users who joined a demo org have their `OrgMembership` row wiped (they can rejoin freely after reset). The frontend banner discloses this on every demo-org page.
- **Don't add reset-coordination logic for multi-instance scaling.** Current design assumes single-instance scheduler. Multi-instance race-condition handling is future work if needed; the `is_demo_resetting` lock + the audit log are sufficient at current scale.
- **Cross-org users.** Marcus Pham, Dana Whitfield, and Janet Reilly each have ONE underlying `User` row with TWO `OrgMembership` rows. The seed pipeline resolves bible-internal IDs (`hoa_marcus`, `coalition_marcus`, etc.) to single User accounts at seed time. Stage 8 §5 documents the mapping; if you add a fourth cross-org character, extend the resolver in `seed_pipeline.py`.

## Demo reset trigger (Phase 23.2+)

`POST /api/demo/trigger-reset` is a token-gated alternative to the admin-auth `/api/admin/demo/reset` endpoint. Code-team sessions hold the token (env var `DEMO_RESET_TRIGGER_TOKEN`, set in both Railway prod env and local `.env`) so resets can be triggered during demo-content iteration without admin credentials. Invoke via `python scripts/trigger_demo_reset.py` — the script reads the token from `.env`, POSTs the header, and prints the `DemoResetResult` JSON (orgs reset, rows wiped/seeded, skip reason). Same code path as the scheduled reset and the admin trigger; the `is_demo=True` safety boundary is not bypassed.

## Frontend conventions

### Topic display name

Read `topic.name` directly. The field is the canonical display name and is uniquely scoped per-org via `UniqueConstraint("org_id", "name")` (Phase 30.1 B5 migration `a8c2d51e9f10`). The legacy `topic.description` field is preserved for back-compat but should not be read in new code — the Phase 23.1-introduced description-fallback workaround (re-applied across Phases 25 / 26 / 28 / 30) was patching around the old global-unique `Topic.name` constraint, which the Phase 30.1 root-cause fix removed. Demo orgs no longer prefix names with `{slug}:`; the seed pipeline writes plain names directly.

### Tailwind arbitrary-value syntax

When using Tailwind arbitrary values with multiple CSS values (commonly grid templates), separate values with **underscores**, not commas:

```
✅ grid-cols-[1fr_88px_88px_88px_88px]
❌ grid-cols-[1fr,88px,88px,88px,88px]
```

The comma form silently produces an invalid Tailwind class name; the framework generates no CSS for it and the layout falls back to default behavior (single-column auto for grid-cols, etc.). The bug is silent — `npm run build` passes without warning — and only surfaces visually. Phase 13.3 shipped with this exact bug; Phase 13.4 was a 3-minute single-line CSS fix once it was caught.

The rule applies to any Tailwind arbitrary value carrying a multi-value CSS property: grid templates, transforms with multiple operations, multi-value transitions, etc. Same separator (`_`) in all cases.
