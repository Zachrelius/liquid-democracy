# Phase 81 — Polis: link-existing-conversation simplification

**One-line dispatch:** `Read and execute phase81_polis_link_simplification_2026-06-28.md`

**Team:** continuing-dev (Polis subsystem context wins here).

**Type:** Single-deploy. Frontend-heavy, one small backend schema/validation change, no migration. Does NOT trip the Greater-Phase threshold (no new infrastructure, no migration, <50 new tests).

---

## Why this pass

Z tested the live Polis "integration" while evaluating it for the Reform Table pilot and found it is mostly theater. With no `POLIS_AUTH_TOKEN` configured (the current and only production state), the create flow runs the manual-fallback path: the operator does ALL the real work on pol.is anyway (sign in, create the conversation, configure it, paste seed statements), and our platform's "Create a Polis" form contributes nothing to creation. It stores a title, a prompt, and a copy of the seed statements whose only function is to be copied back out into pol.is by hand.

On top of that, the flow is actively misleading and broken in two specific ways:

1. The `pol.is/admin` link 404s. Pol.is has no `/admin` namespace. The real flow is: sign in at `pol.is/signin`, create a conversation (lives at `pol.is/<id>`), admin console at `pol.is/m/<id>`. This wrong URL appears in two places.
2. The "Manual-fallback mode" framing throughout the UI presents the current state as a temporary degraded mode awaiting fuller integration, when in practice link-existing IS the model.

**Decision (Z):** Strip the creation theater. Convert to an honest **link-an-existing-pol.is-conversation** flow. Keep everything that genuinely adds value over a bare proposal-body link: the scoped embed, the per-(user,org) pseudonymous `xid` identity bridge, proposal linking, the disclosure modal, and export. Drop the seed-statement data entry entirely (it was pure copy-paste waste). Relabel `title`/`prompt` to **Discussion topic** / **Description** to match pol.is's own vocabulary, while keeping the DB columns named `title`/`prompt` (no migration, no collision with the first-class `Topic` entity). Make topic + description optional so a bare link works.

**Out of scope (do not touch):** the backend `programmatic_path` dispatch, the `polis_auth_token` branches in the route, `polis_service.py`, the `intended_seed_statements` DB column. These stay for a future Phase 69 programmatic-wiring pass. This pass collapses the *frontend* dual-path rendering only.

---

## Decisions locked (do not re-litigate)

- **D1 — Drop seed statements (UI only).** Remove all seed-statement entry and display from the frontend. The `intended_seed_statements` DB column is intentionally RETAINED but unwritten by the new create flow (Phase 69 will want it back; a migration to drop it buys nothing a user sees and touches the live `polises` table with demo rows). Leave a code comment so a future agent doesn't read its absence-from-UI as dead-code-to-clean.
- **D2 — Link-existing create flow.** `polis_conversation_id` is the only required field. Discussion topic and Description are optional.
- **D3 — Relabel at the UI layer only.** "Title" → "Discussion topic"; "Prompt" → "Description". DB columns `title`/`prompt` and all backend symbols stay as-is. The label is "Discussion topic" (not bare "Topic") specifically to avoid collision with the user-facing first-class `Topic` entity.
- **D4 — Empty-topic fallback label, same everywhere:** `Linked pol.is conversation <conversation_id>` (e.g. `Linked pol.is conversation 3jrhnuhnjs`). Used wherever the discussion topic is empty, for both member and admin surfaces.
- **D5 — Fix the 404:** `https://pol.is/admin` → `https://pol.is/signin` in both occurrences.
- **D6 — Strip "Manual-fallback mode" framing** from the frontend. Collapse the dual-path JSX to the single real path. Backend response field `programmatic_path` and the token-configured branches stay (Phase 69).
- **D7 — No migration.** `Polis.title` (`String NOT NULL`) and `Polis.prompt` (`Text NOT NULL`) keep their non-null columns; the create path stores empty string `""` when the optional fields are omitted. `PolisOut.title`/`prompt` typed `str` serialize `""` fine; the frontend fallback (D4) handles display.

---

## Grounding (verified against source this pass)

Files read and confirmed:
- `frontend/src/pages/admin/CreatePolis.jsx` — the dual-path create form + `SuccessPanel`. Has the `pol.is/admin` 404 (banner + success panel), the seed-statement entry UI, the "Manual-fallback mode" amber banner, the `tokenConfigured` branch.
- `frontend/src/pages/admin/PolisDetail.jsx` — header renders `polis.title` + `polis.prompt` directly; breadcrumb shows `{polis.title}`; has the bottom "Intended seed statements" section; "Manual-fallback mode" copy on archive + export.
- `frontend/src/pages/admin/Polises.jsx` — list page; column header literal `Title`; rows render `{p.title}`.
- `frontend/src/pages/Polis.jsx` — voter-facing; header renders `polis.title` + `polis.prompt`; read-only banner copy references "title and prompt".
- `frontend/src/components/LinkedPolisCard.jsx` — voter-facing card on proposal detail; renders `polis.title` (no fallback) + conditionally `truncatedPrompt`.
- `backend/routes/polises.py` — `create_polis` dual-path; `_polis_to_out`; `update_polis` (one-shot connect already wired).
- `backend/schemas.py` — `PolisCreate` (title/prompt `min_length=1`, required), `PolisUpdate`, `PolisOut`, `PolisCreateResponse`.
- `backend/models.py` — `Polis.title` `String NOT NULL`; `Polis.prompt` `Text NOT NULL`; `intended_seed_statements` `JSON nullable`.

**Confirmed:** `update_polis` already accepts `polis_conversation_id` for one-shot connect and already accepts `title`. There is NO existing way to set `prompt` via PATCH — not needed for this pass (topic/description are set at create time only; editing description post-create is out of scope and noted in Backlog).

---

## Backend changes

### B1 — `schemas.PolisCreate`: make topic + description optional

Current:
```python
class PolisCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    prompt: str = Field(min_length=1, max_length=10000)
    sub_org_id: Optional[str] = None
    seed_statements: list[str] = Field(default_factory=list, max_length=200)
    polis_conversation_id: Optional[str] = Field(default=None, min_length=1, max_length=300)
```

Change to:
- `title` → optional, default `""`, drop `min_length`, keep `max_length=500`. (We accept the operator omitting the discussion topic.)
- `prompt` → optional, default `""`, drop `min_length`, keep `max_length=10000`.
- `seed_statements` → KEEP the field on the schema (back-compat: a Phase-69 programmatic caller or an in-flight client may still send it; the route still reads it for the programmatic path which is untouched). It is simply no longer sent by the new frontend. Do NOT remove it.
- `polis_conversation_id` → unchanged shape, but see B2 for the required-ness logic (it's required in the manual path, which is now the only frontend path).

Add a normalizer so whitespace-only topic/description collapse to `""` (keeps the empty-fallback logic simple downstream):
```python
    @field_validator("title", "prompt")
    @classmethod
    def _blank_to_empty(cls, v: Optional[str]) -> str:
        return (v or "").strip()
```

Update the class docstring: remove the "manual-fallback renders intended_seed_statements for paste-these-in UX" framing; replace with a short note that the frontend now links an existing conversation (conversation_id required; topic/description optional) and that the seed_statements field is retained for back-compat / future programmatic use only.

### B2 — `routes/polises.py` `create_polis`: no behavioral change required, verify the manual path

The manual-fallback branch already requires `polis_conversation_id` and 400s without it:
```python
    else:
        if not body.polis_conversation_id:
            raise HTTPException(status_code=400, detail="polis_conversation_id is required ...")
        polis_conversation_id = body.polis_conversation_id
```
This is correct and stays. With B1, `body.title`/`body.prompt` may now be `""`; the `models.Polis(... title=body.title, prompt=body.prompt ...)` construction stores `""` which satisfies the NOT NULL columns. **No change needed to the row construction.** Verify (test) that a create with empty title/prompt + a conversation_id succeeds and persists `title=""`, `prompt=""`.

Leave the `intended_seed_statements=seed_statements or None` line as-is (the new frontend sends `[]`, so this stores `None` — fine).

The 400 detail string still reads "manual-fallback flow". Soften it (it's operator-facing on an error): change to something like `"polis_conversation_id is required. Create the conversation on pol.is first, then paste its conversation_id."` Drop the "manual-fallback" term.

### B3 — leave `PolisOut`, `PolisCreateResponse`, `PolisUpdate` unchanged

`PolisOut.title`/`prompt` stay typed `str` (empty string serializes fine). `PolisCreateResponse.programmatic_path` + `manual_seed_statements_required` stay (Phase 69). No migration.

---

## Frontend changes

### F1 — `CreatePolis.jsx`: convert to link-existing flow

This is the largest change. The component currently branches heavily on `tokenConfigured`. Collapse to the single link-existing path.

**Form fields (the create form):**
- **Remove** the entire seed-statement block: `seedStatements` state, `updateSeed`/`addSeed`/`removeSeed`, the rendered statement inputs, the `+ Add statement` button, the `seedWarning`/`trimmedSeeds` logic, and the "Seed statements" label + helper text.
- **Relabel** the "Title" field label → **"Discussion topic"**. Make it NOT `required` (optional). Add helper text: `Optional. A one-line headline for this conversation (matches the "Topic" field on pol.is).`
- **Relabel** the "Prompt" field label → **"Description"**. Make it NOT `required` (optional). Keep the existing helper text idea but reword: `Optional. A short description of what this conversation is exploring (matches the "Description" field on pol.is).`
- **`conversation_id` field:** this becomes the primary required field and is ALWAYS shown (not gated on `!tokenConfigured`). Relabel/keep label `conversation_id (from pol.is)`. Keep the helper text about pasting the slug, but fix the URL (see F-shared below) and reword to drop "manual-fallback": `Required. Create the conversation on pol.is, then paste its conversation_id here (looks like 3jrhnuhnjs or similar).`
- Keep the scope (sub-org) selector and the sub-org locked-scope banner exactly as-is.

**Submit logic (`handleSubmit`):**
- Required validation becomes: `conversation_id` non-empty. Title/prompt are no longer required — remove the `if (!title.trim() || !prompt.trim())` guard.
- Payload: always send `polis_conversation_id: pastedConversationId.trim()`. Send `title: title.trim()` and `prompt: prompt.trim()` (may be empty strings — backend accepts). Do NOT send `seed_statements` (or send `[]`; backend defaults it). Keep `sub_org_id` when scoped.
- Remove the `tokenConfigured` branch entirely from submit.
- Submit button `disabled` condition becomes: `submitting || !pastedConversationId.trim()` (no longer gated on title/prompt).

**The amber "Manual-fallback mode" banner at the top of the form:** remove it entirely. Optionally replace with a single neutral one-liner under the page subhead, e.g. `Link an existing pol.is conversation to this org.` (no amber, no "fallback" language). Keep it minimal.

**`SuccessPanel`:**
- The component currently branches on `programmatic`. Since the frontend now only ever drives the manual path, **collapse to the manual success state** but strip the seed-statement and fallback framing:
  - Remove the `programmatic` branch's JSX (the green "created on pol.is, seeds inserted server-side" panel + `partialFailures` rendering). The `programmatic_path` response field still exists; the frontend simply no longer needs a separate render for it. (If you want belt-and-suspenders, you may keep a tiny guarded fallback, but it's dead in practice — prefer removing it for clarity per D6.)
  - In the remaining success panel: remove **step 2 "Add these seed statements"** entirely (the `seeds` list, `copyOne`, `copyAll`). The conversation already exists on pol.is with its own statements; we're just linking it.
  - Since `conversation_id` is now always supplied at create time (it's required on the form), the post-create "Paste conversation_id" input in the success panel is **dead** — remove it (`handleSaveConversationId`, the input, the `!polis.polis_conversation_id` guard). The conversation_id is always set by the time we reach success.
  - Simplify the success copy to confirm the link succeeded and offer "Go to Polis →". Something like: heading `Linked` / body `<topic-or-fallback> is now linked to your org. Members can participate in the embedded conversation.` Drop the two-step "finish on pol.is" framing.

**Title-display fallback in success:** where the panel shows `polis.title`, apply the D4 fallback (see F-shared).

### F2 — `PolisDetail.jsx` (admin)

- **Header:** `polis.title` is rendered as the `<h1>` and in the breadcrumb (`{polis.title}`). Apply the D4 fallback in both spots (see F-shared helper).
- **Description:** `polis.prompt` renders below the header. It can now be empty — wrap it so an empty prompt renders nothing (no empty `<p>`): `{polis.prompt && <p ...>{polis.prompt}</p>}`.
- **Edit title:** the inline title editor PATCHes `{title: titleDraft}`. Keep it, but relabel the affordance from "Edit title" → **"Edit discussion topic"**. The PATCH still sends `title` (backend column unchanged). The empty-string case: allow saving an empty topic (don't force non-empty); the fallback handles display. NOTE: `PolisUpdate.title` currently has `min_length=1` — see F-backend-note below.
- **"Intended seed statements" section** (the bottom `{Array.isArray(polis.intended_seed_statements) && ...}` block): **remove it entirely.** New polises won't have seeds; the section is obsolete. (Old polises created before this pass may still carry `intended_seed_statements` data, but per D1 we're done surfacing it — the conversation lives on pol.is now.)
- **"Manual-fallback mode" copy:** remove the token-conditional amber lines on archive (`!publicConfig.polis_token_configured && ...`) and on export (the "Export requires a configured pol.is API token..." note). Replace the archive note with an unconditional reminder that closing on pol.is is a separate manual step: `Archiving here marks the platform record archived. To stop participation, also close the conversation on pol.is.` Keep the export 503 behavior as-is server-side, but the frontend note can simply say export pulls from pol.is and requires the conversation to be reachable. Keep it short; drop "manual-fallback".
- The `polisManageUrl` ("Manage on pol.is →", built as `https://pol.is/${conversationId}`) is CORRECT (that's the real conversation URL) — leave it.

### F3 — `Polis.jsx` (voter-facing)

- **Header:** `polis.title` → apply D4 fallback. `polis.prompt` → guard empty (`{polis.prompt && <p>...</p>}`).
- **Read-only banner copy** that says "you can read but not participate" and the "Conversation hidden" placeholder that says "You can see the title and prompt but not the conversation itself" — reword "title and prompt" → "discussion topic and description" for consistency. Minor.
- No logic changes beyond display.

### F4 — `Polises.jsx` (admin list)

- **Column header** literal `<span className="col-span-4">Title</span>` → **`Discussion topic`**.
- **Row cell** `{p.title}` → apply D4 fallback.
- Page heading "Polises" and subhead "Pol.is deliberations linked to ..." — LEAVE as-is (not part of the topic-word collision; renaming is scope creep Z didn't ask for).

### F5 — `LinkedPolisCard.jsx` (voter-facing card on proposal detail)

- `<h3>{polis.title}</h3>` → apply D4 fallback (this card currently has NO fallback, so a bare-linked polis would render an empty heading without it).
- `truncatedPrompt` already guards empty (`{truncatedPrompt && ...}`) — no change needed.

### F-shared — the D4 fallback helper + the 404 fix

**Fallback helper.** Add a tiny shared helper rather than duplicating the ternary five times. Suggested location: `frontend/src/utils/polis.js` (new file) or co-locate in an existing utils module the team prefers. Shape:
```js
// Display label for a Polis discussion topic, with a stable fallback when
// the operator linked a bare conversation without entering a topic.
export function polisTopicLabel(polis) {
  const t = (polis?.title || '').trim();
  if (t) return t;
  const cid = (polis?.polis_conversation_id || '').trim();
  return cid ? `Linked pol.is conversation ${cid}` : 'Linked pol.is conversation';
}
```
Use it in: `CreatePolis` success panel, `PolisDetail` header + breadcrumb, `Polis.jsx` header, `Polises.jsx` row cell, `LinkedPolisCard` heading. (The trailing-fallback-with-no-cid case (`'Linked pol.is conversation'`) only happens transiently if a polis somehow has neither; harmless.)

**The `pol.is/admin` 404 fix (D5).** Replace `https://pol.is/admin` with `https://pol.is/signin` in BOTH occurrences in `CreatePolis.jsx` (the form-top banner if any remnant references it, and the success-panel step-1 link). Grep the whole `frontend/src` for `pol.is/admin` to be sure none survive elsewhere. The link text should read naturally, e.g. "Create the conversation on pol.is" linking to `https://pol.is/signin`.

### F-backend-note — `PolisUpdate.title` min_length

`PolisUpdate.title` is `Field(default=None, min_length=1, max_length=500)`. If F2 allows saving an empty discussion topic via the inline editor, an empty string would 422. Two clean options:
- **(preferred)** In `PolisDetail.jsx`, when the title draft is empty, send `title: ""`... but that 422s. So instead: drop `min_length=1` from `PolisUpdate.title` (allow clearing the topic back to empty; the fallback handles display). This is consistent with making topic optional at create. Add the same `_blank_to_empty`-style strip if desired.
- (alternative) Keep `min_length=1` and have the frontend disable "Save" on empty. Less consistent with "topic is optional" — prefer the first option.

Go with dropping `min_length=1` on `PolisUpdate.title` so the optional-topic model is consistent across create and edit.

---

## Verification matrix

No deploy-time codepaths (`start.sh`, worker, migrations) are touched, so no `bash start.sh` requirement this pass. Standard suite + the new assertions below.

**Backend (assert side effects on rows, not just status codes):**
1. `create_polis` with `polis_conversation_id` set and **no** title/prompt → 201; assert the persisted `Polis` row has `title == ""`, `prompt == ""`, `polis_conversation_id == <slug>`, `intended_seed_statements is None`.
2. `create_polis` with topic + description + conversation_id → 201; assert row stores the trimmed values.
3. `create_polis` with whitespace-only title/prompt → 201; assert stored as `""` (the `_blank_to_empty` validator).
4. `create_polis` with **no** `polis_conversation_id` (token unconfigured path) → 400 with the reworded detail (no "manual-fallback" substring).
5. `create_polis` still accepts a `seed_statements` payload without error (back-compat): 201, and (token unset) the row stores them in `intended_seed_statements` exactly as before — **this proves we didn't break the retained field / Phase 69 path.**
6. `PolisUpdate` with `title: ""` → 200; assert row `title == ""` (proves the `min_length` drop).
7. `PolisOut` serialization of a `title=""` row → `title` is `""` (not an error).
8. Existing-org parity: a polis created BEFORE this pass (with non-empty title/prompt/seeds) still serializes and renders — no regression. (Reuse the Phase 48 B0 parity helper if convenient; this is a read-path check.)

**Frontend (browser-verify on the Reform Table org, token unset = prod state):**
9. Create flow: paste a conversation_id, leave topic + description blank, submit → success; the detail page header shows `Linked pol.is conversation <slug>`; the embed renders the conversation.
10. Create flow with a topic + description → detail header shows the topic; description renders.
11. No seed-statement UI anywhere in the create form or success panel.
12. No "Manual-fallback mode" string anywhere in the Polis surfaces (grep the built bundle or the source).
13. The pol.is link in the create flow goes to `pol.is/signin` and does not 404.
14. `LinkedPolisCard` on a proposal that links a bare (no-topic) polis shows the fallback label, not an empty heading.
15. Admin list column header reads "Discussion topic"; a bare-linked polis row shows the fallback label.
16. Edit discussion topic → clear it to empty → save → 200, header falls back to the linked-conversation label.

**Grep gates (must return zero in `frontend/src` after the pass):**
- `pol.is/admin`
- `Manual-fallback` / `manual-fallback` / `manual_fallback` (in user-facing copy; the backend code comments referencing the historical term may stay, but no UI string)
- `Seed statement` / `seed_statements` in the create/detail JSX (the component-level seed UI should be gone; backend references stay)

---

## Closeout must report

- The 8 backend row-level assertions passed (esp. #1, #5, #6 — the load-bearing ones: empty-topic create persists `""`; retained seed field still works for back-compat; title can be cleared).
- Browser-verification results for #9–#16 on the Reform Table org with token unset.
- Grep gates returned zero.
- Confirmation that NO migration was created and NO deploy-time codepath was touched.
- Test-count delta.
- Any new tech debt for the backlog.

---

## Backlog (not this pass)

- **Editing a Description post-create.** This pass lets you set description at create time and edit the discussion *topic* inline, but there's no PATCH path for `prompt`. If pilots want to edit descriptions after linking, add `prompt` to `PolisUpdate` + an inline editor in `PolisDetail`. Small follow-up; deferred until a pilot asks.
- **Phase 69 programmatic wiring** remains the home for any real pol.is API integration (token, server-side conversation creation, seed insertion). The retained `intended_seed_statements` column + `programmatic_path` response field + token branches are the seams it will use.
- **`PolisHelp.jsx` + onboarding video:** a short pol.is-side setup checklist (turn on "Participants can see the visualization"; consider disabling the email-subscription prompt to keep participation pseudonymous; leave the experimental Invite Tree off so it doesn't impose a second access model on top of org scoping). Belongs in the help-content / video workstream, not here.
