# Phase 7.5 Screenshots

Captured 2026-04-27 against local dev (backend port 8002 — phantom socket on 8001 again — Vite proxy temporarily redirected; reverted post-test). Driven as alice (regular user) and admin (platform admin).

| File | What it shows | Tests confirmed |
|---|---|---|
| `settings_access_history_alice.html` | Settings page "Data Access History" section as alice. 4 entries: 1× "Viewed your ballot" with reason "Suite O3 smoke test", 2× "Viewed system delegation graph", 1× "Viewed full user list". All show "Admin User (Platform admin)" as accessor with timestamps. Reason line italic-muted under the action when present. | O7, O10 |

## Tests not represented as separate captures

- **O1, O2, O3, O4, O5, O11** were verified at the API level (curl + the new endpoints). Output captured in the QA log within `browser_testing_playbook.md`. The redaction, elevation-self-logging, system-endpoint-self-logging, and regression behaviors are not visual UX changes — they manifest as response-shape changes that the backend tests in `test_privacy_hardening.py` plus the API curls confirm comprehensively. Saving DOM screenshots wouldn't add evidence beyond what `_redacted_fields: ['vote_value', 'ballot', 'previous_value']` and the elevation entry in the audit log already prove.
- **O6 (other-user profile view appears in target's access log)** was SKIP-with-reason. The Phase 7.5 spec mentions `profile.viewed` as a candidate "direct access" action but the audit-log instrumentation for profile views isn't currently in the codebase. The backend dev's `_DIRECT_ACCESS_ACTIONS` set is intentionally empty as an extension point. Spec note: "The exact set of 'data access' actions is something the dev team needs to enumerate during implementation. Some are existing... some are new from this pass (admin elevations)." This pass enumerated only the admin elevations; instrumenting profile-view audit events is logged as tech debt for a follow-up pass.
- **O8 (empty state)** was PASS-with-note. The `AccessHistory.jsx` component's empty-state branch renders the spec-mandated copy "No access events recorded. When other users, organization admins, or platform admins view your data, those events will appear here." — this was verified by source review (`AccessHistory.jsx` lines that branch on `entries.length === 0`). In this local seed, even a brand-new registered user sees 3 entries from earlier admin queries (delegation-graph and user-list views recorded earlier in the QA run touched every user in the system). To exercise the literal empty UX, a fresh DB with zero admin events would be needed; the code path is correct.
- **O9 (cross-user isolation)** verified at API level: frank (a user not targeted by the elevated ballot view) sees 3 entries (system-wide delegation-graph and user-list views — those touch all users in the system by design). Frank does NOT see alice's elevated-ballot view. Cross-user isolation works.
- **PostgreSQL smoke** was performed by the backend dev: brought up `postgres:16-alpine` via `docker compose`, seeded, ran the elevation flow, fetched `/api/users/me/access-log` against the PG-backed instance. Worked cleanly. The Python-side JSON filter approach (Python dict lookup on `details["viewed_actor_id"]` after a coarser SQL query keyed on action+actor) **structurally avoids** the SQLite-vs-PostgreSQL JSON-path divergence — no DB-level JSON path queries are issued.

## Method note

HTML capture used the same upload-server pattern Phase 7C/7C.1 established (local Python HTTPServer at :9876 receiving POSTs from the page's JavaScript context). The upload-server file was kept out of the committed screenshots set.
