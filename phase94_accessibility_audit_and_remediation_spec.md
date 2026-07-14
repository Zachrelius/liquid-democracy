# Phase 94 — Accessibility Audit and Remediation

## Dispatch

### Goal

Reduce pilot risk by auditing and remediating accessibility barriers in the platform's load-bearing journeys. WCAG 2.2 AA is the working engineering target, not a claim of formal conformance or certification.

### Branch and delivery

- Branch: `phase-94/accessibility-audit`
- Merge: `--no-ff` into `master`
- Deploy: push `master`, wait for Railway, then verify the production bundle and backend health
- Migration: none anticipated; PostgreSQL migration smoke is not required unless scope changes

### Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Registration, sign-in, and create-organization forms have programmatic labels and associated errors | Yes | Browser snapshot plus keyboard use |
| Proposal creation and core admin controls are keyboard operable | Yes | Include visible focus and error handling |
| Voting controls have accessible names, states, and instructions | Yes | Exercise representative binary, ranked, approval, and budget surfaces where present |
| Ranked/ordered interactions have a non-pointer path | Yes | Preserve drag-and-drop where useful |
| Dialogs manage initial focus, Escape, containment, and focus restoration | Yes | Test representative shared dialog implementation |
| Status and validation messages are announced appropriately | Yes | Use live regions only where the state changes dynamically |
| Informational charts expose an equivalent text or table representation | Yes | Scope to pilot-critical charts found in the audit |
| Critical controls remain usable at mobile widths and have adequate targets | Yes | Prioritize ballot and admin controls |
| Color and focus contrast checked on critical surfaces | Yes | Automated/static checks plus manual browser inspection |
| Frontend regression tests pass | Yes | Add tests for corrected semantics and keyboard behavior |
| Frontend production build passes | Yes | Required before merge |
| Backend tests | If touched | No backend behavior change is expected |
| Local browser QA | Yes | Use isolated/local data; do not mutate production |
| Production browser sanity | Yes | Read-only where practical after deploy |

### Team structure

Single full-stack Codex pass. The work is deliberately bounded and does not require the planned hands-on onboarding walkthrough or a new example organization.

### Sequence

1. Inventory pilot-critical surfaces and run static/automated checks available in the repository.
2. Browser-audit accessible names, keyboard order, focus behavior, error announcements, and mobile usability.
3. Fix the highest-severity barriers using shared components where possible.
4. Add focused regression tests and run the frontend suite/build.
5. Browser-verify locally, merge, deploy, and run production sanity.

### Load-bearing decisions

- Do not make a formal accessibility-conformance claim in product copy or closeout.
- Prefer native HTML semantics and programmatic labels over ARIA patches.
- Preserve pointer/drag interactions when useful, but provide an equivalent keyboard/non-drag operation.
- Charts need an equivalent way to obtain the information; every visual mark does not need to become an interactive control.
- Correct shared primitives before patching individual screens when the regression risk is reasonable.
- This pass must not add paid services or recurring cost.

### Operational watch-outs

- Preserve existing user-owned dirty-worktree changes.
- Avoid destructive or state-changing production QA.
- Treat automated accessibility results as a floor, not proof of conformance.
- If remediation expands into a major visual redesign, record it as follow-up rather than broadening this pass silently.

### Closeout reporting

- Findings grouped by severity, including what was fixed and what remains
- Tests/build/browser verification performed
- Files changed and commits
- Explicit statement that no migration was added, if unchanged
- Railway deployment identifiers, production bundle hash, and sanity result

---

## Status

**IN PROGRESS — 2026-07-14**

## What this phase is

A focused audit and remediation pass for barriers that could prevent a prospective pilot member or administrator from creating an account, configuring an organization, creating or understanding a proposal, voting, delegating, or reading results.

## What this phase is not

- A third-party accessibility certification
- A guarantee that every historical or low-traffic screen meets every WCAG success criterion
- A broad brand or visual redesign
- The guided-onboarding walkthrough with the owner's new example organization; that is a separate, explicitly deferred exercise

## Workstreams

### A — Inventory and evidence

- Map critical routes to shared components and identify missing names, labels, roles, states, and descriptions.
- Check focus visibility, keyboard reachability, reading order, and mobile target usability.
- Record remaining lower-priority findings rather than losing them.

### B — Forms, validation, and status

- Associate visible labels and help/error text with their controls.
- Ensure invalid state and asynchronous success/failure messages are exposed to assistive technology.
- Remove placeholder-only naming on critical forms.

### C — Keyboard and focus

- Correct shared dialog focus management.
- Ensure menus, tabs, filters, ballots, and admin actions can be operated without a pointer.
- Add a non-drag operation for any load-bearing ordered choice interaction that lacks one.

### D — Results, visualization, and mobile

- Add equivalent text/table access for pilot-critical charts where absent.
- Correct severe contrast, focus-obscuring, or target-size problems found on critical routes.

### E — Regression coverage and QA

- Add focused semantic/keyboard regression tests.
- Run frontend tests, lint where actionable, and production build.
- Browser-verify critical flows locally and perform production sanity after deployment.

## Follow-ups

- Run the separate guided-onboarding walkthrough with the owner's new example organization when the owner has time.
- Consider a later independent/manual audit with assistive-technology users before making any public conformance claim.

## Audit findings and remediation log

### High — visible labels were not programmatic labels

Confirmed across sign-in/registration, first-run setup, later organization creation, proposal creation, and organization settings. Screen readers often received a placeholder or no name even though a label was visible. Fixed critical forms with stable `id`/`htmlFor` associations, fieldset/legend groups, associated help/error text, autocomplete hints, and named proposal filters. A live browser control-name sweep found no unnamed visible inputs/selects/textareas on the audited steward-settings page after remediation.

### High — modal keyboard containment and focus restoration were incomplete

The shared confirm dialog only cycled between two buttons, omitted checkbox controls, globally treated Enter as confirmation, had no dialog semantics, and did not restore focus. Delegate/report dialogs had similar gaps. Added one shared modal-focus hook with Escape, dynamic focus containment, initial focus, and opener restoration; added dialog labelling/description semantics. Browser verification confirmed Shift+Tab containment and restoration to both Archive Proposal and Set Default Delegate launchers.

### High — ordered decisions still depended on drag for reordering

Ranked ballots could add/remove by button but needed drag to change order. Delegation precedence also advertised drag as the operation. Added named, adequately sized up/down controls for ranked ballots, project-budget ballots, proposal option editing, and delegation precedence while preserving drag. Browser verification built South > North using only Rank and arrow buttons at 380px.

### High — ranked drag markup produced nested interactive controls

The drag handle props were attached to the entire ranked option row, turning it into a button containing Rank/remove buttons. Moved drag semantics to a dedicated named handle; the post-fix browser DOM sweep found no nested interactive controls or unnamed controls on the active ranked ballot.

### Medium — dynamic feedback was not consistently announced

Added alert/status semantics to shared errors, toasts, setup failures/successes, and proposal-create errors. The notification bell now exposes expanded state, has a distinct name from the full Notifications link, closes on Escape, and returns focus.

### Medium — topic colors and branded accent text could miss contrast

Topic badges always used white text, producing measured ratios as low as 2.15:1 for configured colors. They now choose black or white for the stronger contrast; the four local topic colors measured 4.70:1–9.78:1 after remediation. Accent-colored normal text now uses a hue-preserving contrast-safe companion variable rather than the raw accent, including custom org themes.

### Medium — keyboard focus visibility depended on individual components

Added a global 3px focus-visible outline fallback. Browser verification observed the outline on registration controls even where component styles suppress the default browser outline.

### Equivalent visualization access

The audited ranked-vote page exposes the same decision information outside its D3/Sankey visuals: ballot totals, current winner, the user's ordered ballot, and a textual round-by-round result with elected/eliminated counts. The trajectory chart also exposes a named no-data state. Direct keyboard manipulation of decorative graph nodes is therefore not required for information access in this pass.

## Known residual accessibility work

- Run NVDA/JAWS/VoiceOver sessions and Firefox/Safari keyboard passes; this phase's browser verification is Chromium-based.
- Custom **primary** brand colors are still allowed without enforcing white-on-primary contrast. Accent text is now protected, but a later branding pass should preview or automatically select on-primary foreground colors before very light primary themes are used.
- Continue converting low-traffic historical forms and bespoke popovers outside the pilot-critical route set as they are revisited.
- A third-party/manual audit with disabled users remains the right gate before any formal conformance claim.
