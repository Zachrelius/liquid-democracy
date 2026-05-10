# Delegation Cross-Org Scoping — Diagnostic Findings (2026-05-10)

**Branch:** `diagnostic/delegation-org-scoping`
**Mode:** read-only investigation. No code changes, no migrations drafted, no destructive prod queries.
**Investigation queries:** all SELECT-only, retained at `.tmp_diag/prod_select*.py` for re-run.

---

## 1. Executive summary

The `delegations` table has **no `org_id` column at the schema level**. Phase 4c (multi-tenancy retrofit) added `org_id` to `topics`, `proposals`, `delegate_profiles`, `invitations`, `roles`, `org_memberships`, and `audit_log`, but **skipped the relationship tables**: `delegations`, `delegation_intents`, `follow_relationships`, `follow_requests`. As a consequence, every `db.query(models.Delegation)` call site in the codebase (15+ sites; full inventory in §3) is structurally unable to filter by org — the column doesn't exist. The visualization bugs (Cases 1–2) are direct: `GET /api/delegations/network` and the per-proposal vote-graph endpoint return all rows for the caller without org filter. The tally bug (Case 3) is the same root cause surfaced through `DelegationService._build_context` (`backend/delegation_engine.py:831`), which loads every delegation row platform-wide and indexes them by `(delegator_id, topic_id)` only. Case 4 is "right by coincidence" — `compute_tally` only iterates `eligible_voter_ids_for_proposal` (line 961), so non-member delegators get dropped at iteration time; this is an incidental side-effect filter, not a deliberate cross-org delegation safeguard. **The fix requires a migration** (add `Delegation.org_id` + likely `sub_org_id`, backfill, change unique constraint), is multi-workstream in shape (read-side filtering + write-side org plumbing + frontend org context + graph_store partitioning + tests), and has one load-bearing data decision: a single prod row (`claireandzachary` → `Zachary`, both members of demo and gamenights) cannot be backfilled deterministically and needs Z to choose one of {pick-one-org, drop, duplicate, ask-user}.

---

## 2. Schema findings (S1–S3)

### S1 — `Delegation.org_id` does not exist

`backend/models.py:482-504`:

```python
class Delegation(Base):
    __tablename__ = "delegations"
    __table_args__ = (UniqueConstraint("delegator_id", "topic_id", name="uq_delegation_delegator_topic"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    delegator_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    delegate_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    topic_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("topics.id"), nullable=True, index=True)
    chain_behavior: Mapped[str] = mapped_column(...)
    created_at, updated_at
```

Confirmed against prod schema via SELECT-only query (`.tmp_diag/prod_select.py` Q1):

```
column_name    | data_type                   | is_nullable
id             | character varying           | NO
delegator_id   | character varying           | NO
delegate_id    | character varying           | NO
topic_id       | character varying           | YES
chain_behavior | USER-DEFINED                | NO
created_at     | timestamp without time zone | NO
updated_at     | timestamp without time zone | NO
```

The Phase 4c migration (`backend/migrations/versions/d909c6da9b8c_phase4c_organizations_and_multitenancy.py`) added `org_id` to seven tables but skipped the four relationship tables. The unique constraint `(delegator_id, topic_id)` means a single user can only have one global-or-per-topic delegation across **all their orgs combined** — already wrong for multi-org by definition.

### S2 — `topic_id` is nullable; NULL means "global"

NULL `topic_id` is the current encoding of "applies to every proposal regardless of topic." The pure resolver `find_delegate_pure` at `backend/delegation_engine.py:174-194` consults `user_delegations.get(None)` as the global fallback.

Post-fix the meaning needs to become "global within ORG X" — the row gets a non-null `org_id` and `topic_id IS NULL` means "all topics in org X." There is no clean way to express "global across orgs," because that's the concept Z has declared incoherent.

### S3 — Other delegation-related tables

| Table | `org_id` column? | Notes |
|---|---|---|
| `Delegation` (`models.py:482`) | **NO** | The primary bug surface. |
| `DelegationIntent` (`models.py:740`) | **NO** | Activates into a `Delegation` row via `activate_intents_for_follow` (`routes/delegations.py:431`); same scope blindness. |
| `FollowRelationship` (`models.py:654`) | **NO** | Currently described as "account-level" by intent. F1 question below: stay or migrate? |
| `FollowRequest` (`models.py:622`) | **NO** | Same. |
| `DelegateProfile` (`models.py:600+`) | **YES** (org_id + sub_org_id) | Public delegate listings work org-correctly. The model to imitate. |

**`graph_store`** (`backend/delegation_engine.py:638-734`) is an in-memory NetworkX `DiGraph` per topic plus one `__global__` graph for `topic_id IS NULL`. Module-level singleton at line 1015. Rebuilt from DB at startup (`rebuild_from_db` line 661); mutated incrementally on every add/remove route call. **Zero org awareness** — edges keyed by `(delegator_id → delegate_id, topic_id)` only. Sync model: route flushes/commits to DB then calls `graph_store.add_delegation(...)`; small race window, not the primary bug but worth flagging.

---

## 3. Query inventory (Q1)

All `db.query(models.Delegation)` and equivalent SQLAlchemy query sites. None filter by `org_id` because the column does not exist. Two sites get partial protection from `topic_id.in_(org_topic_ids)` because topics are org-scoped, but global delegations always slip through that filter.

| File:line | Snippet (abbreviated) | Org-scoped? | Notes |
|---|---|---|---|
| `delegation_engine.py:665` | `db.query(models.Delegation).all()` (rebuild_from_db) | **N** | Loads every row platform-wide into graph_store at startup |
| `delegation_engine.py:831` | `for row in db.query(models.Delegation).all():` (_build_context) | **N** | **Load-bearing tally read.** Indexed by (delegator_id, topic_id). Used by tally + per-proposal vote graph |
| `delegation_engine.py:903` | `Delegation.delegator_id == user_id, topic_id == topic_id` (find_delegate ORM) | **N** | |
| `delegation_engine.py:910` | `Delegation.delegator_id == user_id, topic_id IS NULL` (global fallback) | **N** | |
| `routes/admin.py:142` | `db.query(models.Delegation).all()` (system_delegation_graph) | **N** | Admin tool; org-blind by design (debatable post-fix) |
| `routes/delegations.py:32` | list_my_delegations: `delegator_id == current_user.id` | **N** | No `?org=` parameter |
| `routes/delegations.py:77` | upsert_delegation existing-row lookup | **N** | |
| `routes/delegations.py:153` | revoke_delegation | **N** | |
| `routes/delegations.py:230` | personal_delegation_network outgoing: `delegator_id == current_user.id` | **N** | **Visualization bug surface** — pulls every outgoing edge regardless of org |
| `routes/delegations.py:235` | personal_delegation_network incoming | **N** | **Visualization bug surface** |
| `routes/delegations.py:250` | personal_delegation_network delegator_counts | **N** | Cross-org counts in the rendered numbers |
| `routes/delegations.py:354` | _get_chain_behavior internal lookup | **N** | |
| `routes/delegations.py:447, 515, 632, 676` | DelegationIntent / Delegation lookups in request flow | **N** | |
| `routes/delegates.py:19` | _delegation_count for public delegate | **N** | Cross-org counts inflate "popular delegate" numbers |
| `routes/follows.py:39` | _revoke_dependent_delegations on follow-revoke | **N** | Unfollowing reviews ALL their delegations regardless of org |
| `routes/organizations.py:2546` | analytics: `Delegation.topic_id.in_(org_topic_ids)` | **partial** | The one org-aware site, indirectly. Only correct because topics are org-scoped; misses globals entirely |
| `routes/proposals.py:812` | _is_delegate_target_for_proposal | **partial** | Topic-filtered, accidentally OK for topic-scoped delegations; misses globals |
| `routes/proposals.py:832` | _has_delegated_away_for_proposal | **partial** | Same shape. Notification routing |
| `routes/proposals.py:1411` | get_vote_graph delegators_to_me | **N** | Per-proposal graph; cross-org delegators leak (privacy-gated through `private_follow_ids`) |
| `routes/users.py:529` | per-proposal graph chain_behavior lookup | **N** | |
| `seed_data.py:147` | seed-time existing lookup (test seed) | **N** | Out of scope, but would need updating with the fix |

**15+ production read sites; ZERO filter by org_id** because the column doesn't exist.

## Q2 — Ballot-casting trace ("right-by-coincidence")

Walk from `cast_vote` to where membership filtering applies:

1. `backend/routes/votes.py:28 cast_vote` — caller authentication + line 49: `eligible_ids = eligible_voter_ids_for_proposal(db, proposal); if current_user.id not in eligible_ids: 403`. This protects the *casting user* but not delegators.
2. Vote row written, line 166: `tally = delegation_engine.compute_tally(proposal, db)`.
3. `backend/delegation_engine.py:940 compute_tally`: `eligible_ids = eligible_voter_ids_for_proposal(db, proposal); ctx = self._build_context(proposal, db, eligible_ids=eligible_ids); user_ids = sorted(eligible_ids)` (**line 961 — the load-bearing accidental filter**).
4. `_build_context` (line 799) loads `db.query(models.Delegation).all()` (line 831) — **every delegation row platform-wide**, indexed by `(delegator_id, topic_id)`. The `eligible_ids` parameter is only used to filter `direct_votes` / `direct_ballots`, **not delegations**.
5. `compute_tally_pure` iterates `user_ids` (= eligible_ids) and calls `resolve_vote_pure(uid, ctx)` for each.
6. `resolve_vote_pure` calls `find_delegate_pure(uid, ...)` with `user_delegations = ctx.all_delegations.get(user_id, {})`. **No org filter applied here either.**

**The filter at line 961 (`user_ids = sorted(eligible_ids)`) is what catches Case 4.** It's a side-effect filter, not deliberate org-scoping for delegations:
- **Case 4 (Friend A, gamenights-only, demo proposal):** A is not in demo's `eligible_ids`, so the tally never iterates A → A's gamenights global delegation is loaded into `ctx` but never consulted.
- **Case 3 (Test user C, member of both, demo proposal):** C IS in demo's `eligible_ids`. The tally iterates C → calls `resolve_vote_pure(C, ctx)` → no direct ballot in demo → looks up `ctx.all_delegations[C]` which contains the global → Z delegation (created with no org context) → `find_delegate_pure` returns Z → Z's direct demo ballot is found → **C's vote is counted as Z's choice in demo.** Bug confirmed by code reading; matches Z's observation.

The Phase 8.5 sub-org test (`backend/tests/test_delegation_scope.py:263`) even celebrates the absence of org-aware code: *"no special path. No new pure-layer code is required."* That comment now reads as the documentation of the bug — it's correct only because the test scenario placed the non-member on the *delegate* side, not the *delegator* side.

---

## 4. Network graph findings (G1–G2)

### G1 — Data path: component → endpoint → query

**Frontend page** `frontend/src/pages/Delegations.jsx:148`:

```js
const net = await api.get('/api/delegations/network');
```

No org context in URL or headers. `OrgContext` is read for the profile-link target (lines 13-21) but **not** sent to the backend.

**Backend** `backend/routes/delegations.py:220-347 personal_delegation_network`:
- Line 230: `outgoing = db.query(models.Delegation).filter(delegator_id == current_user.id).all()`
- Line 235: `incoming = db.query(models.Delegation).filter(delegate_id == current_user.id).all()`
- Line 250: `all_delegations = db.query(models.Delegation).all()` (for delegator_counts)

### G2 — No org filter at any of those sites

The graph shows every delegation involving the caller across every org. This is exactly the Cases 1–2 visualization bug, with no further investigation needed: the column doesn't exist; the route doesn't accept an `org` parameter; the frontend doesn't send one. Graph-store-backed alternative endpoint `GET /api/delegations/graph` (`routes/delegations.py:180-217`) reads from `graph_store.get_neighborhood(current_user.id)` — `graph_store` is also org-blind (keyed by topic only).

Per-proposal vote graph (`routes/proposals.py:1353 get_vote_graph`) filters its iteration by `eligible_ids` (line 1380), so it accidentally avoids the worst leak; but it still reads cross-org delegations for the `delegators_to_me` set (line 1411), which is then privacy-gated through `private_follow_ids`. Bounded leak, but structural mismatch.

---

## 5. Engine state findings (E1–E2)

### E1 — `graph_store` is in-memory, org-blind

- Type: `DelegationGraphStore` (`backend/delegation_engine.py:638-734`). NetworkX `DiGraph` per topic + one `__global__` graph for `topic_id IS NULL`. Thread-safe via single `Lock`.
- Lifecycle: module-level singleton at line 1015. Rebuilt from DB at startup via `main.py` (after Alembic upgrade). Mutated incrementally on every add/remove/revoke route call.
- Sync: route flushes/commits to DB then calls `graph_store.add_delegation(...)`. Small race window (DB committed but graph not yet mutated); not the primary bug.
- **Zero org partitioning.** Edges keyed by `(delegator_id → delegate_id, topic_id)` only.
- `compute_voting_weight(user_id)` walks `nx.ancestors` on the global graph — used to display "weight" labels in the visualization. **Cross-org ancestors inflate this weight artificially.**

### E2 — Tally reads from DB only, not from graph_store

`_build_context` (line 799) reads `db.query(models.Delegation).all()` directly. `graph_store` is used exclusively for cycle detection (`would_create_cycle`) at write time and for graph visualization (`get_neighborhood`, `compute_voting_weight`). **Tally results are not affected by `graph_store` state.** Any DB-vs-graph_store sync drift impacts visualization and cycle-prevention only, not tally correctness.

---

## 6. Reproduction (R1) and test gap (R2)

### R1 — Reproduction by prod data inspection

No local repro needed; prod data is the existence proof. SELECT-only query (`.tmp_diag/prod_select2.py`) returns:

| delegator | delegator_orgs | delegate | delegate_orgs | spec case |
|---|---|---|---|---|
| `dave` (Dave the Delegator) | demo | `alice` (Alice Voter) | demo | Within-org global, fine |
| `Imperatoricus` (Senator Ric) | gamenights | `ZacharyPetertam` | demo, gamenights | **Case 1**: gamenights-only delegator, A→Z global appears in demo's graph; tally accidentally OK because A not in demo eligible_ids |
| `claireandzachary@gmail.com` (C&ZTest) | demo, gamenights | `ZacharyPetertam` | demo, gamenights | **Case 3**: delegator in both orgs, global delegation made in gamenights, vote IS tallied in demo |

Topic-scoped:

| delegator | delegate | topic | topic.org | spec case |
|---|---|---|---|---|
| `Claire` | `ZacharyPetertam` | Games | gamenights | **Case 2**: Claire in both orgs; Games topic delegation appears in demo graph (visualization), but doesn't tally-leak because demo proposals don't have a Games topic |

All four cases match the dispatch description. **Case 4** is the topology-not-data case: Friend A is not a member of demo, so demo's `eligible_voter_ids_for_proposal` excludes them, so the tally iteration at `delegation_engine.py:961` never visits A — the filter responsible is the eligibility iteration in `compute_tally`, which is **accidental** (Phase 10.1's cross-scope vote leak fix protects the iteration set; cross-org delegation safety wasn't in its scope).

### R2 — Test coverage gap

**Existing tests** (`backend/tests/`):

- `test_delegation_engine.py` — pure resolver behaviour; no orgs.
- `test_delegation_intents.py` — intent activation flow; no orgs.
- `test_delegation_network_isolation.py` — caller A vs caller B with **disjoint** delegations only (lines 84-122). Does NOT cover "callers connected via cross-org delegation that should be hidden from the queried org."
- `test_delegation_scope.py` — Phase 8.5 sub-org tests. Includes `test_cross_scope_delegation_natural_no_vote_in_sub_org_tally` (line 206) but the test fixes `bob` as the **delegate** (not a sub-org member) and asserts `not_cast` — **does NOT cover the inverse: a sub-org member as delegator with a cross-scope delegation TO an in-scope delegate**, which is exactly Case 3's shape. Line 263 explicitly comments: *"No special path. No new pure-layer code is required"* — that comment is the documentation of the bug.
- `test_delegate_applications.py`, `test_delegates_public_visibility.py` — delegate profile endpoints; do not test org scoping of underlying delegations.

**Concrete tests that should exist (none do today):**

1. `test_network_endpoint_filters_by_org_context` — caller in two orgs, one delegation per org; querying `?org=demo` returns only demo delegations.
2. `test_tally_excludes_cross_org_delegators` — user C in orgs X+Y, delegated globally in X, tally for proposal in Y should not count C's delegated vote.
3. `test_global_delegation_is_org_scoped` — global delegation in X does not apply to proposals in Y, even if delegator+delegate are co-members of Y.
4. `test_network_graph_hides_other_orgs_delegations` — A delegates to B in X; B's view of Y's network does not include the A→B edge.
5. `test_delegation_intent_carries_org_context` — intent created from X activates into a delegation row scoped to X, not a cross-org global.
6. `test_followrelationship_org_scoping` (depending on F1 outcome).

The Phase 4c retrofit was incomplete: the migration added `org_id` to data tables but didn't propagate to the relationship tables. The test suite did not catch it because no test was written that constructs a multi-org user with a delegation. **This is exactly the "treat any org-scoped feature as suspect until verified" pattern flagged in project memory.**

---

## 7. Impact assessment (I1–I3)

### I1 — Prod row count

SELECT-only queries in `.tmp_diag/prod_select.py`:

```sql
SELECT COUNT(*) FROM delegations;                         -- 60
SELECT COUNT(*) FROM delegations WHERE topic_id IS NULL;  -- 3 (globals)
```

Topic-scoped audit (delegator OR delegate not an active member of the topic's org):

```sql
WITH topic_scoped AS (
  SELECT d.id, d.delegator_id, d.delegate_id, t.org_id AS topic_org_id
  FROM delegations d JOIN topics t ON d.topic_id = t.id
  WHERE t.org_id IS NOT NULL
)
SELECT COUNT(*) FROM topic_scoped ts
LEFT JOIN org_memberships m1 ON m1.user_id = ts.delegator_id AND m1.org_id = ts.topic_org_id AND m1.status='active'
LEFT JOIN org_memberships m2 ON m2.user_id = ts.delegate_id  AND m2.org_id = ts.topic_org_id AND m2.status='active'
WHERE m1.user_id IS NULL OR m2.user_id IS NULL;
-- → 0  (all topic-scoped rows are "naturally" sound because topics carry org_id)
```

Globals where delegator+delegate share at least one active org:

```sql
WITH g AS (SELECT id, delegator_id, delegate_id FROM delegations WHERE topic_id IS NULL),
coorgs AS (
  SELECT g.id, COUNT(DISTINCT m1.org_id) AS shared_orgs
  FROM g
  JOIN org_memberships m1 ON m1.user_id = g.delegator_id AND m1.status='active'
  JOIN org_memberships m2 ON m2.user_id = g.delegate_id  AND m2.status='active' AND m2.org_id = m1.org_id
  GROUP BY g.id
)
SELECT COUNT(*) AS total_global, COUNT(coorgs.id) AS with_shared_org
FROM g LEFT JOIN coorgs ON coorgs.id = g.id;
-- → total=3, with_shared_org=3, with_no_shared_org=0
-- → distribution: shared_orgs=1: 2 rows, shared_orgs=2: 1 row (the C&ZTest case)
```

**Prod state:**

- 60 delegation rows total.
- 57 topic-scoped: all naturally org-coherent because topics carry `org_id` and prod has no orphaned cross-org topic delegations.
- 3 global (`topic_id IS NULL`):
  - 1 within-demo (`dave` → `alice`) — fine, both single-org users.
  - 1 cross-org-displayable (`Imperatoricus` → `Zachary`) — visualization-leaks; tally accidentally fine (Case 1).
  - 1 cross-org-tallying (`claireandzachary` → `Zachary`) — both members of demo+gamenights; **tally leak.**
- 1 topic-scoped delegation that visualization-leaks (Claire → Zachary on gamenights/Games topic; Claire is in both orgs).

**Affected: ~3 visualization-leaking rows, exactly 1 tally-leaking row.** Small absolute numbers, but the schema gap means every future delegation has the same shape.

### I2 — Fix shape

This is **not a query-filter-only fix** — the schema doesn't carry the information needed to do the filter. Minimum viable fix involves all of:

1. **Migration:** add `Delegation.org_id` (FK to organizations, initially nullable for backfill, then NOT NULL). Likely also `sub_org_id` for parity with Topic/Proposal scoping. Backfill from `topics.org_id` for topic-scoped rows. Ask cascade question (I3) for the 3 globals. Update unique constraint from `(delegator_id, topic_id)` to `(delegator_id, org_id, topic_id)` (or include `sub_org_id` if sub-orgs participate).
2. **Same migration shape for `DelegationIntent`** (and likely `FollowRelationship` / `FollowRequest` — depends on F1 decision).
3. **Read filter at every site in §3** (15+). Cleanest: add `org_id` parameter to `_build_context`; `eligible_voter_ids_for_proposal` already provides org context naturally because proposals carry `org_id`. The "list my delegations" / "my network" routes need new org parameters.
4. **Write side:** every `models.Delegation(...)` constructor (~8 sites) must set `org_id`. Org context is available via `org_middleware` for org-prefixed routes, but `/api/delegations/*` is currently NOT under an org prefix. Either move to `/api/orgs/{slug}/delegations` (large frontend impact) or add `org_id` body field to upsert/request endpoints.
5. **`graph_store` partition by org:** simplest is per-org dict of per-topic graphs, or accept cycle-detection overhead with org filter at edge-add time.
6. **Frontend:** `Delegations.jsx` calls three URLs without org context. Pass `currentOrg.slug`. The page concept itself probably needs to render as "my delegations in {org}" with org switching (since users may have a separate set per org).
7. **Tests:** at minimum the six listed in §6 R2.
8. **Audit log:** existing `delegation.created` audit entries should add `org_id` to details JSON for forensics going forward.

**Multi-workstream**, comparable to Phase 10.1 (cross-scope vote leak fix) but bigger because it touches the read paths in every delegation surface.

### I3 — Cascade decision for 3 prod global rows

Each global row needs a backfill choice:

- **Row 1:** `dave` (demo only) → `alice` (demo only). Trivial: `org_id = demo.id`.
- **Row 2:** `Imperatoricus` (gamenights only) → `Zachary` (demo + gamenights). Trivial: `org_id = gamenights.id` (delegator only has one org).
- **Row 3:** `claireandzachary` (demo + gamenights) → `Zachary` (demo + gamenights). **Two shared orgs.** No principled deterministic backfill. Z must choose:
  - **Option A:** pick the more-recently-active org (e.g., by `updated_at` of the delegation, or by recent vote activity).
  - **Option B:** drop the row (force user to re-create per-org).
  - **Option C:** duplicate into both orgs.
  - **Option D:** ask the user (in-app banner or email) which org they intended.

Recommend including this section verbatim in the eventual fix-spec dispatch so Z can decide with full context.

---

## 8. Followups & adjacents (F1–F2)

### F1 — Adjacent surfaces

**Sub-org delegation behaviour.** `Topic.sub_org_id` and `Proposal.sub_org_id` are nullable; Phase 8.5 added scope handling for proposals/topics but **not for delegations**. Prod has no sub-org delegation row today (`SELECT COUNT(*) FROM delegations d JOIN topics t ON d.topic_id = t.id WHERE t.sub_org_id IS NOT NULL` returns 0). However, the moment a sub-org-only topic gets a delegation, the same bug applies at the sub-org level. **Recommend extending the fix to `sub_org_id` for symmetry**, even though no prod data is currently affected — the migration is "free" once `org_id` is being added.

**`FollowRelationship` / `FollowRequest`.** Currently account-level by intent (`routes/follows.py` comments). Two arguments:

- *Keep account-level*: a "follow" expresses interest in a person across all contexts. If you follow someone in gamenights, you might reasonably expect to see their activity in shared demo too. The "social media" semantic.
- *Make org-scoped*: parallel with delegations — if delegations are org-scoped, the follow that gates a `delegation_allowed` follow should be org-scoped too, otherwise approving a follow in any org silently grants delegation rights in any other co-org.

**The latter argument is structurally stronger** because of `delegation_allowed`: `_revoke_dependent_delegations` (`routes/follows.py:30-75`) revokes delegations based on follow state, and `activate_intents_for_follow` (`routes/delegations.py:431`) activates pending intents into Delegation rows when a follow is approved. If delegations become org-scoped but follows stay account-level, you get an asymmetry where approving one follow in any org auto-creates per-org delegations — that's worse than the current bug.

**`DelegationIntent`.** Same shape of bug. Add `org_id` in the same migration. The intent → delegation activation path needs to thread `org_id` through.

**`DelegateProfile`.** Already has `org_id` and `sub_org_id`. The model to imitate.

### F2 — Incidental tech debt observed (not in scope)

- `graph_store.rebuild_from_db` is O(N) over all delegations and reads them all in memory. Fine at 60 rows; problem at scale.
- `graph_store.add_delegation` mutates after DB commit but isn't transactionally tied; process crash between the two leaves the in-memory graph stale until restart.
- `seed_data.py:147` and various test seeds construct `Delegation` rows without org context — will need updating after the migration.
- `test_delegation_scope.py:263` comment ("No special path. No new pure-layer code is required") will become misleading post-fix. Worth updating in the same pass.
- `routes/delegations.py:148` (`revoke_delegation`): URL takes either a topic UUID or the literal string `"global"`. After org-scoping, `"global"` collides with "global within which org?" — needs the org context in the URL.
- `routes/admin.py:133` system-wide delegation graph endpoint shows everything cross-org. Probably correct semantics for an admin tool, but should be re-evaluated post-fix.

---

## 9. Recommended fix shape (broad strokes — not detailed)

For the eventual spec, the lead's recommendation:

- **Cluster count: ~5 workstreams.** Comparable in shape and size to Phase 13.2 (notifications redeploy) or Phase 12 Stage 2 (configurable role permissions Stage 2). Bigger than Phase 16 / Phase 17 (which were single-cluster + frontend).
  1. **Cluster B (backend):** migration (add `Delegation.org_id` + `sub_org_id`; backfill; constraint update; same shape for `DelegationIntent`; conditionally same for `FollowRelationship`/`FollowRequest` per F1) + read-side filtering at every query site in §3 + write-side org plumbing in CRUD endpoints + `_build_context` org parameter + `graph_store` partition.
  2. **Cluster F (frontend):** `Delegations.jsx` org context + URL changes + page-concept evolution to per-org view.
  3. **Cluster T (tests):** the 6 missing scenarios listed in §6 R2.
  4. **Cluster D (docs):** update the misleading "no special path" comment in `test_delegation_scope.py:263`; help-page section on what "global" means; SECURITY_REVIEW addendum on the prior leak + the closure.
  5. **Cluster G (cleanup):** F2 incidental items listed above; re-evaluate `routes/admin.py` system graph; rename or repurpose `"global"` URL token.
- **Migration:** YES, mandatory. Two-phase recommended (add nullable column → run backfill script → ALTER NOT NULL) for safety on the C&ZTest ambiguous row.
- **Sub-org delegation:** **include in the same pass.** No prod data affected today, but the migration is free once `org_id` is being added; deferring would require a second migration later.
- **`FollowRelationship` org-scoping:** depends on F1 decision (Q2 below). If yes, add to the same migration; if no, document the intentional asymmetry in SECURITY_REVIEW.
- **Test infrastructure:** no new harness needed. Backend tests use `pytest` with the existing `test_db` fixture pattern. The 6 new tests are straightforward additions to existing `test_delegation_*.py` files. **Frontend test framework is still absent** (Phase 17 audit Item 42); browser verification covers the network-graph UI changes.
- **Backfill timing:** two-phase migration. The 1 ambiguous global row requires Z's decision (Q1 below) embedded in the backfill script's behavior.
- **Risk:** moderate. The migration touches a foundational table that every tally reads from. PG smoke `--mode upgrade` will exercise the alembic chain. Recommend the spec require integration tests against real `models.Vote` rows (Phase 17's `test_earliest_decisive_vote_reads_ballot_dict` pattern) so we don't ship the same shape of bug — passing-tests-with-wrong-fixtures — that Phase 17 caught in pre-merge.

---

## 10. Open questions for Z (decide before fix-spec writing)

1. **Cascade for the C&ZTest global row** (I3 row 3): pick A/B/C/D from §7 I3.
2. **Follow-relationship scope:** stay account-level or get retrofitted with `org_id`? If the latter, that's a parallel migration with similar shape (and probably belongs in the same pass for atomic behaviour).
3. **API surface change:** keep `/api/delegations/*` flat (with `?org=` or body field) or move to `/api/orgs/{slug}/delegations/*`? The latter is cleaner but a bigger frontend lift.
4. **Sub-org scoping for delegations:** include in this fix or defer? Recommendation: **include** (migration is free once org_id is being added; no prod data affected today).
5. **`DelegationIntent` activation path:** when an intent activates, what `org_id` does the resulting delegation get? Probably the org context from the intent itself (which means intents also need `org_id`).
6. **Backfill timing:** single-pass migration with backfill in `upgrade()`, or two-phase (add nullable → backfill script → ALTER NOT NULL)? Recommendation: two-phase for safety on the ambiguous row.
7. **Cycle detection:** should cycles be detected per-org or platform-wide? Currently `graph_store` does global + per-topic. **Per-org is the natural answer post-fix.**
8. **Audit log retro:** backfill `org_id` on existing `delegation.created` audit entries (forensic completeness), or only add it going forward?
9. **Communication:** any in-app or email notification to the C&ZTest user (or all global-delegation users) explaining the change? Or treat as silent infrastructure?

---

## 11. Out-of-scope reminder

This document is a diagnostic. No code was changed; no migrations were drafted (even in `.tmp_diag/`); no prod data was mutated (all queries were SELECT-only). The branch `diagnostic/delegation-org-scoping` carries only this document. The fix is a separate spec dispatch decided by Z + planning agent based on this diagnostic's findings and Z's answers to §10.
