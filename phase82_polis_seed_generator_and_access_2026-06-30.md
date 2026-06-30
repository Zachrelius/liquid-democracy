# Phase 82 — Polis: seed-CSV generator + member access + disclosure cleanup

**One-line dispatch:** `Read and execute phase82_polis_seed_generator_and_access_2026-06-30.md`

**Team:** continuing-dev (Polis subsystem + smart-import plumbing context).

**Type:** Single deploy is feasible but this is at the upper edge — 3 clusters, one new backend module, one new route, a new nav data dependency, frontend across create/detail + nav + embed surfaces, and NO migration. It does NOT trip the Greater-Phase threshold (no migration, no novel infra, <50 new tests, the clusters are independent). Ship as one deploy unless the team's own sizing flags otherwise; if staged, the order is C1 (generator) → C2 (member access) → C3 (disclosure), each independently shippable.

Builds on Phase 81 (link-existing Polis flow). All three clusters came out of Z's live-testing pass on the Reform Table.

---

## What this pass does

Three independent improvements to the Polis system:

- **C1 — Seed-statement CSV generator (Sonnet-powered).** An admin clicks a button, Sonnet drafts pol.is seed statements, they land in an editable list the admin can add to / edit / remove / reorder / regenerate, then a "Download CSV" button produces a pol.is-import-format `.csv`. No pol.is API integration — the output is a file the admin uploads to pol.is themselves. Reuses the `smart_import.py` Anthropic-call pattern exactly.
- **C2 — Member access to Polises.** Today ordinary members can only reach a Polis if it's linked to a proposal (via `LinkedPolisCard`); there's no nav entry. Add a member-facing "Deliberations" nav link, presence-gated: it appears only when the org has ≥1 Polis the member is eligible to see. No org-level setting (consistent with how the rest of the nav self-gates).
- **C3 — Remove the Polis disclosure modal.** The first-visit-per-Polis `PolisDisclosureModal` interrupts to say things that are largely self-evident (statements are authored to be read) or already-familiar (anonymous dots in a graph, like the existing vote/delegation graphs). Remove the modal; relocate the genuinely-informative identity mechanics (random per-org pseudonym, cross-org isolation, moderation deanonymization) into the `PolisHelp` page and a quiet inline "How your identity works here" link near the embed.

---

## Decisions locked (do not re-litigate)

- **D1 — Generator context inputs:** the Polis's discussion topic + description (required substance), an OPTIONAL freeform "steer" field the admin can fill, and an OPTIONAL "include our org description" checkbox that pulls `Organization.description`. Deliberately NOT included: the org's topic taxonomy, the proposal corpus, or member data. Rationale: org-corpus context biases the model toward house-style, agreeable, one-sided statements — the exact failure mode that ruins pol.is clustering. The freeform steer is the high-value lever (the human knows what disagreement to surface); it replaces any auto-pulled org context. Org description is opt-in only because it adds register/tone but mildly risks the same house-lean.
- **D2 — Generator output is an editable list, then a CSV download.** Not fire-and-forget. The admin reviews/edits before download (same human-gate as smart import). The list is usable with or without generation — an admin can hand-type all statements if the AI is down or they prefer. Generation is an accelerator, not a dependency.
- **D3 — CSV format is pol.is's native import shape:** a `comment_text` header row, then one statement per row, using REAL CSV quoting (statements contain commas/quotes/newlines). The download serializer trims whitespace, drops empty/whitespace-only rows, and de-dupes exact duplicates.
- **D4 — Graceful degradation mirrors smart_import:** no `ANTHROPIC_API_KEY` → the Generate button is hidden (not a dead 503 button); a timeout/malformed response → a warning + the list stays usable for manual entry, never a 500.
- **D5 — Generator lives in BOTH the create flow and the detail page.** Create flow reads topic/description from live form state (pre-save). Detail page reads from the saved Polis record. Same component, two input sources.
- **D6 — Member Deliberations nav entry is presence-gated, no org setting.** Link appears iff the org has ≥1 Polis visible to this member under the existing `eligible_viewers_for_polis` logic. Org that doesn't use Polis → no link, no dead button, no config.
- **D7 — Remove the disclosure modal entirely; do not demote-but-keep.** Relocate identity mechanics to PolisHelp + an inline "How your identity works here" link near the embed. The one fact worth keeping reachable (not pushed): the platform can deanonymize for moderation.
- **D8 — No migration.** Nothing in this pass adds or alters a column. The generator is stateless (it does not persist statements anywhere — they go straight to a downloaded file; this is consistent with Phase 81 dropping `intended_seed_statements` from the UI). `eligible_viewers_for_polis` already exists.

**Explicitly deferred (NOT in this pass), logged in Backlog:**
- Per-conversation public-username opt-in (handle-as-xid). Real but needs its own values call — permanence, harassment surface, handle-uniqueness. Spec-ready notes in Backlog.
- The `site_id`/`page_id` auto-creation embed. Recon done; shelved pending a pilot request + two live-account verifications. Notes in Backlog.

---

## Grounding (verified against source this pass)

- `backend/smart_import.py` — the Anthropic-call template. Confirmed pattern: `is_configured()` gates on `ANTHROPIC_API_KEY`; `_call_anthropic(system, user, api_key, model)` is the isolated, monkeypatchable POST to `https://api.anthropic.com/v1/messages` with `anthropic-version: 2023-06-01`, `max_tokens` set, model from `SMART_IMPORT_MODEL` (default `claude-sonnet-4-6`); `generate_drafts` returns `(result, warning)` and degrades to `([], warning)` on any failure. The seed generator is a sibling module following this shape — DO NOT invent a new Anthropic-call pattern.
- `backend/models.py` — `Organization.description` is `Text, default=""` (the C1 checkbox source). `Polis.title` / `Polis.prompt` hold the discussion topic / description (Phase 81 relabel was UI-only; columns unchanged). `PolisXid` confirms the pseudonym is `secrets.token_urlsafe(16)` keyed on `(user_id, org_id)` — the C3 help copy describes exactly this.
- `backend/polis_service.py` — `get_or_create_polis_xid` is the pseudonym source of truth; `secrets.token_urlsafe(16)` (~22 chars), per-`(user_id, org_id)`, opaque, stable-within-org, different-across-orgs. C3 help copy must match this precisely.
- `frontend/src/components/Nav.jsx` — the nav is entirely presence/permission-gated (Messages appears when `messagesSlug` resolves; Admin subsections gate on permission keys via `ADMIN_NAV_SUBSECTION_PERMISSIONS`). There is NO member-facing Polis link today — `showPolises` is admin-only (`polis.*` perms). The member Deliberations link (C2) follows the Messages-badge precedent: a cheap hook (`useHasVisiblePolises(slug)` or similar) drives visibility. Mobile drawer mirrors desktop.
- `frontend/src/components/PolisDisclosureModal.jsx` — the modal removed in C3. Grep for its import sites (member `Polis.jsx`, possibly `PolisEmbed.jsx` wrapper) and remove the gate, not just the file.
- `frontend/src/pages/PolisHelp.jsx` — the relocation target for C3 identity mechanics.
- **MUST READ before building C1 frontend:** `/mnt/skills/public/frontend-design/SKILL.md` (the editable-list + generate/regenerate UI is new UI surface). **MUST READ before building C2:** confirm `eligible_viewers_for_polis` signature in `backend/routes/polises.py` (or wherever it lives) and how the member Polis-list endpoint is scoped. **Confirm** whether a member-facing "list polises for org" endpoint already exists or must be added (the admin `Polises.jsx` list uses an admin-gated endpoint; members need an eligibility-filtered one).

---

## Cluster C1 — Seed-statement CSV generator

### Backend

**New module: `backend/polis_seed_generator.py`** (sibling to `smart_import.py`, same shape).

- `is_configured() -> bool` — `bool(os.getenv("ANTHROPIC_API_KEY"))`. (Identical to smart_import; you may import smart_import's if you prefer one source, but a local copy keeps the module self-contained — team's call.)
- `_model() -> str` — reuse `SMART_IMPORT_MODEL` env (default `claude-sonnet-4-6`). One model knob for both AI features is fine; if the team wants a separate `POLIS_SEED_MODEL` env that's acceptable but not required.
- `_call_anthropic(system, user, api_key, model) -> str` — same isolated POST as smart_import (copy it; tests monkeypatch it). `max_tokens` ~2048 is plenty for ~15 short statements.
- `SYSTEM_PROMPT` — the craft. This is the load-bearing content of the cluster. It MUST encode what makes a good pol.is seed statement:
  - Each statement is a SINGLE, clear, standalone assertion (one idea — not compound, not a list).
  - Each is an OPINION a reasonable person could agree OR disagree with — never a question, never a neutral fact.
  - The SET spans the genuine spectrum of views on the topic, INCLUDING minority, contrarian, and uncomfortable positions — the clustering is only useful if real disagreement is represented. Explicitly instruct the model to include positions the org's own leadership might not hold. (This mirrors the Reform Table content rule: contrarian options included to make rankings honest.)
  - Statements are concise (roughly one sentence; pol.is participants vote agree/disagree/pass on each).
  - Neutral phrasing — not loaded, not strawmanned. A good disagree-voter should feel the statement is a fair version of a view someone holds.
  - No duplicates / near-duplicates; cover distinct facets of the issue.
  - Target 12-15 statements (pol.is recommends 10-15; generating slightly over the floor lets the admin prune).
  - Output format: respond with ONLY a JSON array of strings, no preamble, no markdown fences. (Same parse-discipline as smart_import; reuse a `parse_llm_array`-style extractor that tolerates stray prose by slicing first `[` to last `]`.)
- `build_user_message(*, topic, description, steer, org_description) -> str` — composes: the discussion topic, the description, the optional freeform steer ("Additional steer from the organizer: ..."), and the optional org description ("This conversation is run by an organization that describes itself as: ..."). Omit any that are empty. Keep it short — this is a focused generation, not a document parse.
- `generate_statements(*, topic, description, steer, org_description) -> tuple[list[str], Optional[str]]` — returns `(statements, warning)`. Empty topic AND description AND steer → return `([], "Enter a discussion topic or description first so the generator has something to work from.")` (don't call the API on empty input). On any API/transport failure → `([], "<friendly degradation message>")`, never raise. On unparseable output → `([], "<could-not-parse message>")`. Strip/trim each returned statement; drop empties; de-dupe.

**New route: in `backend/routes/polises.py`** (or a small dedicated router if the team prefers).

- `POST /api/orgs/{slug}/polises/seed-statements/generate`
  - Permission: gated on `polis.create` OR `polis.edit` (whoever can create/manage a Polis can generate seeds). Reuse the existing Polis-permission dependency in this router.
  - Body: `{ topic: str = "", description: str = "", steer: str = "", include_org_description: bool = false }`.
  - If `not is_configured()` → 503 with `{"detail": "AI seed generation isn't configured on this platform."}` (the frontend hides the button in this case, but the route defends anyway).
  - Resolve `org_description`: when `include_org_description` is true, read `Organization.description` for the slug's org (server-side; do NOT trust a client-passed description). Empty string when the org has none.
  - Call `generate_statements(...)`. Return `{ "statements": [...], "warning": <str|null> }`. Always 200 when configured (degradation is in the `warning`, not an error status) EXCEPT the 503-not-configured case.
  - Audit: emit a light `polis.seed_statements_generated` audit event (aggregate only — count of statements, the org; NOT the statement text). Mirrors smart-import's audit posture.
  - Caps: cap `topic`/`description`/`steer` input lengths (e.g. 2000 chars each) and the returned statement count (hard cap 30) defensively.

**No persistence.** The generated statements are returned to the client and live only in the editable list until downloaded as CSV. Nothing is written to the `polises` row (consistent with Phase 81 dropping the seed UI/storage). Do NOT revive `intended_seed_statements` writes.

### Frontend

**New component: `frontend/src/components/PolisSeedGenerator.jsx`** (read `frontend-design/SKILL.md` first).

- Props: the current `topic` and `description` (from create-form state or the saved Polis record), the org `slug`. Self-contained editable-list + generate/download UI.
- UI:
  - A "Generate seed statements" button (hidden when AI isn't configured — gate on a small capability flag from the existing public-config endpoint, or attempt-and-hide-on-503; prefer the config flag if one exists, else 503-driven hide).
  - An OPTIONAL freeform "steer" text input ("Anything to steer the statements? e.g. 'make sure pro-development and anti-development views are both represented'") — sent as `steer`.
  - An OPTIONAL "Include our organization's description for context" checkbox → sets `include_org_description`. Label it clearly so the admin knows what's being sent.
  - On generate: POST to the new endpoint; populate the editable list with returned statements; surface `warning` inline if present (non-blocking).
  - The editable list: one row per statement, each editable inline, with remove buttons and add-row. Reorder is nice-to-have (drag or up/down) — not required for v1; if it adds cost, skip it and log to backlog. Statements persist in component state across regenerations of OTHER controls but see regenerate behavior below.
  - "Regenerate" (re-run, replaces the list — warn if the list has manual edits, "Replace current statements?") and "Add more" (append a fresh batch without clearing existing) — "Add more" is the higher-value one; include at least "Regenerate". Both reuse the same endpoint.
  - "Download CSV" button: always available when the list has ≥1 non-empty statement. Client-side serialize to pol.is format with proper CSV quoting (use a tiny correct CSV-escape, or PapaParse which is already an available library — `import Papa from 'papaparse'`; `Papa.unparse({ fields: ["comment_text"], data: rows })` handles quoting). Trim, drop empties, de-dupe before serializing. Filename: `polis_seed_statements.csv`.
  - A one-line helper under the download button: "Upload this CSV in your pol.is conversation's admin page (Comments → seed)." (Plain guidance; no claim that the platform does it.)
- The list is usable with zero generations: an admin can click "add row" and type their own. Generation never blocks manual entry.

**Wiring:**
- On the **create flow** (`CreatePolis.jsx`): render `<PolisSeedGenerator topic={topic} description={description} slug={slug} />` below the form fields. Inputs come from live form state. (Note: there's no saved Polis yet — that's fine, the generator doesn't need one; it produces a file the admin uses on pol.is.)
- On the **detail page** (`PolisDetail.jsx`): render the same component, reading `topic`/`description` from the saved `polis` record. This is the "I linked it first, now generate seeds" path.

---

## Cluster C2 — Member access to Polises (Deliberations nav entry)

### Backend

- **Confirm/add a member-facing eligible-Polis-list endpoint.** The admin `Polises.jsx` uses an admin-gated list. Members need: `GET /api/orgs/{slug}/polises` (member-accessible) returning only Polises this user is eligible to see, via the existing `eligible_viewers_for_polis` logic (org-wide Polises to all members; sub-org-scoped Polises only to that sub-org's members; archived handling per existing rules). If such an endpoint already exists, reuse it. If only an admin one exists, add the member-eligibility-filtered variant. Assert the eligibility filter with a test (a sub-org-scoped Polis must NOT appear for a non-sub-org member).
- **Cheap presence check for the nav.** Either a lightweight `GET /api/orgs/{slug}/polises/has-visible` returning `{ has_visible: bool }`, or reuse the count from the list endpoint. The nav needs a boolean without fetching full Polis bodies on every render — model it on the unread-message-count hook (`useUnreadMessageCount`) which polls a cheap count.

### Frontend

- **New page or reuse:** a member-facing Deliberations list page at `/{slug}/deliberations` (or reuse the member `Polis.jsx` family). It lists the org's visible Polises (discussion topic + description preview, using the Phase 81 fallback label for bare-linked ones), each linking to the member `Polis.jsx` view. Keep it simple — a list, not an admin surface (no create/edit/archive controls).
- **Nav link (`Nav.jsx`):** add a "Deliberations" `NavLink` in the member nav row (desktop + mobile drawer), placed near Delegates/Messages. Gate its visibility on a new `useHasVisiblePolises(navOrg.slug)` hook (mirrors `useUnreadMessageCount` shape): the link renders only when `has_visible` is true. No permission gate (any member who can see a Polis can reach the list). When the org has no visible Polises, the link is absent — no dead button.
- Sub-org scope: follow the existing nav pattern for sub-org-scoped resource links (the Messages/Proposals links show the parent/sub resolution). Deliberations can be parent-org-scoped in v1 (Polises are org-or-sub-scoped; the list endpoint already filters by eligibility, so a parent-scoped list that includes the member's visible sub-org Polises is acceptable — confirm against how `eligible_viewers_for_polis` scopes and match it).

---

## Cluster C3 — Remove the disclosure modal, relocate identity mechanics

### Frontend

- **Remove `PolisDisclosureModal` as an interrupting gate.** Find its import/render sites (member `Polis.jsx`, and any wrapper in `PolisEmbed.jsx`) and remove the first-visit-per-Polis modal gate and its localStorage/state bookkeeping. Delete the component file if nothing else references it (grep first).
- **Add a quiet inline link near the embed** (in `Polis.jsx`, adjacent to or just above the `PolisEmbed`): a small, non-modal text link "How your identity works here" that links to the relevant section of `PolisHelp` (anchor) — or opens a lightweight inline expander if the team prefers no navigation. NOT a modal, NOT auto-shown. Available to those who want it.
- **Relocate the identity mechanics into `PolisHelp.jsx`** as a clear section. The copy must be accurate to the code (`get_or_create_polis_xid`):
  - You participate under a random ID, not your name, username, or profile.
  - The ID is randomly generated the first time you open a deliberation in this organization.
  - You get a DIFFERENT random ID in each organization, so your activity can't be linked across organizations.
  - The same ID is reused each time you return to deliberations in this organization, so you can pick up where you left off.
  - Your individual statements and agree/disagree votes in a deliberation are shown to other participants (attached to that random ID) — this is how the clustering visualization works. (State it plainly; it's not a warning, it's how the tool functions.)
  - Organizers with the right permission can look up who is behind an ID if needed for moderation. (Keep this — civic-trust products should make the deanonymization capability findable rather than hidden. Per Z: keep it, "if needed for moderation" is sufficient softening.)
- Do NOT add an org setting or any new gate. This cluster is pure removal + relocation.

---

## Verification matrix

No deploy-time codepaths (`start.sh`, worker, migrations) touched → no `bash start.sh` requirement. No migration → no PG-smoke cycle requirement. Standard suite +:

**C1 backend:**
1. `generate_statements` with a topic returns a non-empty list (monkeypatched `_call_anthropic` returning a known JSON array) — assert parsing + trim + de-dupe.
2. `generate_statements` with all-empty inputs returns `([], <warning>)` WITHOUT calling the API (assert the monkeypatch was not invoked).
3. `_call_anthropic` raising → `generate_statements` returns `([], <warning>)`, no exception propagates.
4. Unparseable model output ("here are some statements: ...") → `([], <warning>)`.
5. Route `POST .../seed-statements/generate` with no `ANTHROPIC_API_KEY` → 503 (assert the not-configured branch).
6. Route with `include_org_description=true` reads `Organization.description` server-side (assert the org's description text reaches `build_user_message` — monkeypatch and capture the user message; assert org desc present when flagged, absent when not).
7. Route permission: a member WITHOUT `polis.create`/`polis.edit` → 403.
8. Audit: a successful generate emits `polis.seed_statements_generated` with a count, NOT the statement text (assert no statement strings in the audit details).

**C1 frontend (browser-verify on Reform Table, ANTHROPIC_API_KEY set):**
9. Create flow: type a discussion topic, click Generate → editable list populates; edit a row, add a row, remove a row; Download CSV → file has `comment_text` header + one row per statement, commas/quotes properly escaped (test a statement containing a comma).
10. Detail page: same generator works reading the saved topic/description.
11. With AI unconfigured (or simulated 503): Generate button is hidden/disabled; the editable list still accepts manual entry; Download CSV still works on hand-typed rows.
12. CSV serializer drops empty rows and exact duplicates.

**C2:**
13. Member-eligible Polis list endpoint returns org-wide Polises to a plain member; a sub-org-scoped Polis does NOT appear for a non-sub-org member (assert eligibility filter — load-bearing).
14. Nav: in an org WITH a visible Polis, the "Deliberations" link renders for a plain member; in an org with NONE, the link is absent (no dead button). Desktop + mobile.
15. Member can navigate Deliberations list → open a Polis → participate in the embed (xid bridge still works end-to-end).

**C3:**
16. No disclosure modal appears on first visit to a Polis (assert the modal is gone, not just dismissed).
17. The "How your identity works here" link is present near the embed and reaches the PolisHelp identity section.
18. PolisHelp contains the identity-mechanics section with accurate copy (random ID, cross-org isolation, same-ID-on-return, statements-visible, moderation-deanonymization).

**Grep gates:**
- No `PolisDisclosureModal` render/import remains (the file may be deleted; assert no references).
- No new `intended_seed_statements` writes introduced by C1.

---

## Closeout must report

- C1: the load-bearing tests — #2 (no API call on empty), #3 (degrades, never 500), #6 (org description only sent when opted in, read server-side), #8 (audit doesn't log statement text). CSV-escaping browser result (#9).
- C2: #13 (sub-org eligibility filter holds — a member must not see a Polis they're not eligible for) and #14 (no dead nav button).
- C3: modal gone (#16), identity mechanics relocated and accurate (#18).
- Confirmation: NO migration, NO deploy-time codepath touched, NO revival of `intended_seed_statements` writes.
- Test-count delta; any new tech debt.

---

## Backlog (logged from this session; NOT this pass)

- **Per-conversation public-username opt-in.** A per-Polis checkbox "use my real name in this conversation" that, on opt-in, sends the user's stable handle AS the `data-xid` for that one conversation (pol.is displays the xid string, so a handle-xid shows the name; a random-token-xid stays pseudonymous). Spec-ready notes / catches: (a) it's PERMANENT for that conversation — votes/statements already cast keep that attribution in pol.is's data, no unwind; (b) use the stable `User.delegate_handle` (unique, URL-safe), NOT the mutable `display_name`, and snapshot it at opt-in so a later rename doesn't fork the participant; (c) mixed identity within one conversation is expected (some named, some random) and is fine. Needs a Z values call (permanence, harassment/chilling surface) before building. Does NOT break cross-org/cross-conversation anonymity for anything the user didn't opt into.
- **`site_id`/`page_id` auto-creation embed.** Would let an admin create a pol.is conversation without leaving the platform (the embed creates it on first render). Recon done — shelved because: conversations would be owned/moderated under the platform's single pol.is account (moderation centralization) unless each org gets its own account+`site_id` (which re-introduces per-org setup); the real `conversation_id` isn't returned server-side (would need fragile client-side `postMessage` capture before stats/export/manage links work); config is write-once-at-creation and the visualization-visibility toggle isn't in the documented attribute set (may still force a manual pol.is visit); write defaults to requiring social login (fights the pseudonymous-xid model) unless overridden. Revisit only if a pilot specifically asks to create conversations in-platform AND someone verifies free-tier embed-creation + `postMessage` conversation_id capture on a live account.
- **Reorder control in the seed-generator list**, if cut from v1 for cost.
- **`PolisHelp` pol.is-side setup checklist** (from the earlier session): turn on "Participants can see the visualization"; consider disabling the email-subscription prompt to keep participation pseudonymous; leave the experimental Invite Tree off. Belongs with the help-content/video workstream.
