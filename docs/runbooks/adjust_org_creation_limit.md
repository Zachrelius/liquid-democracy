# Runbook: Adjust a User's Org-Creation Limit

**When you need this:** a real user has hit the per-user cap on owned
orgs and asks for more headroom. Default cap is 3.

**Who runs it:** code-team operator (not Z, not the user themselves).
The script writes to prod via the standard prod DB URL.

## How the limit works (the gate)

`User.org_creation_limit` is a nullable INT on the `users` table.

- **NULL** -> the platform default `DEFAULT_PER_USER_ORG_LIMIT = 3` applies
  (`backend/routes/organizations.py` line ~284).
- **N (integer)** -> the user can own at most N orgs.

Gate 3 of `POST /api/organizations` (`create_organization` in
`backend/routes/organizations.py` line ~353) counts the user's
**owned** orgs — defined as `OrgMembership` rows whose
`Role.system_key == 'steward'` — and 403s if the count is at or above
the effective limit. Demoted/transferred orgs no longer count.

## The procedure

Use `backend/scripts/set_org_creation_limit.py`. It's reusable for any
user (not hardcoded to a specific one), dry-runs by default, writes a
`user.org_creation_limit_changed` audit row on `--confirm`, and is
idempotent.

### 1. Confirm the target user

```bash
# Dry-run first — prints the current limit and the new value, makes
# no write. Identify the user by username OR email (case-insensitive).
DATABASE_URL="<prod-public-url>" \
    python backend/scripts/set_org_creation_limit.py \
        --user <username-or-email> \
        --limit 10
```

The script prints the resolved User row's id, username, email, and the
current `org_creation_limit` so you can sanity-check before applying.

### 2. Apply

```bash
DATABASE_URL="<prod-public-url>" \
    python backend/scripts/set_org_creation_limit.py \
        --user <username-or-email> \
        --limit 10 \
        --confirm
```

Audit row is written before commit; user can verify via the platform
admin audit log when desired.

### 3. Verify

The user can immediately attempt org creation; Gate 3 reads the new
limit each request, so no restart/redeploy is needed.

## Special cases

### Clear an explicit limit back to the platform default

Pass the literal string `none` as the limit:

```bash
python backend/scripts/set_org_creation_limit.py \
    --user <user> \
    --limit none \
    --confirm
```

This writes `NULL` to the column. Gate 3 then falls back to
`DEFAULT_PER_USER_ORG_LIMIT` (currently 3).

### Block a user from creating any orgs

`--limit 0` blocks creation (owned count is always >= 0; limit 0
fails the gate immediately). Reserve for moderation cases — there's
no audit-trail-preserving "soft suspend" beyond this.

## Why this is a CLI script and not an API

Today there is no platform-admin API endpoint or UI for adjusting
`User.org_creation_limit`. Adjustments are infrequent enough that a
reviewed code-team-run CLI is the right cost/risk tradeoff: it
avoids building a new admin surface (auth, rate-limit, UI) that would
need ongoing maintenance for a feature used 1-2x per quarter.

**Future improvement (deferred):** if limit adjustments become
frequent, build a proper platform-admin endpoint
(`PATCH /api/admin/users/{id}/org-creation-limit`) + a small admin UI
in `frontend/src/pages/platform-admin/`. That moves the operation out
of code-team hands and into platform-admin hands. Not warranted yet.

## Related

- Gate 3 logic: `backend/routes/organizations.py` line ~353
- Default constant: `DEFAULT_PER_USER_ORG_LIMIT` (`routes/organizations.py` line 284)
- Audit reading: any `user.org_creation_limit_changed` event in the audit table
  (typically inspected via `/api/admin/audit?action=user.org_creation_limit_changed`)
