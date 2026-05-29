# Phase 42 Cold-Start Test Dispatch — DO NOT EXECUTE

This is a low-risk read-only target for the Phase 42 cold-start viability test. A fresh `claude -p` session will be pointed at this file. It is NOT a real spec; do not implement anything.

**Task for the cold-start test session (read-only):**

Read this file, `CLAUDE.md` (project conventions), and `PROGRESS.md`. Then produce a SHORT report (≤300 words) covering:

1. What does this project do, in one sentence?
2. What's the most recent shipped phase (per memory or recent commits)?
3. Per CLAUDE.md, what's the branch naming convention for a hypothetical Phase 99?
4. Per CLAUDE.md, what's required before merging a pass that adds an alembic migration?
5. Are there any open audit items the docs say are "Tier-1" — and if so, which file lists them?

Do NOT modify any files. Do NOT create a branch. Do NOT commit anything. This is purely a "can the fresh session orient from the docs and answer convention-following questions?" probe.
