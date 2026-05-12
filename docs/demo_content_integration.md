# Demo Content Integration Reference

How the demo bibles at `backend/demo_content/` flow into the database via the seed pipeline. For the demo content agent and future contributors editing bible content.

**Pass that shipped this:** Phase 23 (2026-05-12). See `phase23_demo_daily_reset_spec.md` + `phase23_amendments_2026-05-12.md` + `docs/demo/handoff_stage8.md`.

## Files involved

```
backend/demo_content/
├── schema.py                         # All dataclass shapes — single source of truth
├── hoa_bible.py                      # HOA_BIBLE (Cedar Hollow HOA)
├── union_bible.py                    # LOCAL_4021_BIBLE (AFSCME Local 4021)
├── activist_bible_part1.py           # COALITION members + part of delegate_pages
├── activist_bible_part2.py           # COALITION proposals + drafts
├── activist_bible_part3.py           # COALITION_BIBLE — assembles parts 1+2
├── trajectory_waypoints.py           # Per-proposal Trajectory data keyed by proposal_id
├── name_pool.py                      # ~170 first+last name combos for filler generation
├── filler_generator.py               # Filler members + vote allocation (PRNG by org_slug)
└── seed_pipeline.py                  # The bible → DB orchestrator

backend/
├── demo_reset_job.py                 # run_demo_reset_if_due — wipe+seed orchestrator
└── demo_snapshot_generator.py        # Trajectory → VoteSnapshot bulk helper

backend/migrations/versions/
└── c7e8a3d419f5_phase_23_demo_reset_infrastructure.py  # 8 columns + index
```

## Pipeline flow

```
Schedule fires (or POST /api/admin/demo/reset)
        ↓
run_demo_reset_if_due(db, force=…)
        ↓
[WIPE PHASE — single transaction]
        ├── set is_demo_resetting=True on all is_demo=True orgs (lock)
        ├── for each demo org: delete proposals, votes, snapshots,
        │   comments, delegations, intents, follows, delegate_profiles,
        │   org_delegate_profiles, notifications, org_memberships of real users
        ├── delete prior filler-member User rows (email @demo.example pattern)
        └── (org rows themselves stay; their content is re-seeded)
        ↓
[SEED PHASE — same transaction]
        ├── for each of HOA_BIBLE, LOCAL_4021_BIBLE, COALITION_BIBLE:
        │       seed_org_from_bible(db, bible, ORG_SEED_CONFIG[bible.slug])
        │   inside:
        │       1. Upsert Organization (slug, name, charter → description, is_demo=True,
        │          personas JSONB, governance_type, display_order from ORG_SEED_CONFIG)
        │       2. Resolve cross-org user_ids to underlying User rows
        │          (hoa_marcus + coalition_marcus → User username="marcus_pham")
        │       3. Create User + OrgMembership rows from bible.members
        │       4. Create Topic rows from delegate_pages/proposals (prefixed by slug)
        │       5. Create DelegateProfile rows (per topic + visibility)
        │       6. Create Proposal + ProposalOption rows from bible.proposals + drafts
        │          (backdated timestamps from state_at_reset parsing)
        │       7. For each proposal with a matching Trajectory in trajectory_waypoints:
        │          generate_snapshots(...) → VoteSnapshot bulk insert
        │       8. Create named-character Vote rows from delegate_pages[i].vote_rationales
        │       9. Hardcoded inject: Janet's 8 Local votes (Stage 8 §3)
        │      10. Generate filler members + allocate filler votes
        │      11. Create Comment rows from bible.comments with backdated created_at
        │      12. Create Notification rows from bible.notification_feeds
        │          (event_type → user-facing message via Amendment A template table)
        ↓
[COMMIT]
        ↓
update PlatformSetting.demo_reset_last_completed_at
release is_demo_resetting=False on all demo orgs
emit AuditLog action='demo.reset' with success + counts
return DemoResetResult
```

## Editing bible content

### Add a new proposal to an existing org

1. Open the bible (e.g., `hoa_bible.py`). Add a `Proposal(...)` to the `PROPOSALS` list.
2. If the proposal is in `voting` or `closed` status (i.e., has a support trajectory worth visualizing), add a matching `Trajectory(...)` to `trajectory_waypoints.py` keyed by the proposal's ID.
3. The next reset (scheduled or manual) picks it up.

### Add a new character to an existing org

1. Open the bible. Add a `Member(user_id='org_newchar', ...)` to the `MEMBERS` list.
2. If they should have a delegate page, add a `DelegatePage(...)` to `DELEGATE_PAGES`.
3. If they have vote rationales on existing proposals, add them inside the relevant DelegatePage's `vote_rationales`.
4. If they should appear in quick-login on the `/demo` page, set `quick_login=True` AND add their `username` + `description` to the personas seed (currently fallback to `role` — see audit Item 66 for the cleanup path that adds `quick_login_descriptions` to the bible).

### Add a cross-org character (single User, multiple orgs)

1. Add `Member(user_id='org1_charname', is_cross_org=True, ...)` to org 1.
2. Add `Member(user_id='org2_charname', is_cross_org=True, ...)` to org 2.
3. Extend the cross-org user mapping in `seed_pipeline.py` (search for `CROSS_ORG_USER_MAP` or the resolver function) so both per-org IDs resolve to the same underlying `User.username`.

### Add a new demo org

This is more involved (a 4th demo org wasn't anticipated in Phase 23's scope).

1. Author a new bible module under `backend/demo_content/` following the existing pattern. Export a top-level `OrgBible` instance.
2. Add the slug + `governance_type` + `display_order` to `ORG_SEED_CONFIG` in `demo_reset_job.py`.
3. Add the bible import to the `DEMO_ORG_BIBLES` list in `demo_reset_job.py` so it's part of the seed sweep.
4. The frontend Demo.jsx three-org-card rewrite automatically picks up the new org via `GET /api/orgs/demo`; no frontend code change needed.

## Bible schema reference

All dataclass shapes are in `backend/demo_content/schema.py`. The current set:

- `Member(user_id, display_name, quick_login=False, is_cross_org=False, role='', notification_preset='medium')`
- `TopicVisibility(topic, visibility, position_statement='')`
- `PositionStatement(...)`, `VoteRationale(proposal_id, vote, rationale)`
- `DelegatePage(member_user_id, intro, topics, position_statements, vote_rationales)`
- `Comment(proposal_id, author_user_id, body, relative_timestamp, parent_id=None)`
- `Proposal(id, title, voting_method, state_at_reset, ...)`
- `NotificationEvent(event_type, note, ...)`
- `NotificationFeed(member_user_id, events)`
- `OrgBible(slug, display_name, charter, tone_notes, ..., members, delegate_pages, proposals, drafts, comments, notification_feeds)`
- `Waypoint(hour, support_pct)`, `TrajectoryEvent(hour, event_type, label, note)`, `Trajectory(proposal_id, voting_method, duration_hours, waypoints, events, final_result, notes)`

Adding a new field to one of these dataclasses is a schema change: update `schema.py` AND every bible that uses the dataclass.

## Operational reminders

- **Slugs are URL-facing.** Don't change them after deploy — bookmarks, persona deep-links, marketing references break. Phase 23 set them to `demo-cedar-hollow`, `demo-local-4021`, `demo-westgate-coalition` per Z's call.
- **The reset is destructive.** If you're testing a bible change locally and run `POST /api/admin/demo/reset` on prod by accident, the current demo state is gone. Manual trigger requires platform admin; that's the safety gate.
- **Filler-member identities are stable across resets** (PRNG seeded by `(org_slug, index)`). If you change the `name_pool.py` order or add an org with the same slug, filler identities shift. Adding new names at the END of the pool preserves existing identities for the orgs that draw from earlier indices.
- **Snapshot growth.** Each reset creates ~13K snapshot rows. Phase 22's storage estimate (~3 GB/year at high-end scale) accounts for this. Item 62 in the audit doc tracks future cleanup.
- **DST transitions.** The scheduler uses `zoneinfo.ZoneInfo("America/Los_Angeles")` and converts to UTC for the next-due check; both PST and PDT work correctly. Test `TestResetSchedulingDSTTransition` covers both directions.

## Known limitations + audit items

- **Item 65**: Multi-option snapshot tallies are heuristic (decay from option ordering), not parsed from `Trajectory.final_result` strings.
- **Item 66**: Persona descriptions default to `role`; the Stage 8 §6 descriptions need to be added to bibles as a `quick_login_descriptions` dict to surface in the directory cards.
- **Item 67**: 5 bible event_types fall back to `"{event_type}: {note}"` because they're not in Amendment A's template table.
- **Item 68**: Filler multi-option vote allocation isn't aimed at the trajectory; allocation is random within constraints.
- **Item 69**: Filler comments (Amendment C) are deferred; bibles' named-character comments carry the deliberation narrative on their own at current density.

All five are Tier-3 in the audit doc; defer until real-pilot signal asks for them.
