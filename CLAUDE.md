# CLAUDE.md — Team Operating Conventions

This file is loaded automatically by Claude Code at session start. Keep it under 200 lines. Project context lives in PROGRESS.md and the active spec; this file is for working-style conventions only. When a dispatch says something different from this file, the dispatch wins for that pass.

## Operating mode

This project runs Claude Code with `--dangerously-skip-permissions` enabled. There is no permission prompting; every bash command runs immediately. The safety net is git history + Railway rollback + the conventions in this file (one branch per phase, no-ff merges to master, no force-pushes, never `alembic downgrade base` in production, never destructive SQL against prod). Operate with appropriate care; treat the absence of prompts as trust to be earned, not as license. If you're about to run something genuinely irreversible (force-push, hard reset, schema drop), pause and surface it to the closeout for explicit Z review BEFORE running it.

## Reading order at session start

1. `PROGRESS.md` — canonical session passdown, what's shipped through the most recent phase
2. The active spec for the phase you're working on (e.g., `phase9_7_invitation_flow_spec.md`)
3. `TECHNICAL_SUMMARY.md` — architecture overview if you need orientation
4. `future_improvements_roadmap.md` — forward-looking scope; reference but don't assume anything in it is being built unless a spec says so

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

**Use SQLite for unit tests, Postgres for migration smoke.** Unit tests run fast on SQLite; migrations need PG smoke before merge because some bugs only surface on Postgres (the Phase 4c JSON mutation bug is the canonical example).

**Test fixtures must mirror production storage shape.** When you mock or stub a model object, use the same field shapes the production code reads — not a convenient adjacent shape. Phase 17's `_resolve_earliest_decisive_vote` ballot-shape bug is the canonical example: the resolver read `getattr(v, "approvals", None)` directly off Vote rows but production stores ballot data in `v.ballot["approvals"]` JSON dict. Unit tests passed because `SimpleNamespace` shims used the wrong shape; the bug would have silently broken one of four advertised methods in production. When tests use shims, include at least one regression test against real model objects with production storage shape.

**Phase 4c multi-tenancy retrofit is closed (Phase 18, 2026-05-10).** Phase 18 retrofitted `org_id` onto the four relationship tables (`Delegation`, `DelegationIntent`, `FollowRelationship`, `FollowRequest`) that the original Phase 4c migration skipped — closing the gap surfaced in `delegation_org_scoping_diagnostic_2026-05.md`. Any future relationship table added to the schema must carry `org_id` from day one (or document a deliberate exemption with rationale, mirroring how `User`, `Topic`-precedence, and `Vote` handle their multi-tenancy concerns). The "treat any cross-org / org-scoped feature as suspect until verified" check applied during diagnostic should now find no instances; if a future audit surfaces a new instance, treat as a regression.

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

## Frontend conventions

### Tailwind arbitrary-value syntax

When using Tailwind arbitrary values with multiple CSS values (commonly grid templates), separate values with **underscores**, not commas:

```
✅ grid-cols-[1fr_88px_88px_88px_88px]
❌ grid-cols-[1fr,88px,88px,88px,88px]
```

The comma form silently produces an invalid Tailwind class name; the framework generates no CSS for it and the layout falls back to default behavior (single-column auto for grid-cols, etc.). The bug is silent — `npm run build` passes without warning — and only surfaces visually. Phase 13.3 shipped with this exact bug; Phase 13.4 was a 3-minute single-line CSS fix once it was caught.

The rule applies to any Tailwind arbitrary value carrying a multi-value CSS property: grid templates, transforms with multiple operations, multi-value transitions, etc. Same separator (`_`) in all cases.
