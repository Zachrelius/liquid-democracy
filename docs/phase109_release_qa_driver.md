# Phase 109 isolated release API QA

Executed successfully in the isolated production org on October 8, 2026. API driver and scoped worker gates PASS. The procedural instructions below describe the one-shot workflow; do not rerun bootstrap or API driver against existing fixtures. Final evidence: docs/phase109_closeout.md.

The bootstrap and driver operate only on `phase109-release-qa-20261008` and the two fixed `phase109releaseowner` / `phase109releasemember` accounts. They require fresh distinct passwords supplied through `PHASE109_QA_OWNER_PASSWORD` and `PHASE109_QA_MEMBER_PASSWORD`. Keep passwords out of command-line arguments, logs, checked-in files and manifests. Do not change any existing user's credentials.

After exact deployment verification, the authorized release operator can run the bootstrap once with an explicitly selected PostgreSQL `DATABASE_URL` and `--confirm-isolated-production-qa`. It creates an invite-only, hidden, members-only organization; an org steward and member with fictional `@demo.example` email addresses; and explicit disabled notification preferences. Neither account is a platform administrator. No proposals, email or identity-provider sessions are created by bootstrap. Any organization/account collision causes refusal, not reuse or reset.

Run the API driver separately, from backend:

```
python scripts/phase109_release_api_qa.py --base-url https://www.liquiddemocracy.us --manifest phase109-release-qa-manifest.json --confirm-isolated-release-qa
```

The base URL accepts exactly the production HTTPS origin or local HTTP on localhost/127.0.0.1. Redirects are disabled. Python optimization (`-O`) is refused so scope/assertion guards cannot disappear. A pre-existing output manifest is refused. The driver logs in with both synthetic accounts, checks their names/emails/non-admin flags, verifies exact two-member org scope and an empty proposal/topic/subgroup fixture before writes, and saves non-secret IDs after each creation. Failure messages omit response bodies and credentials. A failed run may leave partial synthetic fixtures; inspect the partial manifest rather than rerunning or clearing them automatically.

The driver creates one topic, one member delegate profile visible within the hidden org, an owner-to-member topic delegation, one subgroup, and nine ordinary proposals: four open voting proposals for browser QA, four finalized method examples, and one subgroup draft. It verifies default-method-list denial of all four opt-ins, restores the original parent settings in a finally block, tests subgroup overrides, and creates proposals through normal authenticated APIs so the server generates fresh voting rules. For each method it checks delegated early ballots, immediate neutral override, hidden early totals, explicit abstention, retraction restoring delegation, late-option defaults, revoting, manual close, reproducible frozen reads and rejection of post-close casts. It preserves the four open proposals for rendered verification.

Worker closure is deliberately reported **NOT RUN** by the API driver. Create four additional ordinary proposals through the same authenticated org API, one per method, with titles beginning `Release QA worker `, `deliberation_days: 0`, `stable_result_required: false`, and `quorum_threshold: 0`. Cast a meaningful synthetic ballot on each. Preserve the original four open browser fixtures. Save the new IDs as a JSON object with exactly the keys `star`, `score`, `ranked_pairs`, and `majority_judgment`.

In a dedicated server-side process with explicitly selected PostgreSQL `DATABASE_URL`, supply that non-secret JSON object on standard input:

```
python scripts/phase109_release_worker_qa.py --confirm-exact-production-worker-qa
```

The helper validates the fixed private org, exact two synthetic non-admin members, disabled notification channels, each method/author/title/status and absence of a final record. It locks and validates the entire batch before changing any deadlines. It shortens only those four deadlines, disables their stability requirement, invokes `evaluate_proposal` on each exact row and commits the batch atomically. It verifies frozen results, notification staging, exactly one additional closure audit (preserving any API creation audit), and a no-op retry. It never calls the global tick or changes scheduler settings. Refusal rolls back the batch. Keep its non-secret output as execution evidence; seven local tests cover all four closures, existing API-shaped audit history, repeat evaluation, unrelated-row preservation and five scope refusals. Production worker execution subsequently PASSED after helper fix c754834 deployed in merge 550a521; see the completed evidence below.

Local validation: six tests pass, including the entire driver through real FastAPI endpoints on an isolated in-memory SQLite database bootstrapped specifically for the test. The five URL rejection tests cover external hosts, production HTTP, paths, embedded credentials and query strings. Existing `phase109-qa` local browser fixtures and production were not touched during preparation.

Worker helper follow-up: the initial production attempt rolled back when its audit-count assertion queried before pending audit rows were flushed. Production sessions use `autoflush=False`; the worker correctly stages its audit for the caller's transaction. The helper now explicitly flushes before checking persistence. Seven worker-helper tests pass with production's flush policy, including reproduction of the original failure before the fix, rollback after the second closure has been staged, and a successful clean retry. This changes the QA helper only, not application closure behavior.

Completed worker execution: backend deployment `639f499a-34cf-46d4-891b-5cfe660fca2b`
was SUCCESS for exact merge `550a521`. Read-only preflight found the four exact
worker fixtures voting/unfinalized, each with a meaningful ballot. The manifest
was supplied on stdin through Railway SSH. Every method returned passed,
closed_on_time, new_status_audits=1, notification_intent_staged=true and
retry_noop=true. Original browser fixtures were preserved by this helper and
later finalized through production browser admin QA. No global tick was run.
The initial assertion failure rolled back the whole batch; retry succeeded.
The checked-in closeout records the exact non-secret IDs and outcomes.
