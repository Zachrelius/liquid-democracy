# Phase 111 — Repository publication review

**MIT publication approved by Z on October 10, 2026. Copyright identity: Zachary Petertam.**

The initial AGPL preparation was reviewed, then the owner selected MIT and explicitly authorized the README update and deployment to GitHub. This record now reflects that decision. Original audit findings below retain their reviewed-baseline context.

Branch: `phase-111/repository-publication-readiness`. Isolated managed worktree: `phase111-publication/Liquid-Democracy`. Initial preparation baseline: `bfbd01712c0c5e9fc0fba09702888139d60abbd1` (Phase 110 A integration). Publication integration baseline refreshed to `0c591057da39e24e570dcab3bfbba6a777f266b1`, after Phase 110 A and B were production verified. Spec-first commit: `2fa0e72`. The final artifact commit is available in the branch log; this document deliberately does not embed its own hash.

## Outcome and scope

| Workstream | Status |
| --- | --- |
| README | DONE: revised Claude's local draft, checked claims, rendered and inspected |
| License materials | DONE: approved MIT LICENSE, copyright 2026 Zachary Petertam, and updated licensing review |
| Tracked public notes | DONE: redacted baseline inventory, focused credential checks, one narrow personal-data cleanup |
| Publication / integration / deployment | APPROVED and executing: no-ff integration and normal GitHub master push; final task closeout records release/production disposition |

Files prepared: `README.md`, `LICENSE`, `docs/phase111_licensing_notes.md`, this review, the committed Phase 111 spec, and the narrowly anonymized `delegation_org_scoping_diagnostic_2026-05.md`. No frontend/backend code, manifests, Phase 110 files, AGENTS/CLAUDE instructions, root .gitignore, or shared PROGRESS edits. No broad document moves or .claude deletion. The root README draft and dirty index were not edited or staged by this work.

The README retains the invitation, live-site/pilot contact, delegation explanation, feature groups, stack, and setup pointers. It corrects lifecycle/consent/privacy claims, identifies the four experimental methods as opt-ins, updates React 18 to React 19, names the two currently listed demos, and states the approved MIT license. The final README removes preparation-stage language.

## README claim verification

| Claim | Evidence and result |
| --- | --- |
| Consent is configurable | `backend/models.py` follow policy and `backend/routes/delegations.py`: require approval, auto-approve view, auto-approve delegation. PASS; no universal consent-approval claim |
| Direct override and lifecycle | `backend/routes/votes.py` cast/retract and `_require_voting_open`; finalized/mutable gates and deadline enforcement. PASS; direct voting limited to eligible/open proposals |
| Methods actually available | `backend/voting_methods.py` legacy/experimental registry; ranked-choice IRV/STV tally and approval winner configuration. PASS; binary, approval, IRV/STV, budget allocation/project, STAR, Score, Ranked Pairs, Majority Judgment |
| Experimental scope | Phase 109 release evidence and registry defaults. PASS; opt-in/off by default; current Phase 110 B supports exactly one elected officeholder as well. README makes no multiwinner or scheduled experimental-method promise |
| Stable-result mode | `backend/sustained_majority.py` and worker/configuration. PASS; checks/possible extensions, not a strategy-proof guarantee |
| Comments, Pol.is | Comment and Polis routes; public Privacy/PolisHelp. PASS; hosted linked integration, no native Pol.is implementation claim |
| Governance/permissions | Organization/title/election/cosign/ratification/share/suborg routes and existing public docs. PASS; concise feature summary, no blanket application of every method to elections |
| Ballot privacy | Public Privacy/Security and admin ballot-audit route. PASS; member privacy by default, relationship/public-delegate exceptions, privileged/database access, no cryptographic secrecy claim |
| Didit platform storage | `backend/models.py` readable legal-name fields, results/hashes/references; verification mapper and public Privacy. PASS; not hashes-only |
| Provider handling | Verification provider's processing/purge attempts and public Privacy. PASS; own provider retention policy, no guaranteed immediate deletion |
| Demo directory | October 10 public GET `/api/orgs/demo`: two listed top-level demos, Cedar Hollow HOA and Calder Tool & Machine Works. Seed bibles also contain union/coalition content; directory visibility filter explains why these are not all advertised |
| Stack | Frontend package/lock: React 19 (locked 19.2.5), Vite/Tailwind/D3/Recharts; backend requirements/Docker/Compose. PASS |
| Setup | DEPLOYMENT, Compose, env example, startup script, auth first-user branch. PASS by source; credentials/origin/email setup required, SMTP forwarding and optional configuration limits explicit; no fresh-install execution claimed |
| Contact/source/URLs | Pilot mailbox retained from draft and existing HelpIndex; present in live bundle. Correct GitHub repository link present in PublicLayout/About/Security/Pilot and live bundle. Public documentation routes returned HTTP 200; no email sent or mailbox deliverability claim |

Initial preparation checks observed bundle `index-DOlyVHds.js`. At MIT publication follow-up, Phase 110 closeout and refreshed master confirm B production verified; the homepage now serves `index-CpFpIu6F.js`. These are read-only observations. Phase 111 changes only documentation/license paths outside both app services' watch patterns, so no new app bundle is required. Final closeout records the actual Railway disposition and live smoke result.

## Redacted public-note and credential audit

Inventory target was the refreshed **origin/master tree**, not the dirty root's many untracked files: **1,139 tracked files**, **195 Markdown files**, **121 root phase Markdown documents**. Scans enumerate tracked paths and inspect UTF-8 text; binary assets are excluded from credential text inspection. The refreshed Phase 110 publication baseline has 1,194 tracked files; a follow-up redacted scan found no private-key/JWT candidate and the same one explicitly synthetic provider-token fixture. The focused Didit guard and six tests were rerun before publication.

| Path / line or category | Finding | Preparation action / remaining remediation |
| --- | --- | --- |
| `.claude/settings.local.json:4,8` | One generic pip-install permission and experimental-team flag; no credential, private path, account identifier, or environment secret | Keep. Its local-style filename alone does not justify deletion |
| `phase52a_handoff_to_z.md:40` | Historical Didit credential is already replaced with a secret-store reference; line 52 reads a local environment variable rather than embedding it | Keep current redaction and technical handoff. Provider revocation remains separately unresolved |
| `phase52e_stage1_handoff_to_z.md:121,149` | Placeholder bearer-key syntax and conditional provider-purge/privacy notes | Keep useful technical history; no current secret found |
| `docs/phase107_credential_remediation.md:5–16` and Phase 107 PROGRESS evidence | Earlier read-only comparison found current deployed key differs from the historical key. Provider revocation still unverified | No new provider authentication, rotation, revocation, Railway variable read/write, or historical cleanup performed |
| `delegation_org_scoping_diagnostic_2026-05.md`, original lines 167–175, 250–278 and repeated references | Production mailbox/participant identifiers, membership relationships, and non-demo organization name in a historical diagnostic | Anonymized participants and organization in this one document; preserved code references, case semantics, counts, and useful technical context. Removed values never reproduced in this report |
| `PROGRESS.md:797` and other historical working notes | Private/local operational context and a user-directory path; technical notes are not credentials merely because internal | Shared PROGRESS is explicitly outside edit scope. Reassess personal/participant context before a broad public-note publication; no broad purge proposed |
| `docs/workflow_spike_resume_findings.md:32,33,149`; `wa1_state_and_ipc_foundation_closeout.md:32`; workflow examples/tests; Phase 110/111 spec line 9 | Local filesystem paths or example paths | Low-risk context, not authentication secrets. Keep structure; optional portability cleanup is deferred |
| `DEPLOYMENT.md:386,567`; `phase4_cleanup_spec.md:317–319`; `phase6_5_spec.md:136,138`; `phase9_polis_api_findings.md:169` | Mailbox references: historical SMTP examples/project account and provider contact | Values withheld from report. Source-cleanup/consent review remains before unrestricted publication of historical notes; no credentials inferred merely from an address |
| `browser_testing_playbook.md:804,860,1105,1203` | QA account/mailbox and sample-password instructions | Test context; not proven live account credentials. Confirm fixtures remain synthetic/disposable before publishing or reusing them; no login probe performed |
| `workflow-automation/dashboard/tests/test_server_and_round_trip.py:144` | One provider-shaped token candidate | Explicit synthetic test fixture; no current credential exposure confirmed |
| `backend/tests/test_auth_change_password.py:27`, `backend/tests/test_auth_password_reset.py:30`, `frontend/test/phase103ProposalFeed.test.js:417` | Three assignment candidates | Test fixture passwords and fake refresh-response values; no production secret inferred |
| 22 credential-shaped URL candidates | Compose substitutions, documentation placeholders, local disposable DB URLs and test/restore fixtures | No production connection secret identified; no database connection or authentication attempted |
| Private keys / serialized JWT candidates | No matching tracked text artifact found | No current-tree fix indicated |

The focused Didit guard passed over tracked text; its **six existing regression tests passed**. Broader redacted pattern checks found no confirmed current credential after candidate review. The scan also checked private-key blocks, provider-token shapes, credential-bearing URLs, literal secret assignments, long note assignments, mailbox contexts, JWT forms, and machine-local paths. This is a bounded heuristic review; it can miss renamed/encoded/split secrets, binary contents, and sensitive information outside selected patterns. It does not certify the repository history. The current repository was already public; the owner approved publishing the narrow README/license/diagnostic diff without changing visibility or broadly republishing/reorganizing historical notes.

**History matters:** deletion/redaction at HEAD does not erase Git history or revoke a key. The historical Didit exposure remains recorded; provider-side revocation must be established from authorized provider metadata, and any cleanup of shared history needs a separately coordinated decision. Personal identifiers removed here also remain in older commits. Do not authenticate with old values to test them.

## Licensing / ownership findings

See [licensing notes](phase111_licensing_notes.md) for canonical MIT checksum, owner decision, dependency inventory, rights limits, asset provenance, and source-link review.

The deployed **MIT statement at `frontend/src/pages/Terms.jsx:83`** now aligns with the approved README and standard LICENSE. The owner identified himself as the creator and selected MIT after discussing closed/commercial forks and contributions. No prior permission is withdrawn. The source-code license does not relicense dependencies or assert sole ownership of all 39 existing public assets; provenance limits remain documented.

All 84 npm production nodes have metadata; version-specific PyPI metadata for all 28 backend pins was checked. No obvious incompatibility was identified from declarations. Full transitive/binary/OS notice clearance and final-bundle attribution are not claimed. Upstream age v1.3.1 license was fetched and has BSD redistribution clauses. Existing package notices must be preserved.

## Acceptance matrix

| Check | Result |
| --- | --- |
| README factual claims | PASS by current source plus bounded public HTTP/bundle checks above |
| Relative links | PASS: final README local targets and report/notes local targets checked |
| Markdown rendering | PASS: Marked + headless Chrome preview visually inspected; eight headings and seven lists; final MIT rendering/link checks rerun; no horizontal overflow at 1100px or 380px; mobile preview visually inspected |
| License text / identifier | PASS: canonical SPDX MIT template verified; only approved year/name substituted; final body matches OSI MIT; README/LICENSE identify MIT |
| Ownership / third parties | REVIEW COMPLETE: owner approved MIT and provided copyright identity; third-party/provenance limits recorded, not comprehensive legal clearance |
| Tracked public-note audit | PASS within stated limits; one current-tree personal-data cleanup; historical/key-revocation questions remain |
| Screenshot | NOT APPLICABLE: no screenshot asset added; temporary README rendering is outside committed files |
| Scope / diff | PASS: exact documentation/licensing path allow-list; no app or Phase 110 changes; explicit staging only |
| Backend/frontend full suites | NOT REQUIRED for documentation-only preparation; backend test count delta 0 |
| Migration / PostgreSQL smoke | No migration; smoke not required |
| Deployment / backfill | GitHub publication authorized and executing; verify remote master plus Railway watch-path disposition/live health. No application change, migration, reset or backfill |

## Approved publication and remaining follow-ups

Z selected **MIT**, supplied **Zachary Petertam**, and directed updating README and deploying to GitHub. No additional license-choice or copyright-name input is needed. The Phase 111 spec has a superseding publication authorization section; original preparation restrictions remain historical context.

Integrate the reviewed documentation/license diff with a no-ff merge on top of refreshed origin/master from a clean isolated integration checkout. Push master normally. Preserve the dirty root checkout, README draft, staged index, app code and all Phase 110 commits. Repository visibility stays public as it already was. Verify the GitHub files/license detection, remote merge identity, Railway deployment disposition and healthy production endpoints. Final task closeout reports exact commits and observed outcomes.

Provider revocation metadata, any shared-history cleanup, exhaustive distribution notices, asset provenance records and a refreshed clean-install guide remain separately scoped follow-ups, **NOT STARTED**. MIT needs no AGPL network-source-offer app change. No background task or automation was created.

Root phase-document migration remains **DEFERRED / NOT STARTED** because current conventions and cross-references depend on the layout. Phase 110's completed release is preserved.
