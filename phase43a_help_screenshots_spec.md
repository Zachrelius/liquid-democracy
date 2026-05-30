# Phase 43a — Help-Page Screenshots

**Status:** Ready to build. Small content + frontend follow-on to Phase 43. Fills the `ScreenshotPlaceholder`s left in the three getting-started help pages with real captioned screenshots from the Cedar Hollow demo. Merged dispatch + spec doc.

**Branch:** `phase-43a/help-screenshots` → `--no-ff` merge to master at close.

---

## Dispatch framing

### Goal

Phase 43 shipped the three "getting started" help pages (member / steward / delegate) with `ScreenshotPlaceholder` components standing in for real images. This pass captures those screenshots against the **Cedar Hollow demo org**, stores them as static assets, and replaces each placeholder with the real image plus its caption. This is the visual half of the help content — the thing Z specifically wants to review on the live pages is whether each screenshot and its surrounding copy back each other up, so accuracy of *what's shown* matters more than polish.

### Branch + merge

- Branch: `phase-43a/help-screenshots`.
- `git merge --no-ff` to master at close; push to origin; Railway auto-deploys.

### Verification matrix

| Check | Required | Notes |
|---|---|---|
| Frontend build (`npm run build`) | Yes | Must pass clean before merge. |
| Backend pytest | No | No backend touch. State "backend untouched, baseline unchanged" in closeout. |
| PG smoke | No | No migration. |
| Browser verification (Chrome MCP, prod) | Yes | After deploy: load all three help pages on prod, confirm every image renders (no broken-image icon), each image sits under the correct paragraph, and each visibly matches its caption. |
| Bundle hash changed post-deploy | Yes | Confirm new hash in closeout. |
| Image weight sanity | Yes | Each screenshot reasonably sized (target ≤ ~300 KB each; PNG or WebP). Total added assets noted in closeout. |

### Exact screenshots to capture

There are **5** `ScreenshotPlaceholder` components across the three pages. Capture one image per placeholder. **The `caption` prop on each placeholder is the authoritative description of what the shot must show** — capture to match it exactly. Current placeholders:

**`GettingStartedMember.jsx` (3):**
1. "The Proposals list in Cedar Hollow showing the All/Deliberation/Voting/Passed/Failed filter row and proposal cards with vote tallies and time remaining." → `/demo-cedar-hollow/proposals`
2. "A single proposal detail in the Voting stage showing the Approve / Reject / Abstain buttons and the Submit Vote button." → open a Cedar Hollow proposal that is in the **Voting** stage; scroll to the vote-cast controls.
3. "The Browse Delegates page showing delegate cards (bio, topic tags, delegator count, View Profile)." → `/demo-cedar-hollow/delegates`

**`GettingStartedSteward.jsx` (1):**
4. "The Admin dropdown menu open, showing Org Settings, Permissions, Members, Proposals, Topics, etc." → as an admin persona, open the **Admin** dropdown in the top nav and capture it open.

**`GettingStartedDelegate.jsx` (1):**
5. "The 'My Delegate Page' editing view for a delegate, showing the intro/profile area and the per-topic sections." → `/demo-cedar-hollow/delegate-profile`.

**Capture conditions:**
- Sign in via the **demo persona flow** at `/demo` (Cedar Hollow → "Sign in as" a persona). Use **Janet Reilly** (Cedar Hollow admin + has a populated delegate page) for shots 2–5; any signed-in persona works for shots 1 and 3. Do NOT use real account credentials.
- Capture at a standard desktop viewport (~1280–1512 px wide). Crop to the relevant UI region where it tightens the shot (e.g. the Admin dropdown shot should center the open menu, not the whole empty page). Full-width is fine for the list/table shots.
- Demo content resets daily; exact proposal titles may differ from any example — match the **caption's described UI**, not specific row text.

### Suggested team structure

Tiny. **Lead + one frontend/QA dev.** The same person can capture, wire, and verify.

### Sequence

1. Capture the 5 screenshots from the Cedar Hollow demo per the list above.
2. Optimize/resize; place under `frontend/public/help-screenshots/` with clear filenames (e.g. `member-proposals-list.png`, `member-vote-cast.png`, `member-browse-delegates.png`, `steward-admin-menu.png`, `delegate-my-delegate-page.png`).
3. Replace each `ScreenshotPlaceholder` with a real image element (see wiring note). Keep the caption text identical.
4. `npm run build`; merge; deploy.
5. Prod QA: load all three pages, verify per the matrix.

### Load-bearing decisions

- **Screenshots come from the Cedar Hollow demo only** — it's the one live demo org and contains no real user data.
- **Captions are not rewritten.** The existing caption text stays; this pass only swaps the placeholder box for an image + that same caption.
- **Promote `ScreenshotPlaceholder` into a real captioned-image component** rather than scattering raw `<img>` tags. Replace the placeholder definition (currently in each page, or factor a shared `components/HelpScreenshot.jsx`) with one that renders `<figure><img …/><figcaption>{caption}</figcaption></figure>`, styled to match the existing help-page card aesthetic (rounded border, subtle frame, small muted caption). A shared component keeps all three pages consistent and makes future screenshot refreshes a one-file change.

### Operational watch-outs

- **Alt text:** give each `<img>` an `alt` equal to (or derived from) its caption for accessibility.
- **Lazy-load** images (`loading="lazy"`) so the help pages stay light.
- **File size:** these are UI screenshots, not photos — PNG or WebP, compressed. Avoid multi-MB images.
- **Don't touch the help copy or any Phase 43 logic** — this pass is images only.
- The demo may show a different proposal set than earlier captures referenced; that's expected (daily reset). Capture whatever currently satisfies each caption.

### Closeout reporting

Per CLAUDE.md closeout shape: per-shot status (5 captured + wired), files added (image assets + any component), build result, bundle hash, prod deploy status, and the prod QA result confirming each image renders and matches its caption. Note backend untouched / no migration.

---

## Spec body

### What IS in scope
Capturing the 5 help-page screenshots from the Cedar Hollow demo, storing them as optimized static assets, promoting `ScreenshotPlaceholder` to a real captioned-image component, wiring all 5 in with unchanged captions + alt text + lazy-load, and deploying.

### What is NOT in scope
Rewriting any help copy or captions; adding screenshots beyond the 5 existing placeholders; capturing from any org other than the Cedar Hollow demo; any backend or Phase 43 logic change; mobile-specific screenshot variants.

### Followups
- If Z's live review finds a screenshot and its copy don't reinforce each other, that's a caption/copy adjustment handled as a trivial follow-on (or folded into a later help pass) — flag any such mismatches in the closeout for planning-agent review.
