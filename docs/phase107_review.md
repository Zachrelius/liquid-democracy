# Phase 107 independent security review

Status: independent code review and focused local regression checks PASS. No remaining merge-blocking code defect found. Full-suite, CI, and production verification remain lead-owned gates.

Reviewed the Phase 107 specification, latest PROGRESS entries, WebSocket lifecycle, canonical proposal-viewer predicate, vote cast/retract integration, and relevant notification background-task arguments.

## Findings addressed during implementation

- Fresh authorization sessions initially competed with database connections retained by the HTTP vote handlers during broadcast. Both cast and retract now release their read transaction with `db.rollback()` before awaiting fan-out. Cast materializes its typed response after notification processing and before transaction release; email tasks retain scalar arguments rather than attached ORM objects. Vote/audit writes and any emitted notifications are committed before this read-transaction rollback. The first implementation used `db.close()`, which detached ORM objects retained by shared test fixtures; correction `85ee4f7` preserves their session attachment while still releasing the connection.
- Token expiry was initially checked before potentially slow authorization queries. The implementation now checks expiry again after those queries and on return to the event loop before granting access for a send.
- Unsolicited subscribed-client messages initially caused fresh database checks. The subscribed protocol has no such messages; they now close the connection rather than generating query traffic.

## Security and resource boundaries reviewed

- The canonical viewer predicate remains authoritative. Its optional user filter narrows existing queries without introducing new access grants. Active organization membership, active private-suborganization membership, parent administrator/steward implicit power, public-suborganization parent visibility, and legacy unscoped behavior retain their existing meaning.
- Platform administrator bypass still requires a valid token and active account.
- Session creation, queries, and closure happen together in a worker thread. Handshake, idle waits, and network sends do not retain the subscription's database connection.
- Broadcasts revalidate fresh state under a per-socket lock; registration is checked again before send. Send and close have deadlines, fan-out uses bounded batches, and empty proposal buckets are pruned.
- Transport cleanup runs in the subscription handler's unconditional finally block; explicit cancellation and malformed-frame regressions pass.

## Independent verification

- Existing Phase 38 authorization suite: **26 passed** in 11.32 seconds.
- Final expanded Phase 107 regression suite: **24 passed** in 32.15 seconds. Includes four concurrent sockets against a one-connection QueuePool, zero retained checkouts, an ordinary database query, unchanged method-aware payload, committed revocations, idle expiry/revocation, malformed handshakes, slow-client handling, and predicate parity. Initial 14-test run also passed.
- The expanded suite exercises actual HTTP vote cast and retract while a socket is open against the one-slot pool, checks the returned vote and binary tally messages, and proves zero retained connections afterward.
- After correction `85ee4f7`, independently reran the real vote/retract one-slot QueuePool regression: **1 passed** in 3.24 seconds. Source review confirms no request-session ORM reads occur after transaction release and the response/tally are already materialized. Broader compatibility and full-suite reruns are owned by the application author and lead.
- Additional passing cases cover platform administrator bypass followed by deactivation, removal of private-suborganization membership, subscription cancellation, unsolicited text/binary frames, safe database failures, handshake timeout/malformed JSON, and expiry detected after validation returns.
- Only existing Starlette/FastAPI deprecation warnings appeared.
- No production load or mutations were performed by this reviewer.
- Rendered browser QA is unavailable through the required Chrome MCP path in this session and is not claimed; no substitute browser was used.

Lead owns final full-suite, secret-scan, CI, deployment identity, and bounded production-smoke evidence. Credential provider-side status is a separate investigation and is not inferred here.
