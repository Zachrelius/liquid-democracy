# Phase 9 — pol.is API verification findings

**Date:** 2026-04-29
**Author:** Phase 9 Session 1 backend dev
**Method:** Source-reading against the public open-source `compdemocracy/polis` repo on GitHub (edge branch). The hosted pol.is at `https://pol.is` runs the same code; live HTTP probes against `https://pol.is/api/v3/*` confirmed reachability and the JWT auth wall (401 "No authentication token found" on `POST /api/v3/conversations`).

WebFetch / WebSearch tools were not permitted in this session, so this report is derived from raw source files in `compdemocracy/polis` plus direct unauthenticated HTTP probes against the hosted endpoint. That is sufficient to establish what the API supports — but **we have not exercised any of these endpoints with a real authenticated session**. Production wiring will need to verify against a real account.

---

## TL;DR for the lead

- The Polis API **supports everything we need programmatically** — conversation creation, seed-statement insertion (single + bulk), participation stats, conversation close (archival), data export, xid-keyed identity bridging.
- **BUT the auth model is JWT-based, not API-key-based.** There is no documented "POLIS_API_KEY" the way the spec assumed. Programmatic access requires a Bearer JWT issued via OIDC (or a valid legacy session cookie). For the hosted `pol.is` instance, the OIDC issuer is the Polis-controlled authentication system; in practice, this means we'd need to either (a) reuse the cookie/JWT obtained from logging in to pol.is as an admin user, or (b) negotiate something custom with the pol.is operators (CompDemocracy / The Computational Democracy Project).
- **Conversation IDs are short opaque tokens** (default 10 chars, 6 chars if `short_url=true`), not UUIDs. Lowercase alphanumeric, ambiguous-character-stripped (no `o/O/0/1/l/L`, etc.). They fit fine in any reasonable string column.
- **xid is 1-999 chars opaque.** UUID format (36) and `secrets.token_urlsafe(16)` (~22) both fit comfortably.
- **Recommendation:** ship Session 1's data layer and `polis_service.py` wrapper as planned, but build it assuming **the v1 production deploy will use a manual-admin-creates-the-conversation-on-pol.is-then-pastes-the-conversation-id flow as the primary path**, with the programmatic path available as a "Tier 2" enhancement once we either (a) get Bearer-token auth working with a pol.is admin account, or (b) self-host (Phase 9.x or later, per spec's Out-of-Scope note). The platform-side data model and service-layer shape are unchanged either way; the only change is that `polis_service.create_conversation()` may end up being a no-op-with-warning in v1 prod and the create-Polis form has a "paste the conversation_id from pol.is here" field instead of seed statements being wired up automatically.

---

## Detailed findings

### 1. Auth model

**No API key.** Polis uses a hybrid JWT middleware (`server/src/auth/hybrid-jwt.ts`) that accepts four token types in priority order:

1. **XID JWT** — issued by Polis on first xid participation; scoped to a single conversation; long-lived (1 year per source comments). Used by participants embedded via `data-xid`.
2. **Anonymous JWT** — for anonymous participants.
3. **Standard User JWT** — issued after OIDC login, identifies a real Polis user.
4. **OIDC JWT** — direct OIDC tokens from the Polis-configured OIDC issuer (`Config.authIssuer` / `Config.authAudience`).
5. **Legacy cookie** — backward-compat cookie session.

All admin endpoints (`POST /api/v3/conversations`, `POST /api/v3/comments`, `POST /api/v3/comments-bulk`, `POST /api/v3/conversation/close`, `GET /api/v3/dataExport`, etc.) require `hybridAuth` — i.e., one of the JWT types above (NOT XID or Anonymous, since those are scoped to participation, not admin actions).

**Practical implication:** to call these programmatically, you need:
- A pol.is admin account (you create one at `https://pol.is/createuser` or the equivalent).
- A way to obtain a session JWT or cookie tied to that account. The Polis authentication flow goes through OIDC (`server/src/auth/jwt-middleware.ts` validates against `Config.authIssuer`); for the hosted instance, that issuer is operated by CompDemocracy.
- The same Bearer JWT gets sent on subsequent API calls.

**No public documentation of how to get this token programmatically for the hosted instance.** Self-hosting bypasses this (you control the OIDC issuer / config), but the spec defers self-hosting.

**Recommendation for `POLIS_API_KEY` env var:** repurpose as `POLIS_AUTH_TOKEN` (or `POLIS_BEARER_JWT`) in `polis_service.py`. Document in `DEPLOYMENT.md` that this is "the Bearer JWT obtained from a pol.is admin session" with a TODO that prod-wiring needs CompDemocracy involvement or self-hosting. For Session 1, the env var being unset is the expected dev case and `polis_service.py` raises `PolisAPIError("POLIS_AUTH_TOKEN not configured")` cleanly.

### 2. Conversation creation — `POST /api/v3/conversations`

**Yes, programmatic.** Source: `server/src/routes/conversations.ts` `handle_POST_conversations`, route registered at `server/app.ts:1647`.

Request body (all optional unless noted):
```
is_active (bool, default true)
is_draft (bool, default false)
is_anon (bool, default false)
owner_sees_participation_stats (bool, default false)
profanity_filter (bool, default true)
short_url (bool, default false)         # if true, conversation_id is 6-char (vs 10-char default)
spam_filter (bool, default true)
strict_moderation (bool, default false)
context (string, ≤999 chars, default "")
topic (string, ≤1000 chars, default "")
description (string, ≤50000 chars, default "")
conversation_id (string, 6-300 chars, default "")  # if you want to specify your own
is_data_open (bool, default false)
ownerXid (string, 1-999 chars)          # bind owner to xid
treevite_enabled (bool, default false)
topics_enabled (bool, default false)
```

Response: a conversation row including `conversation_id` (the slug used in URLs and embeds). On success the URL pattern is `https://pol.is/<conversation_id>` and the embed iframe URL follows the same root.

**Conversation ID shape:** generated by `generateAndRegisterZinvite` (`server/src/auth/create-user.ts:7`), which calls `generateTokenP(10, false)` — 10-char base64-derived token with ambiguous chars (l/L/o/O/0/1, etc.) substituted out, lowercased. With `short_url=true`, it's 6 chars. The `conversation_id` request parameter is bounded to 6-300 chars if provided explicitly.

For platform storage: a `String(64)` column is more than enough; `String(300)` is the strict upper bound.

### 3. Seed statements — `POST /api/v3/comments` (single) and `POST /api/v3/comments-bulk` (CSV)

**Yes, programmatic.** Both routes at `server/app.ts:777` and `server/app.ts:796`.

Single statement:
```
POST /api/v3/comments
need: conversation_id, txt (1-997 chars)
want: vote (-1, 0, 1), is_seed (bool), xid
```

Bulk CSV upload:
```
POST /api/v3/comments-bulk
need: conversation_id
want: is_seed (bool), xid
body: CSV
```

The `is_seed=true` flag distinguishes admin-created seed statements from participant submissions.

**This is load-bearing and works.** The spec's worry about seed statements being admin-UI-only is **not** a real concern — the UI literally just calls these endpoints. Same Bearer JWT auth as conversation creation, so the same auth caveat applies (you need an admin Bearer JWT).

`polis_service.py.add_seed_statements()` can call `POST /api/v3/comments` in a loop or `comments-bulk` for batch. Recommend looping single-call for clearer error attribution per statement.

### 4. Identity bridging — `data-xid`

`xid` is opaque to Polis. Length bound 1-999 chars (`getStringLimitLength(1, 999)` everywhere xid is accepted in `app.ts`). Polis stores it in a `xids` table keyed against the platform-internal user id (`uid`), and issues an XID JWT scoped to a single conversation on first participation.

**No hashing/munging.** Polis takes the xid as-is.

UUID (36 chars) fits. `secrets.token_urlsafe(16)` (22 chars) fits and is recommended for opacity. Don't pass user_id directly.

### 5. Participation stats — `GET /api/v3/conversationStats`

Available. Accepts `conversation_id`, optional `report_id` and `until` (timestamp). `hybridAuthOptional` — works without auth for public reads. Returns participant/comment/vote counts. Suitable for the live link-card display.

There's also `GET /api/v3/participation` (auth required), `GET /api/v3/participationInit`, and `GET /api/v3/topicStats` for richer reporting.

### 6. Archival — `POST /api/v3/conversation/close` and `POST /api/v3/conversation/reopen`

Available, programmatic, requires admin auth. Both at `server/app.ts:1335` and `:1347`.

Closing a conversation prevents further participation but preserves data. Reopening reverses it. **No data loss.**

This satisfies Decision 8 (active → archived lifecycle) and the Open Question about closing pol.is-side when archiving on the platform.

### 7. Data export — `GET /api/v3/dataExport`

Available. `server/app.ts:364`. Requires admin auth. Accepts `conversation_id`, `format`, `unixTimestamp`. There's also `GET /api/v3/dataExport/results` for fetching async-generated export files.

The export is keyed on Polis-side participant ids and includes xid where set, so the platform-side join `polis_xid → user_id` works as the spec describes.

### 8. Rate limits

Source-reading didn't surface explicit rate-limit middleware on the admin endpoints (no obvious `express-rate-limit` or similar wrapping `POST /api/v3/conversations`). The hosted pol.is may have CloudFront / nginx-level limits not visible in the app source. **Reasonable for occasional admin actions** (creating Polises, fetching stats) but treat as unknown — `polis_service.py` should retry-with-backoff on 429 (one or two retries, not a long loop).

### 9. Failure modes (observed via probe)

- Missing Bearer token: `401 {"error":"No authentication token found"}` (confirmed via direct curl).
- Invalid Bearer token: `401 {"error":"Invalid authentication token", "details": ...}` (per `hybrid-jwt.ts:237`).
- Token doesn't match any known type: `401 {"error":"Invalid token format", ...}`.
- Missing required body param: typically `polis_err_*` failJson responses (see `route_conversations.ts`).
- Bad conversation_id reference: `polis_err_*` 4xx.

`polis_service.py` should map all 4xx/5xx responses to `PolisAPIError(message, status)` cleanly. Don't try to interpret the `polis_err_*` codes — log them but surface a generic "pol.is API error" to the user.

### 10. Embedding

The standard pol.is embed snippet is:
```html
<div class="polis" data-conversation_id="<id>" data-xid="<opaque>"></div>
<script async src="https://pol.is/embed.js"></script>
```

`data-xid` is the load-bearing identity bridge. Frontend Session 4 work.

---

## Decisions affected

1. **`polis_xid` storage shape.** No length constraint that would force a particular choice. The recommended default — separate `polis_xids` table keyed on (user_id, org_id) — stands. Going with that for cleaner separation.

2. **`polis_conversation_id` column shape.** `String(64)` is comfortable. (10 chars default, 6 for short_url, 300 hard ceiling if author specifies their own.) Going with `String(64)` to leave headroom.

3. **`POLIS_API_KEY` env var rename.** Going with `POLIS_AUTH_TOKEN` per Item 1 above. `polis_service.py` raises `PolisAPIError` clearly when missing.

4. **Manual-fallback flow.** `polis_service.create_conversation()` and `add_seed_statements()` are real implementations against the documented endpoints. They will only succeed when `POLIS_AUTH_TOKEN` is configured — which in dev it isn't, and in prod it requires either a CompDemocracy-provided admin token or self-hosting. **The create-Polis route in Session 2 should be designed to support both flows:** programmatic-creation (when token is configured) and manual-creation (operator pastes a `conversation_id` they created on pol.is themselves). The `Polis.polis_conversation_id` column being nullable already accommodates this. **Surface this to the lead — the create-Polis form's seed-statements field will need a "we'll insert these for you if API access is configured, otherwise paste them into the pol.is admin UI" framing in Session 3.**

5. **Audit event for archival.** `polis.archived` should record both platform-side state change AND the result of the `/api/v3/conversation/close` call (success / failed-but-platform-archived). Session 2 design note.

---

## Open items for Session 2 / 3 / 4

- **CompDemocracy contact.** Lead should ask CompDemocracy (`hello@compdemocracy.org` per their README) whether they support programmatic admin access to the hosted pol.is for third-party platforms, and what auth flow they recommend. If "no, only via the admin UI," then the manual-fallback flow is the v1 production path.
- **Self-hosted pol.is.** The spec defers this to Tier 3.9. Worth keeping on the radar as the cleanest fix to the auth-token problem.
- **Real-API integration test.** Cannot run from CI without an admin token. Out-of-scope for Session 1 tests (mocked HTTP). Worth a manual test by the lead in Session 4 (prod sanity).
- **`/api/v3/embed.js` cache headers.** Not investigated. Frontend will load it from `https://pol.is/embed.js` — confirm CSP allows it.

---

## Files referenced from the Polis source (saved locally to `.tmp_diag/` for this session, not committed)

- `polis_app.ts` (server/app.ts edge) — full route table
- `hybrid-jwt.ts` (server/src/auth/hybrid-jwt.ts) — auth model
- `xid-jwt.ts`, `auth_readme.md`, `auth.ts`, `auth_routes.ts` — auth details
- `generate-token.ts`, `create-user.ts` — conversation_id format
- `route_conversations.ts`, `route_dataExport.ts`, `route_comments.ts` — handler signatures
- `xids.ts`, `conversation.ts`, `zinvite_util.ts` — supporting modules

These can be re-fetched from `https://raw.githubusercontent.com/compdemocracy/polis/edge/<path>` if needed for Session 2/3/4 work.
