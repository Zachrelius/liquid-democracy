# Phase 52c — Didit Payload Capture (instrument for dedup)

**Status:** Spec + dispatch. Written 2026-06-03, after Phase 52a shipped + live-verified.

Reading order: this doc; `phase52a_closeout.md` (the NULL-nullifier finding); the shipped `backend/verification_provider.py` (the mapper a LATER phase corrects); `id_verification_arc_backlog.md`.

**This phase runs start-to-finish with no Z intervention.** It ends at a clean boundary: a required Z-action (Z + spouse complete real verifications) is the phase boundary, so the mapper-correction work that depends on those verifications is a SEPARATE phase (52d), dispatched only after the Z-action is done. Per the phase-boundary rule: a Z-wait never sits inside a phase.

## Why this phase exists

Phase 52a shipped the nullifier column, partial-unique index, and collision logic, but every real Didit verification lands on `identity` with a NULL nullifier — so `identity_unique` (the one-human-one-account Sybil-resistance guarantee, the capability most aligned with a delegation platform) is built-but-dormant. Reading the shipped `verification_provider.py` revealed the cause is twofold, and BOTH need a real Didit payload to fix correctly:

1. **The dedup payload shape is unconfirmed.** `_extract_nullifier` / `_decision_passed_1n_dedup` probe for `face_search` / `identity_dedup` / `biometric_dedup` blocks with GUESSED key names, never validated against a real payload. 52a's only real verification carried no dedup block — expected, since it was the first face in the workspace, so 1:N had an empty set to match against.
2. **A latent precedence bug** in `map_decision_to_state` (address and uniqueness treated as mutually exclusive rather than ordinal rungs). Fixed in 52d, but noted here for context.

Before either can be fixed against ground truth, we need a real captured payload. **This phase is solely about safely capturing that payload.** It changes no verification behavior.

## Goal

Instrument the webhook receiver to capture the full Didit `decision` payload — PII-safe — so the next phase can correct the mapper against the real key structure instead of guesses. Deploy. Prove the capture fires and redacts. Then STOP — the phase is complete; Z + spouse verifying is the next phase's precondition, not this phase's work.

## Branch + merge
`phase-52c/didit-payload-capture`. `--no-ff` to master per CLAUDE.md.

## Migration head
Recommended log-only mechanism (below) needs NO migration. If a capture table is used instead, confirm `alembic heads` shows a single head first (52a left `e0a1b2c3d4f5`), hex-prefix revision id, multi-head → STOP.

## Clusters

### C1 — PII-safe payload capture
Add capture of the full Didit `decision` payload at the webhook receiver so the next phase can correct the mapper against ground truth. **Hybrid-pattern constraint is absolute:** never persist document images, selfies, raw names, raw addresses, document numbers, or birthdates. Capture ONLY:
- the payload **structure** (the set of keys / nested key-paths present), and
- the **dedup-relevant non-PII fields** — feature status strings (`approved`/`declined`/`review`), presence/absence of a dedup or face-search block, and any opaque handle/id values. If any candidate handle looks like it embeds PII, redact and log only its shape (type + length).

Mechanism — **recommend (i):**
- **(i)** a structured log line at the webhook receiver dumping a **key-redacted skeleton** of the payload (every leaf string that could be PII replaced by its type+length; status enums + opaque ids kept), readable in Railway logs. No migration, nothing to tear down.
- **(ii)** a short-lived `VerificationPayloadCapture` table storing the same redacted skeleton, readable via a platform-admin endpoint, auto-purging after N days. ONLY if logs prove insufficient — and it MUST be torn down (or demo-gated) before the next phase closes; don't leave a payload-capture table in prod.

### C2 — redaction safety test (load-bearing)
A unit test feeds a synthetic payload containing fake PII (name, address, document number, DOB) through the capture/redaction function and asserts NONE of those PII strings appear in the captured output. This is the gating safety test for the whole phase — capture must be proven PII-safe before it ever sees a real ID.

### C3 — deploy + confirm capture fires
Deploy. Confirm:
- the webhook still processes normally — **state writes are unchanged; this phase adds capture, changes no behavior** (an ungated verification still lands `identity` exactly as before);
- the capture mechanism emits the redacted skeleton when a webhook arrives. Z's existing record can't retroactively produce a payload, so confirm via a synthetic/test webhook (the Didit console "Test Webhook" button, or a unit-level invocation) that capture fires + redacts. The REAL payloads come from the next phase's Z-action.

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Redaction safety test | ✅ | Synthetic PII in → zero PII out. The phase's load-bearing safety test. |
| Capture-fires confirmation | ✅ | Redacted skeleton emitted on a test webhook. |
| Behavior-unchanged regression | ✅ | A verification still writes the same state as pre-phase; the 420-test adjacent sweep stays green. This phase must be a pure-additive instrument. |
| Serializer guard intact | ✅ | Nullifier + attestation_id still not on UserOut. |
| Migration cycle + PG smoke | ⚠️ Conditional | Only if mechanism (ii) table used. Log-only → N/A, state so. |
| `bash start.sh` prod-mimic | ❌ | No start.sh / worker / Dockerfile / alembic-ordering change. |
| Deploy + demo reset post-deploy | ✅ | Observed. Demo personas still log in. |

## Sequence
C2 (redaction test — write it alongside C1 so capture is never deployed unproven) → C1 (capture) → C3 (deploy + confirm). Phase ends at C3. Do NOT proceed to mapper changes — that's 52d, gated on the Z-action.

## Team
Continuing dev team. Lead runs the deploy + closeout. Backend dev owns capture + redaction. QA owns the redaction test + the capture-fires confirmation.

## Invariants
- **Hybrid pattern absolute:** capture is PII-safe; the redaction test proves it.
- **Pure-additive:** no verification behavior changes. Adjacent sweep proves it.
- **demo_stub sealed / nullifier internal / provider-agnostic:** unchanged from 52a; nothing here touches them.

## Closeout must report
The redaction safety test result; the capture mechanism chosen (i log-only or ii table); confirmation capture fires + redacts on a test webhook; behavior-unchanged evidence (adjacent sweep green, a verification still writes the same state); and the explicit handoff line: **52c complete; 52d (mapper correction + collision proof) is gated on the Z-action — Z + spouse verifying on this instrumented build.**

## Z-action items
- **None to dispatch or run this phase.** This phase is pure instrumentation.
- **After this ships:** Z will be walked through the verification sequence (Z + spouse) in chat — that is 52d's precondition, NOT part of 52c.
