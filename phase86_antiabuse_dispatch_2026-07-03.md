# Phase 86 — Anti-Abuse Pass: Report Queue + Content Rate Limits + Throwaway Friction

**Source:** Phase 83 findings B-4, B-7, B-9 (Group 2). Read `phase83_readiness_findings_2026-07-02.md` first.

**Type:** Build pass. One migration (new table only). Single deploy. Does NOT touch `start.sh` or deploy-time codepaths.

**Design decisions (locked by Z — do not relitigate):**
1. Reports are SIGNAL ONLY. No auto-hide, no auto-anything at any report count, ever, in this pass. All consequences flow through the existing moderation tools (Phase 85). Threshold automation is explicitly rejected as a brigading vector.
2. Reportable surfaces in v1: comments and proposals only.
3. No new permission key. The report queue is gated on `comment.moderate` (via `role_permissions.has_permission`), which Phase 85 made real. This deliberately avoids the new-key seed/backfill trap for existing orgs.

---

## Cluster 1 — Member report/flag mechanism (B-4)

**Model:** New table `content_reports`: `id`, `org_id` FK, `reporter_id` FK, `target_type` (`comment` | `proposal`), `target_id`, `reason` (enum: `spam` | `harassment` | `misleading` | `other`), `note` (nullable text, short cap ~500 chars, sanitized like all UGC), `status` (`open` | `dismissed` | `actioned`), `created_at`, `resolved_by_id` (nullable FK), `resolved_at` (nullable). Partial-unique: one OPEN report per (reporter_id, target_type, target_id) — re-reporting the same content while a report is open is a no-op 200, not an error.

**Submitting:** `POST /api/reports` — org member, verified email required. Resolve and store `org_id` server-side from the target (never trust client org_id). Validate target exists, is in an org the reporter belongs to, and is not already deleted/removed. Reporting your own content → 400.

**Queue:** `GET /api/orgs/{slug}/reports?status=open` — gated on `comment.moderate` (sub-org-scoped targets resolve through `has_permission_on_sub_org`, same pattern as Phase 85). Returns report rows grouped by target with per-target open-report count, reasons, notes, and enough context to act (target excerpt, author, link). Resolve endpoint: `PATCH /api/reports/{id}` → `dismissed` or `actioned`, sets resolver + timestamp. "Actioned" is a bookkeeping label the moderator sets after using the real tools (remove comment, archive/delete proposal, remove/ban member); this endpoint itself changes nothing about the target.

**Frontend:**
- "Report" affordance on comments and on the proposal detail page (kebab/overflow menu, not a loud button). Modal: reason picker + optional note + submit confirmation toast. Members see no indication of report counts anywhere.
- Admin "Reports" page (nav visible to `comment.moderate` holders): open-queue list grouped by target, with inline links to the target and to the relevant moderation action, plus Dismiss/Mark-actioned controls. Badge count of open reports on the admin nav entry, consistent with `PendingActionsBanner` conventions.
- Copy: neutral, no em dashes.

**Audit + notifications:** Audit `report.created` (no note body in details) and `report.resolved` (with disposition). NO notification to the reported author on report creation (invisible signal). Optional single new notification event to moderators (`report_created`, Admin actions category) respecting existing signal-level machinery; update the Phase 21 signal-level allow-list as Phase 85 did.

**Privacy:** Reporter identity is visible to the moderator queue (accountability, anti-brigading forensics) but NEVER to the reported user or other members. State this in the report modal copy: "Your report is visible to this organization's moderators."

## Cluster 2 — Rate limits on content creation (B-7)

**Keying:** Add `user_or_remote_address(request)` alongside `bypass_or_remote_address` in `rate_limit_utils.py`: same bypass conditions, then authenticated user id if resolvable, else client IP. Use it for all authenticated content endpoints below (IP-keying is the wrong unit for logged-in abuse).

**Coverage (per-user unless noted), with generous defaults tuned to never bother a legitimate pilot org:**
- Comment create: 30/hour
- Proposal create (including cosign-petition submissions): 10/day
- Write-in option add: 20/day
- Follow request create: 30/day
- Join request / open join: 20/day
- Invitation create: verify existing coverage (findings say invites are already limited); align keying if it is IP-based
- Report create: 20/day (belt-and-suspenders on Cluster 1)
- Org create: 5/day per user (the 3-org cap is the real gate; this stops create/delete cycling)

Exceed → 429 with friendly copy, consistent with existing auth-endpoint behavior. Limits are constants in one module-level place with a short comment each, so tuning is a one-line change. Do not add per-org configurability in this pass.

## Cluster 3 — Throwaway-account friction (B-9)

**Verified-email gate, uniform:** Comments already require a verified email. Extend the same requirement to ALL org-scoped write actions: proposal create, vote cast, join (open/request/invite-accept), follow request, delegation create, report create, org create. Implement as one shared FastAPI dependency (e.g. `require_verified_email`) applied per-route rather than N copies of an inline check; error copy tells the user to verify and links the resend flow. Sweep for existing inline checks and migrate them to the shared dependency.

**Registration throttle:** Verify the existing per-IP registration limit (findings say auth is limited); if registration is not covered or is generous beyond 10/hour/IP, tighten to 10/hour/IP. No disposable-email-domain blocklists in this pass (maintenance burden, easy bypass, false positives).

**Explicitly rejected for this pass:** CAPTCHA, phone verification, allowlist-only signup. The verification-floor system (Phase 51/52) is the platform's real Sybil answer; this cluster only raises the cost of casual farming.

## Verification matrix
- Side-effect assertions: report create asserts the row + audit row; duplicate open report asserts NO second row; resolve asserts status/resolver/timestamp mutation; rate-limit tests assert the 429 AND that no row was written on the rejected request; verified-email gate tests assert rejection writes nothing.
- Permission tests: queue access denied without `comment.moderate` (including the toggled-off-for-moderator-role matrix case); reporter identity absent from every non-moderator serialization (extend the serializer-coverage test for any new response schemas).
- Rate-limit bypass: confirm the debug/QA bypass still works for the new limiters and the IS_PUBLIC_DEMO fail-fast assert is untouched.
- Demo orgs: nightly demo reset must not be broken by `content_reports` rows scoped to demo orgs — include demo-org report rows in the reset wipe (check `demo_reset_job.py` wipe list) and add an assertion.
- Migration: hex-prefix, reversible, cycle-tested, PG smoke both modes, verified prod baseline first. New table only; no backfill; state explicitly.
- Browser verification: report modal end-to-end on Cedar Hollow (safe: nightly reset), queue render + resolve, badge count, 429 copy on one endpoint, unverified-account bounce copy.
- Existing tests green; report test-count delta.

## Out of scope
- Auto-hide/threshold behavior of any kind (rejected, not deferred).
- Reporting profiles, display names, DMs (goes with UGC redaction, B-5).
- Platform-admin org/logo takedown (B-10, Group 3).
- Per-org configurable limits; disposable-email blocklists; CAPTCHA.
