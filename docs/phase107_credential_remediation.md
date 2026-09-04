# Phase 107 — Didit credential remediation

## Current status

September 4, 2026: historical source exposure confirmed; provider-side revocation
status **UNKNOWN**. Z reports being "95% confident" it was rotated previously,
but does not recall the details. Confirm that recollection using provider-side
metadata before deciding whether another rotation is needed. No suspected
credential was printed, invoked, rotated, or
tested. Current-source removal is complete in this pass; old Git commits and
existing copies may still contain the value. Removal does not revoke a key.

Evidence: `phase52a_handoff_to_z.md:40` contained a literal API credential;
Phase 102a spec section on operational watch-outs and `PROGRESS.md` Phase 102a
recorded the exposure as unremediated. Phase 102b operational notes kept it a
separate follow-up. No later revocation record was found in repository documents
at reviewed revision `1a8aead`. This is not evidence the key is currently active.

## Provider and deployment actions — NOT STARTED

1. An authorized Didit administrator should inspect key metadata and revocation
   history through the provider console without copying values into chat, logs,
   tickets, source files, or command arguments. Review available usage/audit
   metadata for unexpected activity. Do not test the historically exposed key.
2. If revocation cannot be established, treat it as exposed. Prepare a replacement
   through the provider, update Railway backend `DIDIT_API_KEY` using its secure
   variable interface, update authorized local secret stores, and deploy. Revoke
   the exposed key promptly after replacement verification; if misuse is evident,
   revoke immediately and accept temporary identity-verification disruption.
3. Verify the exact backend deployment and readiness, then verify replacement-key
   authentication using a provider-supported nonmutating check. Do not create
   identity-verification sessions or incur verification charges merely to smoke
   test. Check application error monitoring for authentication and purge failures.
4. All three provider operations use this key: session creation, decision fetch,
   and session purge (`backend/verification_provider.py`, `create_session`,
   `retrieve_session_decision`, `delete_session`). Preserve workflow configuration.
   Webhook signing uses the separate `DIDIT_WEBHOOK_SECRET`; do not rotate it
   unless there is separate evidence or a deliberate coordinated migration.
5. Record provider key identifier, replacement deployment identity, revocation
   timestamp, and verification outcome without credential values. A safe rollback
   is another replacement key or temporary verification unavailability; never
   restore the exposed key.
6. Decide separately whether repository history cleanup is warranted. It requires
   explicit coordination for shared-history rewriting and cannot erase third-party
   clones. No force-push/history rewriting is authorized by this document.

The lead must obtain the repository-required explicit authorization before
changing provider credentials or Railway secrets. The user's current improvement
request authorizes source redaction and preventative checks, not a silent secrets
infrastructure change.

## Prevention implemented

`scripts/check_didit_secrets.py` checks tracked working-tree text for literal
assignments to `DIDIT_API_KEY` and `DIDIT_WEBHOOK_SECRET`, including env/config,
JSON, and Markdown table formats. Its CI job runs synthetic regression fixtures
and the scan; findings print only path and line, never values. It recognizes
specific placeholders and runtime references without ignoring entire files.

Limitations are intentional: this is not a comprehensive secret scanner, does not
inspect Git history or untracked/ignored local files, skips binary files, and can
miss renamed, encoded, split, computed, or shorter-than-12-character credentials.
It does not establish provider revocation. A broader established secret scanner
and provider-supported secret alerts remain separate preventative improvements.
