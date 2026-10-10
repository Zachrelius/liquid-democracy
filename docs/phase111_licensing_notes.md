# Phase 111 — MIT licensing review

**MIT approved by the owner on October 10, 2026.** Z reviewed the prepared materials, selected MIT, supplied the copyright name **Zachary Petertam**, and authorized the README update and publication to GitHub. This replaces the earlier tentative AGPL proposal. The repository's deployed Terms already identify MIT; no app Terms change is needed.

## License selected

Liquid Democracy's original source code and associated documentation use the **MIT License**. [LICENSE](../LICENSE) contains the standard license text with **Copyright (c) 2026 Zachary Petertam**. The reviewed history begins in 2026.

MIT permits commercial use, modification, redistribution, sublicensing and sale, including proprietary derivatives, subject to preserving the required copyright/license notices. It imposes no source-sharing or upstream-contribution requirement. The owner explicitly accepts these tradeoffs.

No custom restriction, new exception, CLA, or contribution-rights policy was added. This publication does not relicense third-party dependencies or claim ownership of externally sourced material. Hosted-service Terms continue to govern accounts and service use separately.

Sources: [OSI MIT text](https://opensource.org/license/mit), [SPDX MIT identifier](https://spdx.org/licenses/MIT.html).

## Canonical text integrity

The [SPDX license-list MIT text](https://github.com/spdx/license-list-data/blob/main/text/MIT.txt) was downloaded over HTTPS and checked against the OSI license text.

- Template: 1,078 bytes; SHA-256 `b05785f9f18e6716bab63424b11454513b9943a222595b70411009202fc592b5`.
- Only `<year>` and `<copyright holders>` were replaced with the approved year/name.
- Final LICENSE SHA-256: `638b143b4689cc954fe096cf64379f468d3b5cf0bb6861a6bdced3c3d1d00b81`.
- License body, notice condition and warranty/liability disclaimer are unchanged. README and LICENSE identify MIT consistently.

## Ownership and existing statements

The owner identified himself as the creator, approved the permissive grant, and supplied the copyright identity. Tracked authorship and source-notice inspection found no separate contributor grant to replace. This scoped review does not prove originality or comprehensive legal clearance.

The baseline had no tracked LICENSE, COPYING or NOTICE file, but `frontend/src/pages/Terms.jsx:83` and `docs/pilot_public_copy_review_2026-08.md:245` already state MIT. The standard MIT LICENSE makes the existing policy explicit without attempting to withdraw any prior permissions. Existing notices remain intact.

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

The npm declarations are permissive; Python components retain their respective licenses, including psycopg2's LGPL terms and exception. A project MIT grant does not replace those terms. Metadata is not a substitute for notices in the actual distribution. In particular, preserve Apache notices, inspect psycopg2's LGPL exception and bundled native-library notices, and retain Pillow/native-code notices. Python transitive resolution, base-image/OS packages, binary contents, and final built-bundle attribution were not exhaustively inspected. Backend Dockerfile also fetches age; its v1.3.1 upstream LICENSE was fetched and reviewed as BSD-3-Clause. Its shipped binary notices belong in a final distribution inventory. Test-only reference libraries are not project-owned code.

There are **39 tracked public image/vector assets**. Demo portraits are described in code as AI illustrations supplied by the owner; no asset license/provenance ledger accompanies them. Rights and generator/source terms for portraits, logos, PWA icons, and help screenshots are not established by this scoped source-code review; no blanket claim of sole project ownership is made. No new screenshot or illustration was added. External Didit, Pol.is, Railway, Resend, and Cloudflare services remain separately operated; the project license does not license those services.

## Deployed source links and remaining review limits

PublicLayout, About, Security and Pilot link to the correct GitHub repository. Phase 110 B's production release has been verified; publication is integrated on top of refreshed origin/master `0c591057da39e24e570dcab3bfbba6a777f266b1`. No application/source-link change is needed for this MIT publication.

The earlier exact-corresponding-source offer discussion concerned the unadopted AGPL proposal. MIT does not impose that network-source-offer requirement. No AGPL grant or custom commercial restriction is part of the current release.

The existing dependency and asset findings below remain useful notice/provenance limits rather than an assertion that all repository material is solely project-owned. Provider-side historical-key revocation, any shared-history cleanup, exhaustive distribution notices, asset provenance records and a refreshed clean-install guide remain separately scoped follow-ups. See the [redacted publication review](phase111_publication_review.md). No provider/infrastructure action or broad file migration is authorized by this publication.
