# Phase 83 — Pre-Recruitment Readiness Findings

**Date:** 2026-07-02
**Type:** Findings-only recon. No code changed, no data touched. Every finding is grounded in a file/symbol or the route's observed control flow. Remediation directions are one-liners only — no fixes designed.

**Method note / caveat:** This pass is code-grounded. The Chrome extension was **not available this session**, so the browser-verification items the dispatch requested (empty-state rendering, mobile ~380px, zero-node D3 charts, live error-copy on prod) were **not executed**. Where a claim requires rendering evidence it is marked `NEEDS-BROWSER-QA` rather than asserted. All Part B findings and the A3 copy-vs-reality findings are fully code-grounded.

**Severity key:** blocker = will visibly embarrass or harm in week one of real strangers · high = exploitable/abusable with trivial effort · medium = degrades trust/experience · low = polish.

---

## Summary table

| ID | Sev | Area | One-line |
|----|-----|------|----------|
| A-1 | **blocker** | Copy vs reality | Consent disclosure says "we do not keep a copy of your documents or selfie" while the Didit session purge is broken |
| A-2 | low | Copy | Security/Privacy retention copy is broadly honest; one nuance to align |
| A-3 | ✅ pass | Pilot copy | Phase 78 contact placeholder is resolved (real mailto) |
| A-4 | NEEDS-BROWSER-QA | First-10-min UX | Empty states exist in source; rendering/mobile/charts not verified this session |
| B-1 | **high** | Moderation | `comment.moderate` registered but enforced nowhere — stewards cannot remove abusive comments |
| B-2 | low | Registry hygiene | `proposal.delete` / `proposal.resolve_tie` are vestigial (self-documented, not misleading) |
| B-3 | medium | Permissions | Tier-vs-matrix divergence remains for a few keys (mostly closed by Phase 71) |
| B-4 | **high** | Moderation | No member-facing report/flag mechanism anywhere |
| B-5 | **high** | Moderation | No moderation/redaction path for any free-text UGC (display name, bio, rationale, org name, DM body) |
| B-6 | medium | Moderation | Admin can archive a mid-vote abusive proposal, but title/body persist visibly in the archive; no redaction |
| B-7 | **high** | Abuse | No rate limiting on content-creation endpoints (comments, proposals, votes, follows, joins) |
| B-8 | **high** | Abuse | Removed member instantly rejoins an open-join org — no ban/blocklist |
| B-9 | **high** | Abuse | Throwaway-email account farming — email verification is the only barrier; 3-org cap is per-account |
| B-10 | medium | Abuse | No platform-admin org takedown; offensive public org name/logo lands on `/explore` with zero review |
| B-11 | medium | Abuse | Open-org Sybil exposure — one throwaway = one vote at The Reform Table's configured floor |
| B-12 | ✅ pass | Demo | Phase 79 demo fence holds at the backend against direct API calls |
| B-13 | ✅ pass | DM abuse | DM surface is reasonably fenced (follow-only default, per-user/org rate limit, block, opt-out) |
| B-14 | medium | Uploads | Upload validation is technically solid but there is no content review or takedown of avatars/logos |

---

## Part A — First-Contact Experience

### A-1 — Consent disclosure claims documents aren't kept while the vendor purge is broken — **BLOCKER**

**Files:** `backend/routes/verification.py:56` (`CONSENT_DISCLOSURE`), `:636` (`_purge_session_best_effort`), `:770-807` (webhook purge wrapper), `:648-650` (`delete_session` call). Rendered to users via `frontend/src/pages/Settings.jsx` (disclosure shown verbatim before the Didit redirect).

**Evidence:** The consent text shown to every user before ID verification reads:

> "We send your ID to our identity-verification partner to confirm who you are. **We do not keep a copy of your documents or selfie — only a record that the check happened and the result.** You can cancel the verification at any time before completing it."

The mechanism meant to guarantee the documents don't linger at the vendor is `_purge_session_best_effort` → `verification_provider.delete_session(session_id)`, called after webhook extraction. Per the dispatch and prior confirmation, that DELETE returns **404** — the purge silently fails (`_purge_session_best_effort` is explicitly "fail-toward-keeping-the-verification"; a failed purge only writes a bookkeeping-row status, never retries). Net effect: the platform does not store the image itself (the copy is literally accurate for *our* DB), **but** the document/selfie is *not* being removed from the vendor session as the design intended, so the images persist vendor-side beyond what the disclosure implies.

**Why blocker:** This is exactly the retention/deletion-claim landmine the dispatch flagged. A skeptical stranger asked to upload a government ID is the highest-trust moment on the platform; a copy claim the system can't fully back is a publish-blocker if a privacy-savvy user (or a journalist) probes it.

**Remediation direction:** Either fix the vendor purge (separate, vendor-blocked track) OR soften the copy to describe vendor-side retention honestly ("our partner processes and retains your ID per their policy; we store only the result") before outreach. Copy change is the fast unblocker.

### A-2 — Retention copy elsewhere is honest; one nuance to align — low

**Files:** `frontend/src/pages/Security.jsx:46-47,60-62`, `frontend/src/pages/Privacy.jsx:46-47`.

**Evidence:** Security/Privacy say data is retained while the account is active, audit logs indefinitely, and that account-deletion requests go "by contacting your organization administrator" with anonymized vote records possibly retained. These are consistent with the code (append-only audit log; no self-serve account delete route found). The only nuance: "contacting your organization administrator" implies an org admin can delete a user account — but account deletion is not an org-admin capability in the routes (no such endpoint surfaced). Low: copy points users at a path that isn't self-service.

**Remediation direction:** Align the account-deletion copy with the actual (manual/support) process, or add the endpoint later.

### A-3 — Pilot explainer contact placeholder is RESOLVED — ✅ pass

**File:** `frontend/src/pages/Landing.jsx:164-187`. The Phase 78 "What 'pilot stage' means" section now links a real `mailto:z@liquiddemocracy.us` ("Reach out"). No placeholder renders. No finding.

### A-4 — First-10-minute UX not browser-verified this session — NEEDS-BROWSER-QA

**Evidence (source-level only):** Empty-state copy is present in source across the member-facing list pages (`Proposals.jsx`, `Delegates.jsx`, `Messages.jsx`, `NotificationsPage.jsx`, `DelegatePublic.jsx`, admin `Members.jsx`/`Topics.jsx`, etc. — 23 files carry empty/"get started" strings), so blank panels are unlikely at the copy layer. User-facing "Phase …" leakage was checked: `Phase` appears only in code comments, not in rendered JSX text — no leakage.

**Not verified (Chrome unavailable):** actual empty-state rendering for a zero-history member in a content-rich org; zero-node D3 charts (vote network / delegation tree / trajectory) rendering sanely with no data; mobile ~380px on landing/explore/org-landing/registration/proposal-detail and the drag-to-rank RCV ballot on touch; live friendly-error copy for bad login / expired token / double-join / double-vote.

**Remediation direction:** Run a dedicated browser-QA pass (own follow-up) on the critical path before outreach; this recon could not stand in for it.

---

## Part B — Abuse Surface & Steward Response Tooling

### B-1 — `comment.moderate` registered but enforced nowhere — **HIGH** (confirms + expands seed finding)

**Files:** `backend/permission_registry.py:226-231` (key + description promising "Allow soft-deleting comments posted by other members"), `backend/routes/comments.py:434-446` (`delete_comment` — strictly `comment.author_id == current_user.id`).

**Evidence:** `DELETE /api/comments/{id}` returns 403 "You can only delete your own comments" for anyone who isn't the author. Grep for `comment.moderate` across all non-test backend code returns **zero enforcement sites** — the only references are the registry entry, `DEFAULT_GRANTS` (seeded TRUE to steward/admin/moderator), the Phase-12 migration, and tests. A steward staring at an abusive comment on The Reform Table has **no button and no endpoint** to remove it. The registry description actively advertises a capability that does not exist.

**Sweep result (other registered-but-unenforced keys):**
- `proposal.delete` — vestigial (see B-2), self-documented as no-effect.
- `proposal.resolve_tie` — vestigial (see B-2), self-documented as automated.
- All other 26 keys have at least one live enforcement site (verified: `delegate_application.approve`, `org_inbox.view`, `title.manage`, `member.suspend`, `analytics.view`, `sub_org.*`, `polis.*`, `proposal.*`, `member.*` via matrix or tier-floor). `comment.moderate` is the **only** key that promises a capability and delivers nothing.

**Remediation direction:** Wire `comment.moderate` into `delete_comment` (moderator soft-delete of others' comments, distinct audit action). This single fix also unblocks the most common day-one abuse response.

### B-2 — `proposal.delete` / `proposal.resolve_tie` are vestigial — low (not misleading)

**Files:** `backend/permission_registry.py:74-100`. Both descriptions were rewritten in Phase 71c to be honest ("Currently has no effect…" / "Automated — no manual action…"). They gate nothing but no longer mislead. Note only — a future pass could deregister them (needs a backfill migration; out of scope here).

### B-3 — Tier-vs-matrix divergence remains for a few keys — medium (mostly closed by Phase 71)

**Files:** `backend/routes/organizations.py:1344` (`change_member_role` gated by `require_org_admin`, not by a `has_permission("member.change_role")` check). `member.change_role` is a Steward-locked key (`role_permissions.py:79`) enforced by role tier, so the matrix cell for lower roles is advisory only.

**Evidence:** This is the Phase 69 audit's known class (see memory: "~12 of 29 keys gated by role tier not the matrix"). Phase 71a/b/c converted the high-value routes to config-authoritative. The residual keys enforced purely by tier are consistent with their locked/steward-only nature. **Not a new regression;** flagged so the outreach owner knows the role matrix is not 100% authoritative and shouldn't be advertised as fully granular.

**Remediation direction:** None required for launch; leave as documented Phase 69/71 state.

### B-4 — No member-facing report/flag mechanism — **HIGH**

**Evidence:** No `report`/`flag-abuse` route exists for members. Grep of `backend/routes/` for report/abuse/moderation surfaces only: `duplicate_flags.py` (Sybil duplicate-detection, admin-facing), and incidental "report" strings in `organizations.py`/`delegations.py`/`comments.py` unrelated to abuse reporting. A member who sees an abusive comment, bio, or display name has **no in-product way to escalate** — their only recourse is finding a steward out-of-band.

**Why high:** For open-join outreach targets (The Reform Table), the crowd is the first line of moderation everywhere else on the internet; here they have nothing. Combined with B-1 (stewards can't act on comments either), abuse response on day one is effectively absent.

**Remediation direction:** Add a lightweight `POST report` on comments/proposals/users that writes to the audit log / a steward-visible queue.

### B-5 — No moderation/redaction path for free-text UGC — **HIGH**

**Surfaces enumerated (each is user-controlled free text with no admin redaction path):**
- **Display name** — `User.display_name`, self-edited; shown on comments, votes, delegate lists, DMs. No admin override/redaction; only `member.remove` (wholesale, reversible — see B-8).
- **Delegate profile bio** — `routes/delegate_profiles.py`, self-edited, publicly rendered on delegate pages.
- **Vote rationale** — `DelegateVoteRationale`, author-written, visible per `can_view_vote_rationale`.
- **Org name / description** — `Organization.name`/`description`, steward-edited, publicly listed on `/explore`.
- **DM body** — Phase 77 `Message.body`, no moderation (only recipient block / rate limit).

**Evidence:** The only steward levers against any of these are `member.remove` (ends membership, does not scrub content) and — for comments — nothing (B-1). No endpoint hides/redacts a slur in a display name, bio, or rationale.

**Remediation direction:** Add an admin "hide/redact UGC field" capability (or reuse a moderation flag) covering display name, bio, rationale, and DM body.

### B-6 — Mid-vote abusive proposal: archivable but not redactable — medium

**Files:** `backend/routes/proposals.py:2031,2075,2105` (`archive` gated by `proposal.archive`, works at any phase per `permission_registry.py:130-134`). Draft-only hard delete at `:1978-1989` (author/`org.edit_proposal`/admin).

**Evidence:** An admin **can** archive a slur-titled proposal mid-vote (archive is phase-agnostic, preserves votes). But archiving only moves it out of the active list into the "Archived" filter — the offending title/body **still renders** to anyone browsing archived proposals. Editing another member's proposal during the voting phase is subject to the org edit-lockout (`org.edit_proposal`), so an admin may not be able to sanitize the title in place. Net: the slur is hidden from the default list but not removed/redacted.

**Remediation direction:** Let archive optionally redact title/body, or allow admin title-edit on archive regardless of lockout.

### B-7 — No rate limiting on content-creation endpoints — **HIGH**

**Files:** `backend/rate_limit_utils.py` + the four decorated modules only: `routes/auth.py` (register/login/reset), `routes/verification.py:95`, `routes/invitations.py:57`, `routes/demo_reset.py:46`; plus DM's own DB-count limiter (`routes/messages.py:285`, 20/hr/user/org).

**Unlimited (no limiter decorator, no DB-count guard):**
- `POST /api/proposals/{id}/comments` (`routes/comments.py:202`)
- proposal creation (`routes/organizations.py:4408/4542`, `routes/proposals.py`)
- vote casting (`routes/votes.py`)
- follow requests (`routes/follows.py`)
- join requests (`routes/organizations.py:2668`)

**Evidence:** A single email-verified throwaway account can POST comments in an unbounded loop; nothing throttles it. Email verification (the one gate) is trivially cleared with any disposable inbox.

**Why high:** Comment flooding on a live proposal is the single easiest way for a bored troll to wreck the outreach org's first week, and there is no server-side brake.

**Remediation direction:** Add per-user + per-IP rate limits to comment/proposal/follow/join creation (reuse the slowapi `bypass_or_remote_address` key_func or the messages DB-count pattern).

### B-8 — Removed member instantly rejoins an open-join org — **HIGH**

**Files:** `backend/routes/organizations.py:1422` (`remove_member` → `execute_member_remove` **deletes** the `OrgMembership` row; verified by `test_phase_71b_config_sweep.py` asserting `.first() is None` post-removal), `:2668` (`request_join` blocks only when an `OrgMembership` row already exists; no ban/blocklist consulted).

**Evidence:** For an `open` join_policy org, removal deletes the membership row and `request_join` re-creates an `active` row immediately on the next call — there is no per-org ban list. Removal is **toothless** for exactly the open orgs being recruited. Suspend (`member.suspend`) keeps them a (non-voting) member but is also reversible and doesn't stop re-join churn.

**Remediation direction:** Add a per-org ban/blocklist (or "removed, cannot rejoin" flag) checked in `request_join`.

### B-9 — Throwaway-email account farming — **HIGH**

**Files:** `backend/routes/auth.py` (registration; email verification is the sole identity barrier), `routes/organizations.py:335,349` (org-create requires verified email + blocks demo_stub; 3-org cap enforced per-account at `:360-381`).

**Evidence:** Nothing limits one person to one account — email verification passes with any disposable inbox, and there is no disposable-domain blocklist or signup-velocity control found. The 3-org cap is **per account**, so N throwaways = 3N orgs. This is the multiplier under B-8, B-10, and B-11.

**Remediation direction:** Consider a disposable-domain blocklist and/or per-IP signup velocity limits before wide (Reddit-scale) outreach.

### B-10 — No platform-admin org takedown; offensive public org lands on `/explore` unreviewed — medium

**Files:** `backend/routes/organizations.py:1148` (`DELETE /{org_slug}` is gated by the org's own steward/admin governance — **not** a platform-admin takedown), `:1908-2043` (`/explore` lists any `is_demo=False`, non-hidden, top-level org immediately), org-logo upload `routes/org_logos.py` (type/size validated, no content review). `backend/routes/admin.py` platform-admin endpoints are: promote-to-admin, verification backdoor, and governance rebootstrap — **no org delete/suspend/hide**.

**Evidence:** A throwaway account creates a public org with an offensive name + logo; it appears on `/explore` with zero pre-review, and a **platform admin has no endpoint to take it down** (they'd have to get seated as steward via the governor-less rebootstrap backstop, which doesn't apply to a live abusive org). The only deletion path is in-org governance the abuser controls.

**Remediation direction:** Add a platform-admin org hide/takedown endpoint (and ideally logo takedown), gated on `User.is_admin`.

### B-11 — Open-org Sybil exposure at the configured verification floor — medium

**Files:** `backend/routes/organizations.py:2668` (join floor = `check_membership_floor_for_join`, no-op when the org sets no floor), `routes/votes.py` (one active member = one vote). Write-ins, cosign petitions (`cosign.py`), and pre-voting are all reachable by any active verified member.

**Evidence:** With The Reform Table's join/verification floor as configured (default: no residency/identity floor), one throwaway verified account = one full vote, plus write-in/cosign/pre-vote participation. B-9 makes minting those accounts free.

**Remediation direction:** Recommend setting a minimum verification floor (e.g., identity or residency) on the recruited org before outreach — a config choice, not a code fix.

### B-12 — Demo fence holds against direct API — ✅ pass

**Files:** `backend/verification.py:493` (`ensure_can_join_real_org` → 422 for `demo_stub` joining any non-demo org), called in `request_join` at `organizations.py:2722`; `organizations.py:349` blocks `demo_stub`/`backdoor` from creating orgs. The Phase 79 frontend auto-logout is UX; the security boundary is backend-enforced and safe against direct API calls. No finding.

### B-13 — DM surface reasonably fenced — ✅ pass

**Files:** `backend/routes/messages.py:612` (default `member_dm_policy="follow_only"` — a fresh member can only DM someone in a follow relationship), `:285` (20 messages/hr/user/org DB-count limit), `:121-125`/`:817` (`MessageBlock` recipient block), `User.dm_disabled` opt-out (`:620`). Mass-DMing a whole membership is not possible without first following each recipient. No finding; note that "open" policy (if an org selects it) would remove the follow gate — worth a doc note to stewards.

### B-14 — Upload validation solid; no content review/takedown — medium

**Files:** `backend/routes/avatars.py:115-225` (content-type whitelist jpeg/png/webp, 6 MB byte cap, 25 MP decompression-bomb guard, Pillow re-encode), `routes/org_logos.py` (same shape). **Evidence:** technically hardened, but an offensive *image* passes every check and is served publicly with no review; the only removal is the uploader deleting their own (no admin takedown of a member avatar or an org logo). Overlaps B-10 for logos.

**Remediation direction:** Fold avatar/logo takedown into the B-5/B-10 admin-moderation capability.

---

## Proposed remediation groupings (grouping only — no specs)

**Group 1 — Steward moderation toolkit (highest launch value).** B-1 (enforce `comment.moderate`), B-4 (member report/flag), B-5 (UGC redaction/hide for display name / bio / rationale / DM), B-6 (redact-on-archive), B-14 (avatar/logo takedown). This is the "what can a steward actually do about a troll" gap and should ship before outreach.

**Group 2 — Anti-abuse rate/identity controls.** B-7 (rate-limit content endpoints), B-8 (per-org ban/blocklist so removal sticks), B-9 (disposable-domain + signup-velocity controls). The "one bored troll with a throwaway inbox" surface.

**Group 3 — Platform-admin & public-listing safety.** B-10 (platform-admin org/logo takedown), plus the config guidance in B-11 (recommend a verification floor on recruited orgs — no code).

**Group 4 — Copy & pre-publish honesty (fast, do first).** A-1 (align consent-disclosure copy with the broken purge — copy change unblocks now), A-2 (account-deletion copy). Plus the standalone **A-4 browser-QA pass** (empty states / mobile / RCV-touch / error copy) as its own dedicated verification task since this recon could not perform it.

**Reference:** Phase 69 permission audit + Phase 71 config-authoritative remediation already cover B-3; do not re-open. Phase 63 security review is not duplicated here.
