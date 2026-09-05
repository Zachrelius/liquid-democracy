# Phase 107 — Connection security closeout

Status: DEPLOYED. Implementation, independent review, CI and production protocol checks passed. Required Chrome MCP unavailable; rendered QA not claimed. Old Didit key revocation remains independently unverified.

## Workstreams

- W1 connection resources: DONE locally. Authentication uses short-lived sessions in worker threads. No session connection remains checked out during handshake waits, idle subscriptions, or network sends. Vote/retract release their post-commit read transaction before fan-out; vote responses are materialized first and committed notification behavior is preserved.
- W2 live authorization: DONE locally. Fresh canonical proposal access and active-account/token checks precede each update and run during idle periods at most 30 seconds apart, bounded by token expiry. Send and close have deadlines, fan-out batches are bounded, unsolicited client data closes without generating database work, and registration cleanup is unconditional.
- W3 credential hygiene: DONE. The historical Didit value was redacted from the current handoff version. Six synthetic tests and a targeted CI guard detect literal Didit secret assignments without printing values. An in-memory comparison confirms the currently configured Railway backend key differs from the historical value. Old-key revocation at Didit is independently UNKNOWN; Z recalls prior rotation with 95% confidence. Neither key was displayed or exercised, and no secrets or infrastructure were changed.
- W4 deployment: DONE. Exact release commit is deployed successfully; homepage, liveness, readiness, monitor and unauthorized-socket checks passed.

## Root cause and proof

The original route at `1a8aead` kept a generator-injected database session alive for the entire socket lifetime. The independent baseline test opened one authorized idle socket against a disposable one-connection QueuePool: the checkout count remained one and an ordinary SELECT timed out. After disconnect, checkout count returned to zero and SELECT succeeded.

The new actual-route test keeps four sockets open against that same one-connection capacity with zero idle checkouts. Real vote and retraction requests complete with unchanged tally payloads. Committed membership removal, private-scope membership removal, account deactivation, proposal deletion, token expiry, malformed frames, cancellation, database failures and slow clients are covered.

Independent review found and resolved an integration trap: vote requests initially retained their own connection while subscriber authorization needed another. The final transaction release occurs after committed vote/audit/notification work and response materialization. `rollback()` releases the read transaction without detaching shared ORM identities, closing a ranked-choice compatibility regression found by the focused matrix.

## Verification

- Backend baseline: 3,172 passing / 20 environment skips. This pass adds 24 cases.
- Authoritative Linux CI: **3,197 passed / 19 skipped / zero failures** across 3,216 cases in 34m22s. The pass count rises by 25 rather than 24 because one environment-dependent case runs on Linux instead of skipping locally.
- Focused security/voting/visibility matrix: 142 passed.
- Full local collection: 3,216 cases. Initial run: 3,194 passed / 20 skips / 2 monitoring assertions failed because the local safety environment disabled scheduled workers. The complete 15-test monitoring file passed with worker/monitor configuration restored. All cases are covered, totaling 3,196 passes / 20 skips / no unresolved failure; this is explicitly a full run plus targeted configuration-correct rerun, not a claimed single green invocation.
- Credential guard: 6 synthetic tests passed; tracked-text scan passed. A value-redacted in-memory historical regression proved it catches the actual old handoff assignment.
- Independent review: Phase 107 24 passed, Phase 38 authorization 26 passed, and actual vote/retract one-slot pool check passed after the transaction-release correction.
- Python compile and diff whitespace checks passed. The test-generated audit sample was restored only in the isolated worktree.
- No migration; PostgreSQL migration smoke not required. Resource proof uses a real SQLAlchemy QueuePool with disposable SQLite, not a mocked checkout counter.
- No frontend source change. All jobs in GitHub Actions run [33929594302](https://github.com/Zachrelius/liquid-democracy/actions/runs/33929594302) passed: full backend suite and dependency audit, frontend audit/tests/build, and the new secret guard. CI tested implementation `85ee4f7`; subsequent pre-merge changes were reviewer documentation only, with identical backend/frontend/scripts/workflow code.
- Required Chrome MCP is unavailable in this session. Rendered browser QA is not claimed and no substitute browser was used. The frontend currently has no WebSocket consumer; actual socket and vote API integration are covered by the local protocol tests.

## Production

Pre-release backend deployment `9b25eddf-b098-4f3b-ab70-063ed4a811bb` and frontend deployment `d297b96b-f4f0-49e5-87f0-564dfad342be` are successful for Phase 105 merge `8a95f8f`. Homepage bundle is `index-DKjP7ryU.js`; readiness is healthy. A single unauthorized socket to an existing public proposal closed with 4401 and sent no tally, followed by healthy readiness. No production mutation or load was performed.

Release no-ff merge: `e3ecd6284077984de89d386588dd45fc407728f4`. Backend deployment `7a645ef4-807c-4004-843a-a3a92dc425d4` is **SUCCESS** for that exact commit. At `https://www.liquiddemocracy.us`, homepage is HTTP 200, liveness/readiness are `ok`, and the monitor is `ok` with zero issues. A single unauthorized WebSocket closed 4401 without receiving a tally; subsequent readiness remained healthy. The frontend correctly retained `index-DKjP7ryU.js` and its existing successful deployment because no frontend source changed. No production records or configuration were changed by the smoke checks. The merge-triggered CI repeats already-passed code checks automatically; it is not the source of the completed pre-release CI evidence above.

## Files

Application and tests: `backend/websocket.py`, `backend/main.py`, `backend/eligibility.py`, `backend/routes/votes.py`, `backend/tests/test_phase_107_connection_security.py`, `backend/tests/test_phase_38_authorization_audit.py`.

Credential prevention: `.github/workflows/ci.yml`, `scripts/check_didit_secrets.py`, `scripts/tests/test_check_didit_secrets.py`, `phase52a_handoff_to_z.md`, `docs/phase107_credential_remediation.md`.

Documentation: `phase107_connection_security_spec.md`, `docs/phase107_review.md`, this closeout, and `PROGRESS.md`.

## Workspace, commits and follow-ups

Work is isolated in `.claude/worktrees/phase107-connection-security` on `phase-107/connection-session-security`, with a separate integration checkout. The original dirty planning checkout is preserved, including its older local master state.

Implementation commits: `3618167` credential redaction/guard; `404ea5b` spec; `5c6def1` configured-key comparison; `892d6bf` connection security; `0fa4a51` independent review; `85ee4f7` compatible transaction release; `c6db312` review correction.

NOT STARTED: provider-console confirmation that the old Didit key is revoked. Procedure: `docs/phase107_credential_remediation.md`. Exact task dispatch if a separate run is needed: "Confirm the historical Didit key is revoked using provider metadata, following docs/phase107_credential_remediation.md; do not display or exercise the old key."

HTTP access-token invalidation after password reset, horizontal replicas, and a comprehensive general secret scanner remain outside this high-priority pass. No paid capacity, pool-size change, verification session, production data cleanup, or history rewrite was introduced.
