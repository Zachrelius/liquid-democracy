# Phase 87 — Verify-Email False Error Fix + Org Takedown + Minimal Platform-Admin Frontend + Admin Provisioning

**Source:** Phase 83 finding B-10 (Group 3) plus a newly observed prod bug (email-verification false error). Read `phase83_readiness_findings_2026-07-02.md` for B-10 context.

**Type:** Build pass. One migration (new nullable columns on `organizations`). Single deploy. Does NOT touch `start.sh` or deploy-time codepaths.

**Design decisions (locked by Z — do not relitigate):**
1. Takedown ships BOTH tools: delist (org keeps functioning, vanishes from public view) and full reversible suspension (org inaccessible to everyone including members). Delist is the default/proportionate tool; suspension is the escape hatch.
2. Platform admin operates from a dedicated account (ZacharyAdmin, z@liquiddemocracy.us), not Z's daily account. The seeded bootstrap admin gets disabled.
3. The platform-admin frontend is a minimal toolbench, not a dashboard.

---

## Cluster 0 — Email-verification false error (prod bug, hits every new user)

**Diagnosis (confirmed in source):** `frontend/src/pages/VerifyEmail.jsx` — the verify effect depends on `[token, persistedNext, user, refreshUser, navigate]`. After the first successful POST, `persistedNext` state resolution and/or the `user` object changing (via `refreshUser`) re-fires the effect, which POSTs the same token again; the backend rejects the consumed token and the `.catch` overwrites `status='success'` with the red-X error. Users end up verified but told verification failed.

**Fix, both ends:**
- **Frontend:** run-once guard (`useRef`) so the POST fires exactly once per mount regardless of dependency churn; restructure so the persistedNext/navigation logic doesn't share an effect with the POST. Also guard against a transition from `success` back to `error` (state machine only moves forward).
- **Backend:** make `POST /api/auth/verify-email` idempotent for the benign case — if the token is invalid/consumed BUT the user it belonged to is already `email_verified`, return 200 "already verified" instead of an error. (Token rows must retain user linkage after consumption, or match on a hash — read the actual `email_verifications` implementation and pick the cheapest correct mechanism; if consumed tokens are hard-deleted, say so and solve FE-only with a note.) Genuinely invalid/expired tokens for unverified users still error. This also covers email-scanner pre-clicks and double-clicked links.
- **Tests:** double-POST of the same token asserts (a) user verified after first, (b) second returns the benign success, (c) no duplicate side effects. FE change is covered by browser verification below.

## Cluster 1 — Org takedown backend (B-10)

**Model:** `organizations` gains `platform_restriction` (nullable string enum: NULL/none | `delisted` | `suspended`), `restricted_at`, `restricted_by_id` (FK users), `restriction_reason` (text, admin-facing only). Single-field state machine; reverting sets restriction back to NULL but leaves an audit trail (audit log is the history; no separate history table this pass).

**Delisted semantics:** org remains fully functional for members. Effective public posture is forced regardless of org settings: excluded from `/explore`, public landing 404s to non-members, logo not served on any public surface. Org admins CANNOT counteract it: the org settings UI shows a notice ("This organization has been restricted from public listing by platform moderation") and discoverability edits while delisted don't restore public visibility. Enforce at read/serve time (effective-discoverability helper), not by overwriting the org's stored settings — reverting then restores their prior configuration untouched.

**Suspended semantics:** org inaccessible to everyone except platform admins. All org-scoped routes (API and pages) return a clean 404-style response for members and non-members alike; memberships, content, delegations all remain intact in the DB; nothing is deleted. Login still works for affected users (suspension is org-level, not account-level). Enumerate the org-resolution entry points (the org-context dependency the routes share, public landing, explore, join paths, invitation acceptance, notification emission for that org) and gate each — grep for how org context is resolved rather than assuming a single chokepoint; Phase 4c multi-tenancy debt means there may be org-blind paths, and any found should be flagged in the closeout.

**Endpoints:** platform-admin-only (existing `get_current_admin` dependency) in `routes/admin.py`: `GET /api/admin/orgs` (list with name, slug, member count, discoverability, restriction state), `PATCH /api/admin/orgs/{id}/restriction` (set delisted/suspended/none; `reason` REQUIRED on restrict, optional on revert). Audit events `org.restriction_set` / `org.restriction_reverted` with actor, org, restriction, reason.

**Demo orgs:** restriction must never be applied to `is_demo` orgs (422) — the nightly reset and demo login paths are not built to handle it.

## Cluster 2 — Minimal platform-admin frontend

- Route `/platform-admin`, gated on the current user's `is_admin` (verify `is_admin` is serialized on the user response the FE reads; if not, add it and extend the serializer must-surface test). Non-admins get a silent redirect, and no nav affordance exists for them; admins see a "Platform" nav entry.
- Page 1 — Organizations: table from `GET /api/admin/orgs` with restriction badge and actions: Delist / Suspend / Revert, each behind a ConfirmDialog requiring the reason text. No em dashes in copy.
- Page 2 — Users: render the existing `GET /api/admin/users` list (read-only this pass; no make-admin button in the UI — that stays API/DB-only deliberately).
- Reuse existing admin-page styling/components; this is a toolbench. Nothing here is org-scoped, so keep it outside the org-context layout.

## Cluster 3 — Admin provisioning (prod, one-time)

1. Flip `is_admin = TRUE` on the user with email `z@liquiddemocracy.us` (username ZacharyAdmin) directly in the prod DB (account already exists, registered and email-verified by Z).
2. Disable the seeded bootstrap admin: set `is_active = FALSE` on it (identify it by the seed path in the codebase; do not delete the row). Confirm nothing operational depends on that account (grep seed/demo/scheduler code) before disabling; if something does, report instead of disabling.
3. Closeout must state both as OBSERVED (queried rows after mutation), and confirm ZacharyAdmin can load `/platform-admin` in prod.

## Verification matrix
- Side-effect assertions throughout: restriction PATCH asserts the org row fields + audit row; delisted org asserts absence from /explore query results and 404 on public landing while stored discoverability is unchanged; suspended org asserts member API access rejected AND rows intact; revert asserts full restoration of prior public posture.
- Double-verify-token test per Cluster 0.
- Demo-org restriction attempt → 422, no mutation.
- Migration: hex-prefix, reversible, cycle-tested, PG smoke both modes, verified prod baseline. Nullable columns, no backfill — state explicitly.
- Browser verification (prod after deploy): fresh throwaway signup end-to-end to confirm the verify-email page lands green with no error flash (this is the bug's only true test); /platform-admin renders for ZacharyAdmin and is absent/redirects for a normal account; delist+revert exercised against a purpose-made throwaway org (create one; do NOT restrict real or demo orgs), confirming /explore disappearance and reappearance.
- Existing tests green; report test-count delta.

## Out of scope
- UGC redaction (B-5/B-6) — next Group 1 slice.
- Org-name/impersonation validation beyond the existing reserved-slug list.
- Platform-admin actions beyond takedown + read-only users (no make-admin UI, no platform settings UI).
- 2FA (worth a future conversation given the admin tier, but not this pass).
