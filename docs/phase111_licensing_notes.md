# Phase 111 — Proposed licensing materials

**Proposal only, October 10, 2026.** No publication, public license grant, merge, or push is authorized by this preparation pass. The existing deployed Terms page still states MIT. This document is a bounded repository review, not comprehensive legal clearance.

## Decision proposed

Use **AGPL-3.0-only** for project material the owner has authority to license. The unmodified GNU text is prepared at [LICENSE](../LICENSE); the README labels it as a proposal. No copyright-holder identity, new exception, CLA, or contribution-rights policy has been invented.

- **AGPL-3.0-only** fixes the grant to version 3.
- **AGPL-3.0-or-later** lets recipients choose version 3 or a future AGPL version published by the FSF. The same version-3 text is used; the project's grant and identifier determine the choice.

Recommend `only` as the concrete starting point because the owner has not yet approved future license versions. This is a preference to decide, not an extra restriction added to AGPL.

## What the choices mean

| Choice | Practical effect |
| --- | --- |
| MIT | Allows proprietary derivatives and commercial use, with the required copyright/license notice. No source-sharing requirement. |
| Apache-2.0 | Also permissive, with explicit patent licensing and termination terms, notice preservation, and modification notices. |
| AGPLv3 | Allows commercial use. Covered redistribution carries copyleft/source obligations; section 13 requires a modified network-interactive version to prominently offer its corresponding source to remote users at no charge. |

AGPL does not require contributors to submit changes upstream. It does not require voter data, credentials, production databases, or private configuration values to be disclosed. Calling an API does not automatically put every independent client under AGPL; whether software forms one covered combined work requires a fact-specific assessment. Corresponding source includes the source and necessary build/install material for the covered version, not just an unrelated or older repository snapshot.

Sources: [GNU AGPLv3, especially sections 1, 5–6, 9, 13–14](https://www.gnu.org/licenses/agpl-3.0.html), [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html), [MIT text](https://opensource.org/license/mit), [Apache-2.0 text](https://www.apache.org/licenses/LICENSE-2.0.html).

## Canonical text integrity

Downloaded directly over HTTPS from [GNU's text endpoint](https://www.gnu.org/licenses/agpl-3.0.txt) on October 10, 2026.

- 34,523 bytes; SHA-256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`.
- A second download matched the saved file byte for byte.
- GNU HTML was also fetched. The [SPDX AGPL-3.0-only text](https://github.com/spdx/license-list-data/blob/main/text/AGPL-3.0-only.txt) agrees word for word after whitespace normalization and normalization of three GNU/FSF links from HTTP to HTTPS. These link differences are documented; the saved GNU text was not changed.
- All 17 numbered sections, the end-of-terms marker, and GNU's application instructions are present.
- The FSF copyright notice protects the license text; it is not a project copyright attribution.

## Ownership and existing grants

Tracked author names on the reviewed origin/master history resolve to one name. This does not establish copyright ownership, employee/contractor rights, imported-code rights, or asset rights. No contributor assignment records were found in this scoped review.

No tracked LICENSE, COPYING, or NOTICE file exists on the baseline; no such path appeared in the locally available all-ref path history. However, `frontend/src/pages/Terms.jsx:83` states that the source is MIT-licensed, and the exact statement is present in the deployed bundle. `docs/pilot_public_copy_review_2026-08.md:245` repeats it. Earlier public open-source/MIT representations therefore need owner review. A new license must not be represented as retroactively withdrawing valid prior permissions.

Confirm the owner or entity authorized to grant rights, authority over original code and documentation, any third-party contributions/copying, and the intended treatment of prior MIT releases. Existing author notices remain intact. No blanket claim that every file or image belongs solely to the project has been added.

## Third-party review

The tracked tree has no vendor, vendored, third_party, or node_modules directory. A scoped copyright/SPDX/copied-source search found no separate copied-code license header in app sources. This is not proof of originality.

The npm lock has **84 production package nodes**, all with license metadata: MIT, ISC, BSD-3-Clause, Apache-2.0, Unlicense, or MIT AND ISC. Direct production dependencies:

| Package | Locked version | Metadata |
| --- | --- | --- |
| @hello-pangea/dnd | 18.0.1 | Apache-2.0 |
| d3 | 7.9.0 | ISC |
| d3-sankey | 0.12.3 | BSD-3-Clause |
| react / react-dom | 19.2.5 | MIT |
| react-router-dom | 7.18.2 | MIT |
| recharts | 3.8.1 | MIT |

Version-specific PyPI metadata was read for all **28 pins** in `backend/requirements.txt`; it reports:

| Pins | Reported license |
| --- | --- |
| fastapi 0.134.0; sqlalchemy 2.0.36; alembic 1.14.0; pydantic 2.10.3; pydantic-settings 2.7.0; python-jose 3.5.0; pyrankvote 2.0.6; nh3 0.2.18; slowapi 0.1.9; aiosmtplib 5.1.2; pytest 9.0.3; pytest-xdist 3.8.0; pdfplumber 0.11.10 | MIT |
| starlette 1.3.1; uvicorn 0.32.1; python-dotenv 1.2.2; httpx 0.28.1 | BSD-3-Clause |
| passlib 1.7.4; networkx 3.4.2 | BSD metadata; exact notice text requires distribution inspection |
| bcrypt 4.0.1; python-multipart 0.0.31; pytest-asyncio 1.4.0; tzdata 2024.2; requests 2.33.0; boto3 1.43.54; botocore 1.43.54 | Apache-2.0 |
| psycopg2-binary 2.9.9 | LGPL with exceptions |
| Pillow 12.3.0 | MIT-CMU |

Metadata source pattern: `https://pypi.org/pypi/{package}/{pinned-version}/json`. Test/script pins share the requirements file; they are included above without asserting every pin executes in the server request path.

No obvious AGPLv3 incompatibility was identified from these declarations. Metadata is not a substitute for notices in the actual distribution. In particular, preserve Apache notices, inspect psycopg2's LGPL exception and bundled native-library notices, and retain Pillow/native-code notices. Python transitive resolution, base-image/OS packages, binary contents, and final built-bundle attribution were not exhaustively inspected. Backend Dockerfile also fetches age; its v1.3.1 upstream LICENSE was fetched and reviewed as BSD-3-Clause. Its shipped binary notices belong in a final distribution inventory. Test-only reference libraries are not project-owned code.

There are **39 tracked public image/vector assets**. Demo portraits are described in code as AI illustrations supplied by the owner; no asset license/provenance ledger accompanies them. Confirm rights and generator/source terms for portraits, logos, PWA icons, and help screenshots before applying a repository-wide grant. No new screenshot or illustration was added. External Didit, Pol.is, Railway, Resend, and Cloudflare services remain separately operated; this proposal does not license those services.

## Deployed source offer and follow-ups

PublicLayout, About, Security, and Pilot link to the correct GitHub repository; that URL is present in live bundle `index-DOlyVHds.js`. Discoverability exists, but these generic repository-root links are not evidence of an exact corresponding-source offer for a future modified covered deployment.

After license/rights approval, a separately authorized app pass should reconcile Terms/public copy with the chosen license, identify the deployed source revision, and ensure a prominent source offer gives users the corresponding source including required build/install material. Keep build artifacts' upstream notices. Phase 110 app files were not edited here.

**Remaining owner decision:** choose AGPL-3.0-only or AGPL-3.0-or-later (or retain a permissive choice), confirm rights/asset provenance and prior MIT treatment, and separately authorize any eventual integration/publication. Credential revocation and history remediation also remain separate decisions; see the [publication review](phase111_publication_review.md).
