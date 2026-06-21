# Phase 80 — Public read-only org surfaces (Proposals + Delegates)

**Goal:** When an org has `activity_visibility='public'` ("Public read-only" in OrgSettings), let non-members — including fully logged-out / accountless visitors — click into and browse the org's **Proposals** (list + detail + comments + aggregate results) and **Delegates** (browse + per-delegate page), reusing the existing member pages in a read-only mode. All participation controls (vote, comment, delegate, create/advance/edit proposal, follow, message, etc.) are hidden for non-members. Members are unaffected.

**Scope:** Mostly frontend (routing relaxation + read-only mode + action-gating across the reused pages + a lightweight public header). Minimal backend (the public read endpoints already exist from Phase 57 + Phase 19; this pass adds only what's missing and tests the boundary). No migration.

**Branch:** `phase-80/public-read-only-surfaces` → `--no-ff` merge to master.

---

## 1. Status: what already exists (do NOT rebuild)

**Backend (ready):**
- `GET /api/orgs/{slug}/public` → `OrgPublicOut` (includes `activity_visibility`). Org-info for non-members.
- `GET /api/orgs/{slug}/public/proposals` — list (Phase 57 B5).
- `GET /api/orgs/{slug}/public/proposals/{id}` — detail (ProposalOut; no individual votes).
- `GET /api/orgs/{slug}/public/proposals/{id}/results` — aggregate tally only.
- `GET /api/orgs/{slug}/public/proposals/{id}/comments` — comments read.
- `GET /api/orgs/{slug}/delegates` — browse, `get_optional_user`, serves non-members for non-hidden orgs (Phase 19 B4).
- `GET /api/orgs/{slug}/delegates/{handle}` — per-delegate, `get_optional_user`.

All `/public/*` proposal endpoints 404 unless `discoverability != hidden` AND `activity_visibility == 'public'` (`_public_activity_org_or_404`). Same byte-for-byte 404 as a non-existent org.

**Frontend (the gap):**
- `OrgPublicLanding.jsx` fetches `/public/proposals` and renders each proposal as a **non-clickable** `<li>` (title + status). This is the "useless list" being replaced.
- Member pages (`Proposals`, `ProposalDetail`, `Delegates`, `DelegatePublic`) are locked behind `ProtectedRoute` (requires login) + `OrgScopedLayout` (requires membership → `accessDenied` pane otherwise).

---

## 2. Locked decisions (from Z)

1. **In-scope surfaces:** Proposals (list + detail + comments + aggregate results) and Delegates (browse + per-delegate). NOT delegations (personal), NOT topics/admin/sub-orgs/polises.
2. **Audience:** logged-out / accountless visitors AND logged-in non-members. Both get the same read-only experience.
3. **Reuse the existing pages** with a `canParticipate` flag — one `ProposalDetail`, not a parallel page.
4. **Landing proposals become clickable** into the proposal detail (and always show). (Alternative considered: remove them — rejected since we now have a real detail view.)
5. **Single switch:** the whole public-read-only experience is gated on `activity_visibility === 'public'`. (The delegates endpoints are more permissive server-side, but the FE only opens the browsing experience when the org opted into public read-only.)

---

## 3. Architecture

### 3a. OrgContext — resolve org for non-members
Today `currentOrg` is derived only from `userOrgs` (memberships); a non-member slug yields `currentOrg=null, accessDenied=true`.

Add a **public-org fallback**:
- Expose `isMember` (boolean): true iff `urlOrgSlug` is an active membership in `userOrgs`.
- When `urlOrgSlug` is set, not loading, and NOT in `userOrgs` (non-member or logged-out): fetch `GET /api/orgs/{slug}/public`.
  - On success with `activity_visibility === 'public'` → set `currentOrg = publicOrg`, `isMember = false`, `accessDenied = false`, `isPublicReadOnly = true`.
  - On 404 / non-public → `accessDenied = true` (current behavior).
- Members keep today's path unchanged (`isMember = true`, `isPublicReadOnly = false`).
- `OrgPublicOut` must carry enough for branding + page chrome (name, slug, branding, activity_visibility, is_demo). Extend `OrgPublicOut` only if a needed field is missing; add to the serializer-coverage allow-list per the Phase 46a convention if so.

Expose on context: `isMember`, `isPublicReadOnly` (derive `canParticipate = isMember`).

### 3b. Routing — let non-members reach the 4 routes
The four routes:
- `/:org_slug/proposals`
- `/:org_slug/proposals/:id`
- `/:org_slug/delegates`
- `/:org_slug/delegates/:handle_or_username`

Remove the hard `ProtectedRoute` (login) requirement for these four so logged-out visitors render. Replace with a new `PublicReadableOrgRoute` wrapper that:
- Renders children for everyone (no login redirect).
- Still wraps in `OrgProvider`.
- Lets `OrgScopedLayout` decide member vs read-only vs access-denied.

Sub-org variants of these routes are **out of scope** (Phase 57's public surface is parent-org only); they keep `ProtectedRoute`.

### 3c. OrgScopedLayout — three render modes
After OrgContext resolves (`loading === false`):
- **Member** (`isMember === true`): today's behavior — `<Layout>` with full `<Nav/>` + `DemoOrgBanner` + children.
- **Read-only** (`isPublicReadOnly === true`, `isMember === false`): render a new lightweight `<PublicOrgChrome>` (brand + org name/logo + "Sign in" + "Join {org}" CTA) wrapping children. Do NOT render the member `<Nav/>` (it assumes `user` + `currentOrg.user_permissions`). The Phase 79 demo-fence Layer 2 still applies (demo persona on a non-demo org → logout) and runs before this.
- **Access denied** (no org resolved, not public): today's access-denied pane.

Keep the existing `loading` branch. The new chrome path must also apply branding (`OrgScopedBrandingTheme` / `BrandingThemeApplier`).

### 3d. Pages — read-only mode + endpoint switch
Each reused page reads `isMember` from context. When `!isMember`:
- **Data:** fetch the `/public/*` sibling endpoint instead of the member endpoint.
  - `Proposals.jsx` → `/public/proposals`.
  - `ProposalDetail.jsx` → `/public/proposals/{id}` + `/results` + `/comments`.
  - `Delegates.jsx` → `/delegates` (same endpoint; already optional-auth).
  - `DelegatePublic.jsx` → `/delegates/{handle}` (same endpoint).
- **Hide all participation controls** (see the gating checklist, §4).
- **Individual vote data stays hidden** — read-only proposal detail shows aggregate results only (no vote network / per-delegate vote breakdown). This matches Phase 57's privacy posture (the public endpoints never return individual votes).

### 3e. Landing — clickable proposals
In `OrgPublicLanding.jsx`, wrap each proposal row in a `<Link to={`/${slug}/proposals/${p.id}`}>` and keep the list always visible. (The list already only renders when the org is public-readable.) Add a "View all proposals" link to `/${slug}/proposals`, and surface the delegates browse entry (`/${slug}/delegates`) on the splash.

---

## 4. Action-gating checklist (the load-bearing audit)

Every interactive/participation control on the reused pages MUST be hidden (preferred) or disabled when `!isMember`. Source-review each page and confirm:

**Proposals.jsx (list):**
- [ ] "New / Create proposal" button hidden.
- [ ] Any per-row quick-vote / status-change affordances hidden.
- [ ] Filters/search may stay (read-only safe). "To vote" filter (Phase 76e) hidden (meaningless to non-members).

**ProposalDetail.jsx:**
- [ ] Vote/ballot controls (binary/approval/RCV/budget) hidden.
- [ ] Comment composer hidden; comments render read-only.
- [ ] Delegate-on-this-topic / delegation controls hidden.
- [ ] Author/admin controls (edit, advance, archive, withdraw, manage) hidden.
- [ ] Vote network / individual-vote breakdown hidden; aggregate results shown.
- [ ] "Your vote / your delegate" personalized panels hidden.

**Delegates.jsx (browse):**
- [ ] "Become a delegate" / manage-my-profile CTA hidden.
- [ ] Per-delegate "Delegate to" / follow / message buttons hidden.

**DelegatePublic.jsx (per-delegate):**
- [ ] "Delegate to" / revoke / follow / message buttons hidden.
- [ ] Public voting record + rationales render read-only (these are already public surfaces).

**Cross-cutting:**
- [ ] `MessageButton` (Phase 77) never renders for non-members.
- [ ] No control links to a member-only route that would bounce to `/login`.
- [ ] A single, friendly "Join {org} to participate" CTA appears in the read-only chrome (not per-control nags).

Defense-in-depth: the backend already gates writes behind membership/permission deps, so a bypassed FE control fails server-side — but the FE must not surface dead controls.

---

## 5. Backend work (minimal)

- **Verify** the delegates endpoints serve logged-out users for an `activity_visibility='public'` org and return the expected shape. They gate on `discoverability != hidden`, which is satisfied for any listed/unlisted public-readable org. No code change expected; add tests.
- **If** any in-scope read needs an endpoint that doesn't exist yet (none identified), add it following the `_public_activity_org_or_404` pattern.
- **Do NOT** relax any write/participation endpoint. Membership/permission deps on vote/comment/delegate/create stay exactly as-is.
- Confirm `OrgPublicOut` carries the fields §3a needs; extend + cover per Phase 46a if not.

---

## 6. Tests

**Backend (pytest):**
- [ ] `/public/proposals*` endpoints: 200 + correct shape for an `activity_visibility='public'` org; 404 for `members_only`; 404 for `hidden`. (Some exist from Phase 57 — extend, don't duplicate.)
- [ ] Delegates browse + per-delegate: 200 for logged-out viewer on a public org; correct empty/visibility behavior.
- [ ] Negative: write endpoints (vote/comment/delegate/create) still 401/403 for non-members on a public org. (This is the security assertion — assert the side effect did NOT happen.)
- [ ] `OrgPublicOut` serializer coverage if a field was added.

**Frontend:** browser-verify per CLAUDE.md (QA pending if Chrome disconnected — note in closeout). Source-review the §4 gating checklist regardless.

---

## 7. Verification matrix

| Check | Required | Notes |
|---|---|---|
| Logged-out visitor opens `/{slug}/proposals` on a public org | ✅ | List renders, rows clickable |
| Logged-out opens `/{slug}/proposals/{id}` | ✅ | Detail + comments + aggregate results; no vote/comment controls |
| Logged-out opens `/{slug}/delegates` + a delegate page | ✅ | Browse + per-delegate read-only |
| Same routes on a `members_only` org while logged-out | ✅ | Access-denied / 404 posture (no leak) |
| Member experience unchanged on a public org | ✅ | Full Nav, all controls present |
| Landing proposals clickable + delegates entry present | ✅ | |
| Non-member cannot vote/comment/delegate via direct API call | ✅ | 401/403, no row written |
| Demo persona fence (Phase 79) still fires on non-demo org routes | ✅ | Layer 2 runs before read-only chrome |
| Full backend suite green; build clean | ✅ | No migration |
| Prod deploy verified (bundle hash + backend 200) | ✅ | Browser QA if Chrome available |

---

## 8. What's NOT in scope
- Delegations page, topics, admin, sub-orgs, polises public exposure.
- Sub-org public surfaces.
- Relaxing any write endpoint.
- Individual delegate-vote exposure beyond the existing public surfaces.
- Changing the `activity_visibility` setting model or its OrgSettings UI.

---

## 9. Operational watch-outs
- **OrgContext public fallback must not fire for members** (avoid a redundant `/public` fetch) and must not loop. Gate the fetch on `!loading && urlOrgSlug && !isMember`.
- **Nav reuse risk:** do NOT try to make the member `Nav` render for anonymous users; use the dedicated `PublicOrgChrome`. This is why read-only mode gets its own chrome.
- **Branding** must still apply in read-only mode (logo/colors) — wire `BrandingThemeApplier` on the public path.
- **api client + logged-out:** ensure the api helper omits the auth header gracefully when there's no token (public endpoints need no auth); a 401 from a mistakenly-member endpoint must not redirect-to-login the read-only viewer.
- **PWA/bundle cache** caveat for QA per memory.
