# Phase 30.2 B2 — Visibility Model Audit Findings

**Branch:** `phase-30-2/visibility-audit-and-delegate-page-fix`
**Author:** Code team (read-only investigation per dispatch §B2)
**Date:** 2026-05-17
**Status:** Audit complete — paused for planning review per dispatch instruction.

## Executive summary

`OrgDelegateProfile.page_visibility` is **purely a URL gate** on the dedicated public-delegate-page endpoint. It does not gate any other surface in the codebase today. Z's preconditions for the proposed consolidation (kill `page_visibility`, add `followers_only` between `private` and `public` on each topic's `visibility` ladder) hold cleanly.

Three pre-existing oddities surfaced during the audit, none blocking the consolidation:
1. The browse endpoint (`/api/orgs/{slug}/delegates`) does not check `page_visibility` — a user with `page_visibility='private'` who has a `public_accepting` topic appears in the browse list anyway. Stored `page_visibility` is overridden by `effective_page_visibility` at the only place that gates on it, so this is observable but harmless.
2. `can_see_votes` (vote visibility on the public profile page) does not differentiate `view_only` vs `delegation_allowed` follow permission levels — any follow row passes the check.
3. `effective_page_visibility` returns `'public'` whenever ANY topic is non-private, including transparent-only (`public`) topics. There is no way to have a page visible at `private_delegators` while having any `public` topics — the topic state wins.

## B2.1 — Field-level findings

`OrgDelegateProfile.page_visibility` is a 2-value Enum (`private`, `private_delegators`). The 3-value logical "public" state is derived from topic state via `OrgDelegateProfile.effective_page_visibility(db)`:

```python
def effective_page_visibility(self, db) -> str:
    non_private_topic_count = (
        db.query(DelegateProfile)
        .filter(
            DelegateProfile.user_id == self.user_id,
            DelegateProfile.org_id == self.org_id,
            DelegateProfile.visibility != "private",
        )
        .count()
    )
    if non_private_topic_count > 0:
        return "public"
    return self.page_visibility
```

Stored values & their semantics:
- `'private'` (default) — owner-only. Public page returns 404 to everyone except the owner.
- `'private_delegators'` — owner + any user with a `FollowRelationship` row pointing at the owner with `org_id = page_org_id`. Permission level (`view_only` vs `delegation_allowed`) is NOT differentiated by the gate.
- Derived `'public'` — anyone, including unauthenticated viewers.

**Where the field is read in backend Python:**

| File:Line | Use |
|---|---|
| `models.py:847` | The derivation itself. |
| `routes/delegate_profiles.py:110` | Default on first-access get-or-create. |
| `routes/delegate_profiles.py:123` | Same — first-access return value. |
| `routes/delegate_profiles.py:178` | GET own-profile reports `effective_page_visibility` in the response. **No gating.** |
| `routes/delegate_profiles.py:651-653` | PATCH own-profile writes the value. |
| `routes/delegates.py:571-591` | **The only real enforcement point** — public-page GET gates 404 on private + checks follower-relationship on `private_delegators`. |

**Frontend:**

| File:Line | Use |
|---|---|
| `frontend/src/pages/DelegateProfile.jsx:710` | PATCH body when changing radio. |
| `frontend/src/pages/DelegateProfile.jsx:790` | Displays current effective state under "Effective: …". |
| `frontend/src/pages/DelegateProfile.jsx:857-911` | Phase 30.1 B1 — the 3-radio block that disables Private + Followers when effective is public. |

That's the complete map. Vote visibility (`permissions.can_see_votes`), the browse endpoint (`browse_org_delegates`), the delegation graph, the user-search endpoint, the follow-request flow, notifications, and the rationale endpoint all read user state at the `DelegateProfile` (per-topic) level, not the `OrgDelegateProfile` (page) level — they have no idea what `page_visibility` is set to.

**Is the stored value ever different from effective?**

Yes — and that's the design. When the user has any non-private topic, `effective` is forced to `'public'` regardless of stored value. The stored value matters ONLY when ALL topics are private (or the user has no `DelegateProfile` rows at all in the org).

## B2.2 — Surface-by-surface audit

| Surface | Behavior |
|---|---|
| Delegate browse list (`/api/orgs/{slug}/delegates`) | Filters on per-topic `DelegateProfile.visibility = 'public_accepting'`. **Does NOT check `page_visibility`.** A user with `page_visibility='private'` + a `public_accepting` topic appears here. |
| Delegate browse list, viewer's perspective | Same — the endpoint is identical regardless of viewer. No filter on follower status. |
| Public delegate page (`/api/orgs/{slug}/delegates/{handle_or_username}`) | The single enforcement point. `private` → 404 to everyone except author. `private_delegators` → 404 unless author OR `FollowRelationship` (any permission level) exists in this org. `public` (auto-derived OR stored — but stored `public` doesn't exist post-Phase-19) → anyone. |
| Public delegate page (private mode) | HTTP 404 with body `{"detail": "Delegate page not found"}` — same shape as "no such user" so existence isn't leaked. |
| Vote rationale visibility | `permissions.can_see_votes(viewer, target, topic_ids)` → True if (self) OR (target has any public DelegateProfile on a matching topic) OR (any FollowRelationship row exists). **Does NOT check `page_visibility`.** |
| Follow request flow | No `page_visibility` check. A user with `page_visibility='private'` can still receive follow requests. |
| Delegation network graph | Reads `DelegateProfile` per-topic visibility for edge attributes. No `page_visibility` check. Delegate nodes are rendered regardless of page state. |
| Search results (`/api/users/search`) | No `page_visibility` check. Private-page delegates are searchable. |
| Notifications | No `page_visibility` references in `notification_events.py` or `email_service.py`. Notification routing is independent of page state. |
| Cross-org page reachability | Per-org enforcement: Marcus's `OrgDelegateProfile` in Cedar Hollow and in Coalition are independent rows. Visiting `/cedar-hollow/delegates/marcus_pham` gates on Cedar Hollow's `page_visibility`; visiting `/westgate-coalition/delegates/coalition_marcus` gates on Coalition's. No cross-org leakage possible. |

## B2.3 — Vote visibility findings

**Z's question:** "All your votes are currently visible to approved followers regardless of these selections — correct me if that's wrong."

**Answer: correct.** The gate in `permissions.can_see_votes` is:

```python
def can_see_votes(db, viewer_id, target_user_id, topic_ids) -> bool:
    if viewer_id == target_user_id:
        return True
    # public delegate on a matching topic → public
    if topic_ids:
        profile = db.query(DelegateProfile).filter(
            DelegateProfile.user_id == target_user_id,
            DelegateProfile.topic_id.in_(topic_ids),
            DelegateProfile.is_active.is_(True),
        ).first()
        if profile:
            return True
    if viewer_id is None:
        return False
    # any follow relationship
    rel = db.query(FollowRelationship).filter(
        FollowRelationship.follower_id == viewer_id,
        FollowRelationship.followed_id == target_user_id,
    ).first()
    return rel is not None
```

Three sub-questions:

1. **Vote visibility on the public delegate page** — gated by `can_see_votes`, which checks per-topic public-delegate state + follow relationship. **Independent of `page_visibility`.**
2. **Vote visibility in delegation chains** (`resolve_vote_pure`) — the resolver doesn't expose votes; it computes a delegate-cast `Vote` row in the same shape as a direct vote. No leak.
3. **Vote rationale visibility** — served by `GET /api/votes/{id}/rationale` (`routes/votes.py`); the rationale endpoint gates on the same `can_see_votes` shape. Rationale is not shown without the vote.

Note: `can_see_votes`'s `FollowRelationship` check does NOT differentiate `view_only` from `delegation_allowed`. Both permission levels grant vote visibility. This is consistent with the public-page endpoint's `private_delegators` check (same shape, same lack of differentiation).

## B2.4 — Condition check for Z's proposed model

Proposed model: kill `page_visibility`; add `followers_only` between `private` and `public` on each topic's `visibility` ladder. Page reachable at the highest threshold any of its topics is at.

| Precondition | Holds? | Notes |
|---|---|---|
| `page_visibility` is purely a "is the page reachable" toggle | ✅ Yes | Only `routes/delegates.py:571` enforces it. |
| No other code path reads `page_visibility` for behavior we'd want to preserve | ✅ Yes | Confirmed via exhaustive grep across `backend/`. The GET own-profile endpoint reports it; nothing else reads it. |
| `followers_only` at the topic level is cleanly modeled | ✅ Yes — with one caveat | Bio + position statement + votes on the topic visible only to approved followers. Vote visibility already differentiates by per-topic public-delegate state (the existing `can_see_votes` check) — the new `followers_only` value would be a fourth state in `DelegateProfile.visibility` (`private` / `followers_only` / `public` / `public_accepting`). The vote-visibility logic would need a parallel update so `followers_only` topics expose votes to followers only (not to the general public). |

The caveat: `can_see_votes` currently has a shortcut that says "any FollowRelationship → can see all votes." That conflates "I follow this person" with "I can see their votes on every topic." Z's proposed model implies per-topic `followers_only` should mean votes on THAT topic only visible to followers. A clean implementation either:
- Keeps the broad "follow → all-vote visibility" shortcut (simple — followers are already trusted with everything they want to see), OR
- Tightens to "follow + topic at `followers_only` → only those topic's votes." More surgical but a behavior shift; non-target-issue per dispatch out-of-scope list.

**Recommendation for Phase 30.3:** keep the existing broad follow-shortcut. The new `followers_only` topic value gates page-level access (URL reachability + bio/position render) without tightening the vote-shortcut. That preserves existing follower experience while adding the new visibility option.

## B2.5 — Approved-follower semantics

"Approved follower" means a `FollowRelationship` row with:
- `follower_id = viewer`
- `followed_id = target`
- `org_id = the_org_being_viewed` (org-scoped per Phase 18 D2)
- `permission_level` is either `view_only` OR `delegation_allowed` — **both count** for page-visibility purposes.

No per-topic follower visibility today. Today's `private_delegators` model treats "all approved followers in this org" as a single audience for the whole page. The proposed `followers_only` topic value would shift that to per-topic — a single user could have one topic `public` and another `followers_only`, exposing different content to different audiences.

## B2.6 — Recommended design for Phase 30.3

**Schema:**
- Change `DelegateProfile.visibility` enum from `('private', 'public', 'public_accepting')` to `('private', 'followers_only', 'public', 'public_accepting')`. Migration adds the new enum value; existing rows unchanged.
- Drop `OrgDelegateProfile.page_visibility` column. Migration removes; existing data: any user with `page_visibility='private_delegators'` AND no non-private topics should... actually probably nothing — those rows are useless under the new model. Could optionally backfill: if user has `page_visibility='private_delegators'`, set every existing `private` topic to `followers_only`. Decision deferred to Phase 30.3 spec author.
- `effective_page_visibility` derivation simplifies to: "highest visibility across topics" (`public_accepting > public > followers_only > private`). The "stored fallback" branch is gone.

**Backend semantics:**
- Public-page endpoint's gate: walk the user's `DelegateProfile` rows; the highest visibility wins.
  - All `private` → 404 to non-author.
  - At least one `followers_only` (and no `public`) → render to author + approved followers + 404 to others. Only render `followers_only` topics; private topics still hidden.
  - At least one `public` or `public_accepting` → render to everyone. Render `followers_only` topics ONLY to followers + author; hide them from anonymous/non-follower viewers; private topics always hidden.
- Vote visibility: keep the current `can_see_votes` shape. Follower → sees all votes (existing behavior, see §B2.4).

**Frontend:**
- `DelegateProfile.jsx` per-topic radio block grows to 4 options: Private / Visible to followers / Public (transparent) / Public — accepting delegation. The Page Visibility section is removed entirely.
- `DelegatePublic.jsx` filters which topics it renders based on viewer relationship — same shape as the backend response (the endpoint already does the filtering).

## B2.7 — Migration sketch

1. Add `followers_only` value to the `delegate_profile_visibility` PG enum.
2. (Optional backfill — see §B2.6) For each user where `OrgDelegateProfile.page_visibility = 'private_delegators'`, for each of their `DelegateProfile` rows where `visibility = 'private'`, set `visibility = 'followers_only'`. This preserves the user's stated intent ("show my private stuff to my approved followers") in the new model.
3. Drop the `page_visibility` column from `org_delegate_profiles`. Drop the `org_delegate_page_visibility` PG enum if no other table uses it (none do).
4. Update `effective_page_visibility` to the simpler "highest topic visibility wins" rule.
5. Sweep `routes/delegate_profiles.py` to remove the `page_visibility` PATCH handling.

Migration is reversible (down() flips the values back). Estimated ~2-3 hours including tests.

## B2.8 — Surfaced bugs / oddities

**(B) Browse endpoint ignores `page_visibility`.** A user with `page_visibility='private'` and a `public_accepting` topic appears in the browse list. Strictly: this isn't a bug because once they have a `public_accepting` topic, `effective_page_visibility` derives to `'public'` anyway. But it surfaces a redundancy — the stored `page_visibility` is moot the moment you make any topic public. Phase 30.3's "highest topic visibility wins" derivation eliminates the redundancy.

**(B) `effective_page_visibility` makes the `private_delegators` setting unreachable in many states.** Today: as soon as the user makes any topic non-private, `effective` jumps to `'public'`, and the radio for `private_delegators` becomes inert (Phase 30.1 B1 disabled it visually). The combination "I want my page restricted to followers AND I want public-accepting on one topic" is unrepresentable. Z's proposed model fixes this by making each topic its own audience.

**(B) `can_see_votes` permission-level shortcut.** Any `FollowRelationship` row (including `view_only`) grants view of all the target's votes. Some users probably expect `view_only` to mean "view profile only, not votes" — that's not what the field does. Pre-existing; Phase 30.3 is a reasonable time to revisit but the dispatch is out-of-scope for visibility consolidation. Logged for a future targeted pass.

**(N) `DelegateProfile.is_active` legacy column.** `can_see_votes` reads `is_active`; the Phase 19 `visibility` column superseded the "registered vs not" semantic. `is_active` is still set to True by the seed pipeline + create flows. Removing it is its own deferred cleanup pass.

**(N) `OrgDelegateProfile.page_visibility` default is `'private'`** but `effective_page_visibility` derivation makes it `'public'` as soon as any topic is non-private. A new user who creates a `public_accepting` topic without touching the page-visibility section has an "effective public" page even though their stored value says private. Z noticed this confusion; the Phase 30.3 consolidation removes the surface that creates it.

---

## Closeout

Audit confirms Z's proposed consolidation is clean. Phase 30.3 dispatch should specify:
1. Schema migration (add `followers_only` value, drop `page_visibility` column).
2. Backfill choice for existing `private_delegators` users (recommend: convert private topics to followers_only for those users).
3. Frontend radio expansion (4 options per topic, remove the Page Visibility section).
4. Backend public-page endpoint refactor (single derivation rule).
5. Test surface for the new `followers_only` semantic.

No code changes in this pass per dispatch §B2 instruction. Awaiting planning agent review + Phase 30.3 dispatch.
