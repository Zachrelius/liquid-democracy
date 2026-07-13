# Phase 91a — Private Backend Network

**Status:** In progress (2026-07-13)

## Goal

Close Phase 91's remaining trusted-proxy exposure by routing frontend-to-backend traffic over Railway's private network and removing the backend's public domain after the private route is proven in production. Preserve all public behavior through `https://www.liquiddemocracy.us`.

## Branch + merge

- Branch: `phase-91a/private-backend-network`
- Merge: `git merge --no-ff` to `master`, then push and verify Railway production.
- No DNS, secret, database, billing-plan, or destructive production-data changes.
- Z authorized the Railway networking/environment change on 2026-07-13.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Startup/config regression tests | Yes | Backend binds dual-stack; frontend proxy remains environment-driven and re-resolves private DNS |
| Backend targeted tests | Yes | Health, proxy/security headers, rate-limit/client-IP behavior |
| Frontend proxy smoke | Yes | `/api/`, `/ws/`, and `/uploads/` configuration remains valid |
| Frontend build | Yes | Production bundle builds cleanly |
| Railway private route | Yes | Frontend reaches backend at its `railway.internal` domain before public exposure changes |
| Backend-only redeploy | Yes | Frontend remains untouched; API, WS, and uploads recover through changed private IP without a frontend restart |
| Forwarded-IP production proof | Yes | Spoof XFF/X-Real-IP on a harmless failed login; stored audit IP must match the real caller, not either spoof |
| Public production smoke | Yes | Main-site health plus representative authenticated and unauthenticated API paths |
| Direct backend exposure | Yes | Former public backend domain is unreachable after removal |
| Browser QA | Yes | Login, representative org/proposal page, avatar/static path, clean console |
| Migration / PG smoke | No | No schema change; explicitly not required |

## Locked decisions

1. The frontend remains the sole public application gateway. Browsers continue to use same-origin `/api`, `/ws`, and `/uploads` paths.
2. The frontend Railway service receives `BACKEND_URL=http://<backend-private-domain>:8000` through a Railway reference variable. Internal traffic uses HTTP because Railway's private mesh is encrypted.
3. Uvicorn uses Railway's documented dual-stack Uvicorn bind form, preserving IPv4 compatibility where Railway supplies dual-stack networking.
4. Keep the backend public domain during the first two deploys. Remove it only after the private route passes live health and application smoke checks.
5. Nginx must perform request-time DNS resolution through the container's trusted local resolver. A startup-only resolution is forbidden because Railway private IPs change on redeploy.
6. `--forwarded-allow-ips '*'` is acceptable only behind the private-only backend boundary. The frontend normalizes the forwarded scheme/client headers. Trust of sibling services in the same Railway environment remains documented lateral-trust debt.
7. The Didit webhook stays public at `https://www.liquiddemocracy.us/api/webhooks/didit`; no provider-console change is expected.
8. Roll back by generating a new backend public domain, capturing its actual hostname, updating `BACKEND_URL`, and redeploying the frontend. Do not assume Railway will restore the former hostname.

## Sequence

1. Land dual-stack startup/config documentation and regression tests on the phase branch.
2. Merge and deploy the code while the existing public backend route remains available.
3. Change the frontend service's `BACKEND_URL` to the backend private-domain reference and redeploy the frontend.
4. Prove API, WebSocket configuration, uploads, authentication, and the Didit webhook route through the public frontend.
5. Redeploy only the backend while leaving the frontend untouched. After the private DNS TTL expires, prove API, WebSocket, and uploads still route successfully through the frontend.
6. Remove every backend public HTTP/custom domain or TCP exposure.
7. Re-run public smoke and browser QA; confirm the old backend hostname can no longer reach the app.
8. Update this spec and `PROGRESS.md` with commits, bundle hash, deployment evidence, and rollback notes.

## What is not in scope

- No Cloudflare or registrar DNS changes.
- No database networking or public Postgres proxy changes.
- No changes to application authorization, ballot privacy, or voting behavior.
- No new public API hostname.

## Closeout

Report code/config status, targeted tests and frontend build, migration/PG-smoke exemption, Railway service-variable and domain changes, frontend bundle hash, public smoke, direct-backend negative check, browser QA, branch/merge commits, and any remaining trusted-proxy debt.
