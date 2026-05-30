# Phase 43b — Vote-Copy Hotfix

**Status:** Ready to ship. Trivial copy hotfix to the member getting-started help page. The edit is **already applied to the working tree** by the planning agent (frontend source + content artifact); this pass just builds, commits, deploys, and verifies. Merged dispatch + spec doc.

**Branch:** `phase-43b/vote-copy-hotfix` → `--no-ff` merge to master at close.

---

## Why

Phase 43a's closeout flagged a screenshot↔copy mismatch on `/help/getting-started-member`: the "Cast your vote" copy and the vote-cast screenshot caption described the vote controls as **"Approve / Reject / Abstain"** with a separate **"Submit Vote"** button. Per the 43a team's prod verification (Chrome MCP), the real UI uses **Yes / No / Abstain**, records the vote on selection (no separate submit button); changing a vote is done by selecting a different option. The Phase 43a screenshot is accurate to the live UI — only the prose and that one caption were wrong. (Source: 43a closeout. The planning agent's own live re-verification this session was blocked by the demo persona session not persisting — relied on the team's prod-verified finding, which is trustworthy. **As the first QA step, confirm the live vocabulary against the captured `member-vote-cast.png` screenshot before merging** — that image already shows the real controls.)

## What changed (already applied to working tree)

`frontend/src/pages/GettingStartedMember.jsx`, "Cast your vote" section:
- Vote options "Approve / Reject / Abstain" → "Yes / No / Abstain".
- "Pick your choice and select **Submit Vote**." → "Your choice is recorded immediately; there's no separate submit step."
- "you can select **Change Vote** and update it." → "you can change your vote any time — just select a different option."
- `HelpScreenshot` caption → "A single proposal detail in the Voting stage showing the Yes / No / Abstain vote options."

`phase43_help_content.md` (source-of-truth artifact) — same three edits, kept in sync.

No image change (the screenshot already matches live). No other page touched. No backend, no migration.

## What the team does

1. Confirm the pre-applied working-tree edits to `GettingStartedMember.jsx` (and the `phase43_help_content.md` sync) are present and correct.
2. `npm run build` — must pass clean.
3. Commit to `phase-43b/vote-copy-hotfix`, `--no-ff` merge to master, push, let Railway deploy.
4. Confirm bundle hash flip + backend non-502.
5. Prod QA: load `/help/getting-started-member`, confirm the "Cast your vote" copy now reads Yes/No/Abstain with no "Submit Vote" reference, and the screenshot + caption + prose all agree.

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Frontend build | Yes | Clean. |
| Backend pytest | No | Untouched; note baseline unchanged. |
| PG smoke | No | No migration. |
| Browser verification (prod) | Yes | The coherence check above. |
| Bundle hash changed | Yes | Confirm in closeout. |

## Closeout

Per CLAUDE.md shape, abbreviated: confirm copy fix live, bundle hash, prod QA result. Note backend untouched / no migration.

## Followup

This was the one screenshot↔copy mismatch found. The other four Phase 43a screenshots (proposals list, browse delegates, admin menu, delegate page) were verified coherent by the planning agent. If a future help-copy change touches vote mechanics, remember the live vocabulary is **Yes / No / Abstain, recorded-on-select, no submit button**.
