# Phase 84 — Verification Consent Copy Correction (A-1 blocker from Phase 83)

**Type:** Copy-only fix. No schema, no migration, no behavior change. Single deploy.

**Problem (Phase 83 finding A-1, severity: blocker):** The ID-verification consent disclosure (`routes/verification.py:56` and any frontend component rendering equivalent copy) states "We do not keep a copy of your documents or selfie." This is true of our database but false in effect: the Didit session purge (`_purge_session_best_effort` → `delete_session`) is broken (DELETE returns 404), so documents persist on the vendor side indefinitely. A user reading the current copy would reasonably conclude their documents cease to exist after verification. They don't.

**Fix:** Reword the disclosure to be strictly accurate without waiting on the vendor fix. Required properties of the new copy:

1. Accurately states what WE store: derived verification state and privacy-preserving hashes only; no document images, selfies, or raw document numbers in our systems.
2. Accurately attributes vendor processing: identity documents are processed and retained by our verification provider (Didit) under its own privacy policy — link to Didit's privacy policy.
3. Makes no deletion/purge promise anywhere (grep for it) until the purge is verified working end-to-end (confirmed session disappearance in the Didit portal — this is a known open item with Didit CS).
4. No em dashes in the copy (platform copy voice rule).

**Scope of the sweep:** Find EVERY surface making a retention/deletion claim about verification data, not just verification.py:56 — the consent modal/component in the frontend, the Privacy page, the Security page, help pages, and email templates. Phase 83 Part A3 inventoried some; re-grep to be exhaustive (search terms: "do not keep", "not stored", "deleted", "purge", "retain", "selfie", "document" across frontend copy, help pages, legal pages, and backend-served strings). Every instance either updated to the accurate framing or removed.

**Verification:**
- Grep proof in the closeout: zero remaining instances of non-retention/deletion claims about vendor-side verification data.
- Browser check of the consent flow rendering the new copy (if the Chrome extension is unavailable, screenshot via local dev render and say so explicitly).
- No test-count change expected; existing tests must stay green.

**Explicitly out of scope:** Fixing the purge itself (blocked on Didit CS / Mara). When the purge is confirmed working, a future micro-phase MAY strengthen the copy again — that phase must include observed evidence of a session disappearing from the Didit portal before any deletion claim ships.

**Also in this pass (housekeeping, zero-risk):** Commit `phase83_readiness_findings_2026-07-02.md` to the repo (main is fine; it's a findings doc, not code).
