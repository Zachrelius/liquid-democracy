# Phase 98 — Layered Backup and Recovery

**Status:** Stages 0-2, 4, and 5 are complete. Stage 3's live R2 preflight and synthetic backup/restore proof passed; its one-day lifecycle deletion observation remains clock-bound and Z explicitly directed later stages to proceed without waiting for it. Railway Pro native coverage and the disposable native restore-mechanics rehearsal are proven. Stage 6 is prepared but not started: the production offsite worker remains disabled, and no production offsite backup or production-data restore has started.

## Execution results — 2026-08-14

### Stage 0 — DONE (read-only)

- The authenticated Railway UI confirms the workspace remains on Hobby. The current billing cycle is August 5–September 5. The Pro confirmation modal displayed an immediate **$20** charge; it was closed without purchasing.
- Both the Postgres and backend/uploads Backups tabs state that backups and PITR require Pro. No schedules were configured.
- Postgres and uploads each retain a 5 GB Railway volume in US East at `/var/lib/postgresql/data` and `/data/uploads`, respectively. Postgres still has the no-expiration 440 MB `Online resize to 5000MB` recovery point plus the 959 MB `Pre-Security-Patch Backup`; uploads has no backup.
- The production homepage, readiness endpoint, and combined monitor were healthy before implementation. The monitor reported database capacity below 10%, uploads at 0.03%, no recent 5xx responses, current scheduler/decision-worker heartbeats, and one alert recipient.

### Stage 1 — DONE

- Implemented the configuration-disabled worker, PG advisory lock, PG custom dump, no-follow uploads archive, versioned manifest, pinned age encryption, private immutable R2 upload/verification path, coarse `PlatformSetting` state, monitor component, isolated process supervision, and fail-closed disposable-target restore CLI.
- Added PostgreSQL 18 clients plus checksum-pinned age v1.3.1 to the container and pinned boto3/botocore 1.43.54. The worker has no object-delete path and receives no private age identity.
- Verification passed: Phase 98 suites 36 passed/2 environment skips; a separate real age v1.3.1 round-trip passed with a disposable identity and wrong-key rejection; full backend 3,034 passed/20 skipped/0 failed (Phase 97 baseline 2,998, +36); Python compile, Git Bash syntax, diff check, and scoped high-confidence secret scan passed. The remaining local symlink fixture skip is Windows privilege-specific and its no-follow behavior has independent contract coverage.
- Implementation commit `83698f1`; no-fast-forward merge `ab4356f`; Railway backend deployment `17d6ced9-bb75-46ab-84e8-d4973dfa8026` became Active. The image build verified the official age archive checksum and version assertions. The live container reports `pg_dump 18.6`, `pg_restore 18.6`, and `age v1.3.1`.
- Disabled production smoke passed: homepage title correct, readiness `ok` with database connected, monitor overall `ok`, and `offsite_backup.status=disabled` with no issues. Post-deploy GitHub production-monitor run `31815337987` succeeded and opened no incident.
- No migration was added; PG migration smoke was not required. No frontend source changed; frontend build was not required.

### Stage 2 / Gate 2 — DONE

- Z explicitly approved the Cloudflare R2 billing relationship and storage of Phase 98 production backups. R2 was activated with $0 due at checkout; usage remains subject to Cloudflare's included allowance and overage pricing.
- Created the private Standard bucket `liquid-democracy-production-backups` in Eastern North America. Public access is disabled; no public development URL, custom domain, CORS policy, or R2 Data Catalog is enabled.
- Enabled prefix locks before any production object: `production/daily/` for 7 days, `production/weekly/` for 35 days, and `production/monthly/` for 100 days. Enabled lifecycle deletion after 8, 36, and 101 days on those prefixes respectively.
- Generated a dedicated production age identity. Z saved and verified password-manager and offline flash-drive copies by exact private-identity/public-recipient readback. Railway received only the public recipient. The temporary workstation identity/tooling directory and clipboard copy were removed after verification; the private identity was never stored in Railway, R2, GitHub, the repository, or application logs.
- Created `Phase 98 production backup writer` with Object Read & Write access scoped only to this bucket. It can read, write, and list objects but cannot administer buckets. Its one-time values were transferred directly into Railway secret variables and not written to the repository or a local credential file.
- Applied all 10 `OFFSITE_BACKUP_*` variables to the Railway backend while explicitly retaining `OFFSITE_BACKUP_ENABLED=false`. Deployment `dabaa9dc-9987-43f7-b88e-ca4440634da0` became Active.

### Stage 3 — PARTIAL (all immediately runnable checks passed)

- Live production preflight passed without dumping or uploading: database and upload-volume reads, advisory lock, temporary-space check, age recipient parsing, bucket connectivity, PostgreSQL client/server compatibility, and R2 credentials all succeeded. The container reported `pg_dump 18.6`, `pg_restore 18.6`, and `age v1.3.1`.
- Immediately after preflight, Cloudflare still showed a 0-byte bucket with no objects and Public Access disabled. The production monitor remained overall `ok` with `offsite_backup.status=disabled` and no offsite issue.
- Added an enabled one-day lifecycle rule for `test/phase98-synthetic-20260814/`, then used a short-lived isolated Railway `postgres:18` service containing one known synthetic user and one 33-byte upload fixture. No production database or production uploads path was read.
- The full pipeline produced one 194,792-byte ciphertext object under the synthetic `test/` prefix. HEAD verification found exactly the allowed metadata keys: artifact format version, creation time, encrypted length, and ciphertext SHA-256. No plaintext object was uploaded.
- The standalone restore CLI downloaded and verified ciphertext SHA-256 `630288a97a1a0ad32d3a5a15788bcc405ad8a398bc9759fe233002f71a909bc4`, decrypted with a disposable synthetic identity, restored into a separate empty PostgreSQL 18 database, and verified Alembic head `c5d6e7f8a9b0`, the known user count, and a byte-for-byte upload match. It left zero decrypted `offsite-restore-*` directories.
- Both disposable databases, all synthetic source/restore/key files, the transient credential, and the temporary Railway service were removed. Only the encrypted test object remains so Cloudflare lifecycle deletion can be observed. Its dashboard timestamp is August 14, 2026 at 12:45:50 EDT; deletion observation is **NOT YET DUE** before August 15, 2026 at 12:45:50 EDT and may be eventually processed after that boundary.

### Stage 4 / Gate 4 — DONE

- Z activated Railway Pro and explicitly directed Stage 4 to continue without waiting for the clock-bound R2 lifecycle observation. The authenticated workspace now reports **Pro** active as of August 14, 2026. The current billing cycle is August 5–September 5; the billing history records a **$10.73** usage-based subscription invoice on August 14, while the usage page reports the ongoing **$20.00 Pro plan fee** with **$20.00 included usage**. The downgrade/keep decision is due before the September 5 cycle boundary.
- Enabled and re-opened the schedule dialogs to verify all three selections are checked on both `postgres-volume` and `user-uploads`: daily every 24 hours retained 6 days, weekly every 7 days retained 1 month, and monthly every 30 days retained 3 months.
- Created one manual backup on each production volume without invoking Restore. PostgreSQL recovery point `2026-08-14 14:28` reports **991 MB** referenced size; uploads recovery point `2026-08-14 14:30` reports **150 MB**. The existing PostgreSQL manual points remain `Pre-Security-Patch Backup` at **959 MB** and `Online resize to 5000MB` at **440 MB**.
- Railway's August 5–September 5 usage ledger currently reports **6,284.48 minutely GB** of Backup usage at **$0.000003/GB/minute**, costing **$0.0218** cycle-to-date. The four visible references total 2.54 GB, which projects to about **$0.34 per 31 days** if the footprint stays flat; scheduled retention will grow that footprint, while Railway's incremental storage behavior may reduce the realized amount. The workspace's overall current estimated bill is **$4.47**.
- PostgreSQL PITR remains off because Stage 4 requires native volume schedules, not a production redeploy for PITR. No production Restore control was used. After the changes, the combined production monitor remained `ok` with no issues, both capacity checks healthy, and `offsite_backup.status=disabled` as intended.
- No continuity assumption is made for these Pro-created backups after downgrade. Their accessibility must be treated as unproved unless Railway documents or a later safe observation establishes it.

### Stage 5 — DONE

- Created a disposable Alpine 3.21 service and 5 GB Railway volume in the production project/environment, named only for the Phase 98 native-restore test and mounted at `/phase98-data`. The service and all generated replacement volumes had unique non-production identifiers; the production service and volume identifiers were checked before every restore and cleanup action.
- Wrote a synthetic marker plus structured JSON fixture and recorded their SHA-256 values. The first immediate backup (`2026-08-14 14:43`, 790 MB referenced size) restored the directory entries but produced zero-byte files even though the pre-backup reads and hashes were correct. The result stayed entirely inside the disposable service. Repeating the rehearsal after an explicit filesystem `sync` and settle interval produced backup `2026-08-14 14:46` (790 MB).
- Mutated both flushed fixtures to distinct values and hashes, restored the second backup, reviewed Railway's staged replacement-volume change, and deployed it only to the disposable service. The restored marker, JSON nonce, and both SHA-256 values matched the originals exactly: marker `e9bef2813c3b32370407228b98e7df4f5d529969526ac31011a5e99f7be6b2c5`; fixture `69d50cda9faa680d289636dabbd5a70e1388e9e095f1f92e4850a7533ec1afa5`.
- Treat an explicit application quiesce/filesystem flush and settle interval as a required native on-demand-backup operator step. The rehearsal proves Railway's staged replacement-volume mechanics and also proves that an immediate snapshot must not be assumed to have captured recently buffered writes.
- Re-read, without clicking Restore, the production recovery points: PostgreSQL 991 MB, 959 MB, and 440 MB; uploads 150 MB manual plus a new 150 MB daily scheduled point. All are plausible relative to their production volumes.
- Deleted and applied the destructive-change confirmation for exactly four disposable resources: the test service, its original test volume, and the two replacement volumes generated by the rehearsals. The project canvas then contained no Phase 98 test resource; backend, PostgreSQL, and frontend remained Online.
- Railway usage moved from 6,284.48 to 6,299.19 minutely GB of Backup usage and from $0.0218 to $0.0219 cycle-to-date during the rehearsal: a displayed delta of 14.71 minutely GB and $0.0001. Current usage remained $2.04 and the workspace estimate remained $4.47.

### Stage 6 preparation — READY, NOT STARTED

- Re-ran the non-writing production preflight after Stage 5 cleanup. It passed at August 14, 2026 18:52 UTC with `pg_dump`/`pg_restore` 18.6, age 1.3.1, database/uploads reads, advisory lock, free-space check, public recipient parsing, and R2 connectivity. It did not dump or upload data.
- The combined production monitor remained `ok` with zero issues, healthy capacity/worker components, and `offsite_backup.status=disabled`. No production object exists and `OFFSITE_BACKUP_ENABLED` remains false.
- The private production age identity is **not needed to enable the worker, create the encrypted production object, or verify its ciphertext metadata/lock/lifecycle**. It is needed only after those steps pass, immediately before the isolated Stage 6 download/decrypt/restore rehearsal. At that checkpoint Z should place the identity in a temporary local file outside the repository and say only that the file is ready; never paste the key into chat or store it in Railway, R2, GitHub, repository files, logs, email, or Google Drive. The temporary operator copy is removed after the disposable restore evidence and cleanup are complete; the password-manager and offline originals remain.

### Remaining gates

- **Stage 3 — PARTIAL only for the clock-bound lifecycle observation.** The preflight and complete synthetic object/restore/cleanup proof passed. Z explicitly waived waiting for this observation before Stage 4. Confirm the one-day lifecycle removed the synthetic object after its due time, then remove the temporary synthetic lifecycle rule if no longer needed.
- **Stage 4 / Gate 4 — DONE.** Pro is active; both native schedule matrices and both new manual recovery points are verified above.
- **Stage 5 — DONE.** The disposable native replacement-volume restore and cleanup proof passed; production Restore controls were never invoked.
- **Stages 6–7 — NOT STARTED.** No production offsite backup, isolated production-data restore rehearsal, or downgrade-continuity proof has run.
- Phase 98 is deliberately **not complete**. The native restore requirement is satisfied; completion still requires the isolated production-data offsite restore required by Stage 6.

## Goal

Establish and prove two complementary recovery layers before a real pilot deposits irreplaceable data:

1. Railway-native volume backups for fast same-project recovery while the workspace is on Pro.
2. A daily encrypted PostgreSQL-and-uploads backup stored in a private Cloudflare R2 bucket that continues operating when the workspace returns to Hobby.

Use one intentionally bounded Pro billing cycle to configure and test the native layer, prove both restore paths without replacing production data, and leave the offsite layer active on Hobby at an expected current storage cost of $0/month. Do not start the paid month until all code, local tests, encryption-key custody, and the R2 destination are ready.

## Branch + delivery

- Branch: `phase-98/layered-backup-recovery`
- Merge: no-fast-forward to `master`; push and verify the deployed backend before any live backup is enabled.
- The implementation is configuration-disabled by default. Merging code must not start a production backup or require secrets that are not yet provisioned.
- Z must explicitly approve the Railway Pro checkout amount before the plan is changed.
- Z must explicitly approve enabling Cloudflare R2 if its checkout flow creates a billing relationship, even when forecast usage is within the free allowance.
- Never restore over, replace, wipe, resize, detach, or otherwise mutate the production Postgres or uploads volumes during verification.
- Never copy an unencrypted production backup to GitHub, the repository, Google Drive, email, logs, or a publicly reachable location.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Current Railway backup entitlement check | Yes | Read-only dashboard check on Hobby before requesting an upgrade; record what the live UI offers |
| Backup configuration unit tests | Yes | Disabled-by-default, required settings, time calculation, retention class, fail-closed validation |
| Artifact/manifest unit tests | Yes | PostgreSQL dump, uploads archive, schema/version metadata, counts, checksums, no symlink traversal |
| Encryption tests | Yes | Plaintext never uploaded; invalid/missing recipient aborts before network write; round-trip with disposable test key |
| Object-store tests | Yes | Private bucket, unique immutable keys, expected prefix, size/metadata verification, failure cleanup |
| Concurrency/interruption tests | Yes | PostgreSQL advisory lock, redeploy overlap, subprocess failure, SIGTERM, partial-object behavior |
| Monitoring tests | Yes | Success state, failure streak, stale/missing backup, disabled state, public-safe health payload, email incident/recovery |
| Restore-tool safety tests | Yes | Requires explicit non-production target; rejects production target; checksum and Alembic validation |
| Container toolchain verification | Yes | Container reports PostgreSQL 18-compatible `pg_dump`/`pg_restore` and a pinned `age` binary |
| Targeted backend suites | Yes | Startup, settings, monitoring, scheduler/worker, uploads, database, email alerts |
| Full backend suite | Yes | No unexplained regressions |
| Frontend build | No | No frontend source change planned |
| Migration / PG smoke | No | Reuse `PlatformSetting`; no schema migration planned |
| Disabled production deploy smoke | Yes | Homepage/readiness/monitor remain healthy before secrets or enable flag are set |
| R2 live backup proof | Yes | Encrypted object exists; expected metadata/size; no plaintext object; no secret in logs |
| Offsite isolated restore rehearsal | Yes | Temporary PostgreSQL 18 target + temporary uploads directory; representative counts/files verified; temporary data removed |
| Railway native schedule proof | Yes | Daily + weekly + monthly on Postgres and uploads; initial manual backup visible |
| Railway native restore-mechanics proof | Yes | Disposable test service/volume only; never production volumes |
| Post-downgrade continuity proof | Yes, when downgrade occurs | Offsite backup succeeds on Hobby; native schedule state and retained-backup accessibility recorded honestly |

## Suggested team structure

- **Lead:** owns gates, provider configuration, cost evidence, production sequencing, and closeout.
- **Backend/operations developer:** builds the worker, artifact/encryption/upload path, restore tooling, container toolchain, and tests.
- **QA/operations teammate:** independently verifies the disabled deploy, R2 object/lock/lifecycle configuration, both safe restore rehearsals, production health, and no-secret evidence.
- No frontend developer is needed unless the team finds an unexpected user-facing surface.

## Sequence and approval gates

### Stage 0 — Reconfirm live provider facts, read-only

1. Open the production Postgres and backend services' **Backups** tabs while the workspace remains on Hobby.
2. Record whether manual backups, daily/weekly/monthly schedules, and PITR are currently available or Pro-gated. Railway's public documentation has been inconsistent; the authenticated live UI is authoritative for this workspace.
3. Record the billing-cycle renewal date and the exact Pro checkout amount, but do not upgrade.
4. Reconfirm both volumes, mounts, capacities, current used sizes, and the existing no-expiration Postgres resize snapshot.
5. Reconfirm homepage, readiness, combined monitor, and current deployment state.

**Gate 0 outcome:** If native backups are unexpectedly available on Hobby, configure nothing yet; revise the cost step and retain all remaining safety work. If they remain Pro-gated, continue through Stages 1–3 before asking Z to upgrade.

### Stage 1 — Implement the offsite path, disabled

Build, test, document, and deploy the complete offsite path with `OFFSITE_BACKUP_ENABLED=false`. This stage must not require live R2 credentials and must not touch production data beyond ordinary read-only health checks.

### Stage 2 — Prepare encryption custody and R2

1. Generate a dedicated `age` keypair. Railway receives only the public recipient. The private identity is never stored in Railway, R2, GitHub, the repository, or application logs.
2. Z records the private identity in a password-manager secure note and one second offline recovery location. Do not proceed until the saved key has been read back successfully.
3. Create a dedicated private R2 bucket with no public development URL, custom domain, CORS exposure, or unauthenticated listing.
4. Configure bucket-scoped S3 credentials only for that bucket. Store the production credential only as Railway secret variables. Use a separate read-only credential for restore rehearsals where practical.
5. Configure prefix-specific bucket locks and lifecycle rules before the first production object is uploaded:
   - `daily/`: minimum 7-day lock; expire after 8 days.
   - `weekly/`: minimum 35-day lock; expire after 36 days.
   - `monthly/`: minimum 100-day lock; expire after 101 days.
6. Record Cloudflare's displayed pricing/free allowance and any checkout commitment. No public bucket access.

**Gate 2 — Z action:** Explicit approval is required before enabling an R2 billing relationship or storing production data in the bucket.

### Stage 3 — Production dry run, still on Hobby

1. Deploy the disabled implementation.
2. Verify the live container tool versions.
3. Run a production **preflight** that checks tool availability, upload-volume readability, database connectivity, R2 connectivity, encryption recipient parsing, temporary free space, and the advisory lock. It must not create a database dump or upload an object.
4. Exercise the complete pipeline against synthetic local/test data and the real R2 bucket under a `test/` prefix. Restore that synthetic object and then let its short test lifecycle expire.
5. Confirm monitoring reports `disabled` rather than stale/error while the production enable flag is false.

**Gate 3 outcome:** Only after all checks pass is the paid Railway month useful.

### Stage 4 — Railway Pro approval and native coverage

Present Z with:

- the exact checkout amount;
- renewal/effective dates;
- live confirmation that native backups remain Pro-gated;
- Stage 1–3 results;
- the planned date for the downgrade decision.

**Gate 4 — Z action:** Z explicitly approves the observed Pro charge. The team may perform the portal change through an authenticated browser after that approval; otherwise Z performs the single plan-change click.

After Pro activates:

1. Enable daily + weekly + monthly schedules on both `postgres-volume` and `user-uploads`.
2. Create one manual backup of each volume.
3. Record timestamps, backup identifiers, referenced/incremental sizes, retention, and current projected storage cost.
4. Do not assume Pro-created backups remain accessible after downgrade; Railway does not currently document that contract clearly.

### Stage 5 — Prove native restore mechanics safely

Railway volume restores are same-project/same-environment operations and stage a replacement mounted volume. Do not run that flow against a production volume merely for testing.

1. Create a disposable low-cost test service and volume in the same project/environment.
2. Write a marker file and a small structured fixture.
3. Back up the disposable volume, alter the fixture, restore the backup, deploy the staged test-only change, and verify the original fixture returns.
4. Delete only the disposable service/volume after evidence is recorded and absolute resource identifiers are checked.
5. For production volumes, verify that backups exist and have plausible sizes; do not click through a production restore.

### Stage 6 — Enable, run, and restore the offsite production backup

1. Add the production secrets and set `OFFSITE_BACKUP_ENABLED=true` only after native coverage is visible.
2. Trigger one manual run through the same core code path the scheduler uses.
3. Verify an encrypted immutable object exists in `daily/`; if the calendar classifies the run as weekly/monthly, verify the corresponding additional key(s).
4. Confirm the bucket lock and lifecycle expiration metadata apply.
5. Download with a restore-only credential to a local isolated temporary directory, decrypt with the offline identity, verify all checksums, and restore into a disposable PostgreSQL 18 database.
6. Verify Alembic head plus representative table counts, organization/member/proposal/vote relationships, and selected non-sensitive aggregate invariants. Never print row contents, emails, ballot data, tokens, or private organization text.
7. Extract uploads to a disposable directory and verify file counts, sizes, checksums, and expected avatar/logo directory structure without opening or displaying private files.
8. Destroy the temporary database, decrypted artifacts, extracted files, and plaintext dumps after evidence is recorded. Keep the private identity.
9. Allow or deliberately schedule one normal worker-driven run and verify its success timestamp independently of the manual trigger.

### Stage 7 — Return to Hobby if no pilot is active

1. Record the renewal date and set a user-visible decision checkpoint several days before it. Do not create an automation unless Z requests one.
2. If Z confirms there is still no committed pilot, request/perform the downgrade. Railway says a downgrade becomes effective at the beginning of the next billing cycle.
3. After Hobby becomes effective, record what happened to native schedules and existing native backups without assuming retention/access.
4. Trigger or observe another successful encrypted offsite backup on Hobby and repeat a lightweight object/monitor verification.
5. If a pilot commits before renewal, Z may keep Pro; this is a business decision, not an automatic code action.

## Locked decisions

1. **The two layers are independent.** Railway Pro is required only for Railway's native backup feature if the current UI still gates it. The offsite worker uses capabilities already present on Hobby: the backend's `DATABASE_URL`, read access to `/data/uploads`, background compute, and outbound HTTPS. Downgrading does not disable that application code.
2. **Native first at live-enable time.** Code and R2 preparation happen first, but the initial production-data offsite run waits until Railway-native coverage is visible. This gives the new pipeline a same-provider safety net during its first live exercise.
3. **Separate process, not the request or digest loop.** A dedicated `offsite_backup_worker.py` child process performs blocking dump/archive/encryption/upload work. It must not block Uvicorn requests or the hourly digest scheduler. `start.sh` launches and terminates it only when enabled.
4. **PostgreSQL-version compatibility is explicit.** The backend image must contain PostgreSQL 18-compatible `pg_dump` and `pg_restore`. CI/container verification fails if the client major version is older than the production server major version.
5. **Standard cryptography, no custom encryption design.** Use a pinned `age` implementation and a dedicated recipient. The production environment has no decryption key.
6. **Private, immutable destination.** R2 remains private. Prefix bucket locks prevent deletion/overwrite for the retention window even if the application credential is compromised. Lifecycle rules, not the application, perform ordinary expiration.
7. **No delete permission is exercised by the worker.** The worker only creates uniquely named objects and verifies them. It never prunes or overwrites objects. Retention is a bucket policy.
8. **One logical backup run, up to three retention keys.** Generate and encrypt one artifact per run. Upload it under `daily/` every day, additionally under `weekly/` on the configured weekday, and under `monthly/` on the configured day. Never regenerate three plaintext copies.
9. **Daily RPO, best-effort recovery target.** Internal operating target: no more than 24 hours of offsite data loss and a four-hour operator-assisted restore objective at current scale. This is not a public SLA or contractual promise.
10. **Production restore is prohibited in this phase.** Restore rehearsals target disposable resources only. A real incident requires a separate incident decision based on the runbook.
11. **No migration.** Backup state uses `PlatformSetting`; no new table is justified at this scale.
12. **Fail visibly but do not take the site down.** Backup failures update monitoring and alert administrators; they never crash application startup, HTTP handling, digest processing, or voting workers.

## Offsite artifact contract

Each encrypted bundle contains:

- `manifest.json`
- `database.dump` — PostgreSQL custom-format, internally compressed
- `uploads.tar.gz`

The manifest format is versioned and contains only what is necessary for restoration and verification:

- artifact format version;
- environment identifier (`production`) and application commit SHA;
- UTC start/completion timestamps and backup window duration;
- PostgreSQL server/client versions and database name without credentials/host;
- Alembic current/head revisions;
- dump/archive byte sizes and SHA-256 checksums;
- uploads file count and aggregate bytes;
- representative table row counts selected for structural verification;
- retention classes uploaded (`daily`, `weekly`, `monthly`);
- encryption recipient fingerprint, never the private identity.

The bundle must not include `.env`, application secrets, logs, temporary files, caches, source code, or files outside the resolved upload root. Upload archiving must reject symlinks and must not follow them.

Object keys are unique and non-overwriting, for example:

`production/daily/2026/08/liquid-democracy-20260814T110000Z-<short-sha256>.tar.age`

Only the timestamp, format version, encrypted byte length, and ciphertext SHA-256 may appear as R2 object metadata. The detailed manifest remains encrypted.

## Backend implementation requirements

### B1 — Configuration

Add validated settings with disabled-safe defaults:

- `OFFSITE_BACKUP_ENABLED=false`
- `OFFSITE_BACKUP_TIME_UTC=11:00`
- `OFFSITE_BACKUP_S3_ENDPOINT`
- `OFFSITE_BACKUP_S3_REGION=auto`
- `OFFSITE_BACKUP_BUCKET`
- `OFFSITE_BACKUP_PREFIX=production`
- `OFFSITE_BACKUP_ACCESS_KEY_ID`
- `OFFSITE_BACKUP_SECRET_ACCESS_KEY`
- `OFFSITE_BACKUP_AGE_RECIPIENT`
- `OFFSITE_BACKUP_STALE_AFTER_SECONDS=129600` (36 hours)
- optional instance/replica selector matching the project's existing single-instance worker conventions

When disabled, missing secrets are valid. When enabled, missing/placeholder/invalid values abort the backup worker loudly without aborting the web application.

### B2 — Dedicated worker and concurrency

- Add a worker with manual `--once`, non-writing `--preflight`, and long-running scheduled modes.
- Use `subprocess` argument arrays with `shell=False`; never interpolate secrets into a shell command.
- Use a stable PostgreSQL advisory lock so overlapping deploys/replicas cannot run simultaneous backups.
- Write artifacts under a fresh `0700` temporary directory on ephemeral storage. Check available space before beginning.
- On SIGTERM, terminate children, abort multipart upload if applicable, remove plaintext/ciphertext temporary files, update failure/interrupted state where possible, and exit promptly.
- `start.sh` must forward shutdown signals to the backup worker alongside existing children. An unexpected backup-worker exit must not kill Uvicorn; unlike the load-bearing decision worker, backup failure degrades monitoring rather than site availability.

### B3 — Dump, archive, manifest, and encryption

- Invoke PG18-compatible `pg_dump --format=custom` against `DATABASE_URL` without exposing the URL in process/log output.
- Capture server/client versions and Alembic revisions before finalizing the manifest.
- Archive only the configured uploads root. Reject symlinks and special files; include regular files/directories only.
- Compute checksums before bundling.
- Encrypt the complete bundle with `age` to the configured public recipient.
- Remove every plaintext artifact before upload begins where feasible; at minimum, plaintext must be removed immediately after successful encryption and before any retry sleep.
- Confirm the ciphertext cannot be opened without the test identity in integration tests.

### B4 — R2 upload

- Use a pinned S3-compatible client library.
- Upload only ciphertext, with private ACL/default bucket privacy.
- Generate daily/weekly/monthly keys according to UTC calendar rules and never overwrite an existing key.
- Use bounded timeouts and retries. A retry must be safe after an uncertain network outcome: HEAD the exact unique key before retrying.
- Verify object size and recorded ciphertext checksum metadata after upload.
- Do not list or log unrelated bucket contents.

### B5 — State and monitoring

Persist coarse state under one versioned `PlatformSetting` key:

- enabled/disabled;
- last attempt/success/failure/interruption UTC timestamps;
- consecutive failure count;
- last encrypted size;
- last retention classes;
- last object-key hash or basename only, not credentials/full endpoint;
- last duration;
- sanitized failure category, never a raw exception or command output.

Extend `/api/health/monitor` with `offsite_backup`:

- `disabled` when intentionally disabled;
- `ok` after a recent verified success;
- `warning` during startup/first-run grace;
- `error` after a failed enabled run or success age over 36 hours.

The existing Phase 97 incident email and GitHub external monitor must carry the new component through their current deduplicated incident/recovery behavior without exposing bucket names, object keys, credentials, database URLs, or private data.

### B6 — Restore tooling

- Add a standalone restore/verify script that is never called by application startup or an HTTP route.
- Require a target database URL plus a literal typed confirmation naming a disposable target.
- Reject the current `DATABASE_URL`, the production database host/name, and ambiguous/missing targets.
- Download through a supplied restore credential, verify ciphertext checksum, decrypt through a supplied local identity path, verify the manifest and member checksums, and run `pg_restore` into the empty target.
- Validate Alembic revision and structural counts. Extract uploads only to an empty caller-supplied directory.
- Provide `--verify-only` and `--keep-temporary` (default false). Normal completion securely removes ordinary temporary files to the extent supported by the filesystem; documentation must not claim guaranteed forensic erasure on SSDs.

## Security and privacy requirements

- Never put the private `age` identity in Railway. This is what makes stolen R2/application credentials insufficient to read backups.
- Scope the R2 token to the one backup bucket. Do not use a Cloudflare account-wide Admin token in Railway.
- Configure bucket locks before live upload. Locks must cover the exact prefixes the worker writes.
- Keep R2 public access, custom domains, and browser access disabled.
- Secret scans must include new docs, tests, fixtures, shell scripts, and example env files.
- Tests use synthetic credentials and generated disposable keys only.
- Logs may contain timestamps, durations, byte counts, retention class, and sanitized categories; no emails, row contents, filenames from private uploads, database URLs, S3 endpoints containing account IDs, access keys, or command stderr that may echo secrets.
- The restore rehearsal is treated as production-data access. Work locally in an isolated temporary environment, do not display content, and delete decrypted material afterward.

## Cost model and guardrails

Recent observed combined data volume has ranged from approximately 0.306 GB to 0.586 GB. Fourteen to sixteen retained full encrypted copies would occupy approximately 4.3–9.4 GB before allowing for database compression. Cloudflare R2 Standard currently includes 10 GB-month and ample operations at no charge; expected present offsite storage cost is therefore $0/month, not a guarantee.

- Alert Z before any configuration likely to exceed the free allowance.
- Use Standard storage so the free tier applies.
- Record actual encrypted object sizes after the first run and recalculate the 30-day projection.
- Railway Pro changes the minimum monthly commitment from $5 to $20. Treat the experiment as one billing cycle unless Z chooses to keep it.
- Temporary restore/test services should be removed promptly and are expected to remain inside Pro's included resource usage; record actual usage rather than claiming zero.

## Documentation and closeout

Update:

- `DEPLOYMENT.md` with architecture, configuration, manual run, monitoring, restore, key loss, credential rotation, Railway native restore, downgrade, and incident procedures.
- `PROGRESS.md` with completed/deferred stages, exact costs, evidence, and current layer status.
- `future_improvements_roadmap.md` only if a remaining backup follow-up belongs in the forward queue.
- This spec's status/results sections as execution progresses.

Closeout must report:

- per-stage DONE / blocked / deferred;
- all user approvals and actual plan/provider changes;
- current Railway plan and renewal date;
- native schedules/backups and observed incremental sizes;
- offsite schedule, last success, ciphertext size, projected monthly storage/cost, bucket lock/lifecycle proof;
- native disposable restore result;
- offsite isolated restore result and cleanup evidence;
- monitoring/alert result;
- tests and count delta;
- no-migration/PG-smoke status;
- files changed and commits/merge;
- Railway deployment ID, production health, and external monitor result;
- what happens next if the workspace downgrades or a pilot commits.

Do not mark Phase 98 complete merely because backups were created. Completion requires an isolated successful offsite restore and a safe native restore-mechanics rehearsal. If the Pro month remains active at closeout, label post-downgrade continuity as **NOT YET DUE**, record the exact checkpoint, and do not imply it will happen in the background.

## Out of scope

- Point-in-time recovery configuration beyond recording whether Pro exposes it.
- Multi-region active database replication.
- Migrating uploads to R2 as their primary serving store.
- Fully automated destructive restoration.
- Public backup/recovery SLA or legal guarantee.
- Backing up demo data more frequently than the production dataset; the checked-in demo bibles remain the primary demo reconstruction source.
- Keeping Pro indefinitely without a separate Z decision.

## References

- Prior decision and inventory: `phase92_pilot_readiness_and_operational_recovery_spec.md`
- Railway backups: https://docs.railway.com/volumes/backups
- Railway plans: https://docs.railway.com/pricing/plans
- Cloudflare R2 pricing: https://developers.cloudflare.com/r2/pricing/
- Cloudflare R2 API tokens: https://developers.cloudflare.com/r2/api/tokens/
- Cloudflare R2 bucket locks: https://developers.cloudflare.com/r2/buckets/bucket-locks/
- Cloudflare R2 lifecycle rules: https://developers.cloudflare.com/r2/buckets/object-lifecycles/
