# Phase 5 Dispatch Prompt

Copy the text below into the Claude Code team lead to start Phase 5.

---

You are coordinating Phase 5 of the Liquid Democracy Platform. This is a cleanup pass — no new features, four specific fixes. Full spec is at `phase5_spec.md` in the project root. Read it first.

**Summary:**

1. Fix the admin route guard so moderators can't access admin-only pages via direct URL.
2. Fix the admin Members page so moderators see the actual member list (bug is in the frontend fetch coupling, not backend query).
3. Disable vote and delegate controls for unverified users instead of letting them click through to backend 403s.
4. Replace every `alert()` and `window.confirm()` in the frontend with in-DOM Toast and ConfirmDialog components. This is the biggest piece of work in the pass.

Read `phase5_spec.md` for scope, acceptance criteria, non-goals, and the exact file locations already diagnosed for each fix. Also read `PROGRESS.md` for current project state and `browser_testing_playbook.md` (particularly Suite H) for the testing patterns used in Phase 4 Cleanup — Phase 5 adds Suite I in the same format.

**Operational notes:**

- Scope is narrow. Do not expand into URL routing, full permission-keying, notification systems, or accessibility beyond what's in the spec. If you find adjacent issues, log them as new entries in `PROGRESS.md` technical debt rather than fixing inline.
- The Toast and ConfirmDialog components must be in-DOM (React components) — do not leave any native `alert()` / `confirm()` / `prompt()` calls in the application code. The grep acceptance criteria in the spec are explicit; run them yourself before reporting completion.
- Backend tests: `cd backend && python -m pytest tests/ -v` must still show all 96+ tests passing. No regressions.
- Browser tests: Suite I must be executed end-to-end and results committed into `browser_testing_playbook.md`. Do not skip this step — skipping test documentation was called out as a regression risk in the Phase 4 Cleanup retrospective.
- Update `PROGRESS.md` at the end with a Phase 5 section documenting what was done, and move the three now-resolved items out of technical debt.

**Suggested team structure:**

- Lead (you) in delegate mode.
- Dev teammate #1: Fixes 1, 2, 3 (the three permission-alignment fixes). These are small and share context — one dev in one session makes sense.
- Dev teammate #2: Fix 4 (dialog replacement). Larger and independent. Starts in parallel with #1.
- QA teammate: Waits for both devs to report fix complete, then runs Suite I and commits results.

If you prefer a different structure, use your judgment — the fixes have no hard dependencies between them except that QA tests the combined result.

Report completion with a short summary listing: which fixes shipped, backend test count, Suite I results, and any new technical debt items discovered. No need to be verbose — the planning agent will read `PROGRESS.md` for details.
