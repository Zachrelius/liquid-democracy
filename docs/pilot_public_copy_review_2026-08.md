# Pilot Public-Copy Accuracy Review

**Status:** Copy approved by Z on August 22, 2026 for the Phase 99 preview implementation. Nothing in this document is live site copy yet. YouTube disclosures remain conditional and must not publish until a playable video ships.

**Purpose:** Replace self-hosted-template language with accurate copy for the hosted service at `liquiddemocracy.us`, update pilot-stage claims, and give Z a side-by-side review before any frontend change ships.

**Legal note:** This is an operationally grounded, best-judgment product draft, not legal advice. It is written for an initial, general-audience U.S. pilot involving known members and correctable organizational decisions. Legal review is not treated as a prerequisite to publishing this low-risk pilot copy. It should be revisited before intentionally serving children under 13, targeting people in the European Union, charging organizations under a commercial contract, or supporting regulated, employment, housing, union, governmental, legally binding, or otherwise high-stakes decisions.

## Executive review

| Page | Current state | Material problem | Recommended treatment |
|---|---|---|---|
| Privacy | April 2026 self-hosted template | Says each organization controls its own database and infrastructure; says no third parties receive data; promises portability and deletion paths not implemented as described | Full replacement for the hosted service |
| Terms | April 2026 self-hosted template | Assigns hosting/backups to each organization and lets organization administrators change site-wide terms; lacks hosted-pilot boundaries | Full replacement with the bounded pilot terms below; revisit with counsel before higher-risk or paid use |
| Security & Trust | Strong conceptual explanation of ballot/privacy tradeoffs | Calls production merely a public demo; omits the now-proven backup/restore and monitoring posture; pilot CTA is missing | Targeted replacement sections and additions |
| About | Good long-form product explanation | Says the platform is already in pilot use by real organizations; outreach still routes through email rather than `/pilot`; operations summary predates monitoring/backups | Targeted edits |

## Current production data map to ground the copy

This is the minimum accurate provider and data-flow inventory as of August 2026:

- **Railway:** Hosts the application, PostgreSQL database, and persistent upload volume. The database contains accounts, memberships, organization configuration, proposals, comments, votes, delegations, messages, notifications, audit records, and verification results/derived fields.
- **Resend:** Delivers transactional email such as verification, password-reset, invitation, notification, monitoring, and recovery messages. Email addresses and message contents necessary for delivery pass through Resend.
- **Cloudflare R2:** Stores private, retention-protected offsite backup objects. These objects are encrypted before upload with an `age` public recipient; Cloudflare and the running application do not receive the private recovery identity.
- **Didit, optional:** Processes identity documents and selfies when a user chooses or is required to complete identity verification. Liquid Democracy stores verification results and derived privacy-preserving hashes, not raw ID images, selfies, or raw document numbers. A provider-side deletion promise must not be made because end-to-end Didit purge remains unproved.
- **pol.is, optional:** Hosts structured deliberation conversations when an organization enables or links one. Participants receive a platform-generated pseudonymous identifier, but pol.is processes the conversation participation.
- **YouTube, proposed and click-gated:** Training and demonstration videos may be hosted as Unlisted YouTube videos. The site should display its own preview first and should not contact or load YouTube until a visitor chooses Play. At that point YouTube/Google receives the ordinary browser request and applies its own policy. This disclosure should publish only when the video feature ships.
- **GitHub:** Receives only coarse public production-monitor results through GitHub Actions/issues. The monitoring contract prohibits private organization content, ballot data, credentials, database details, and personal contact data.

Provider policies for the final page's external-links section:

- Railway: https://railway.com/legal/privacy
- Resend: https://resend.com/legal/privacy-policy
- Cloudflare: https://www.cloudflare.com/privacypolicy/
- Didit: https://didit.me/terms/privacy-policy/
- pol.is: https://pol.is/privacy
- Google/YouTube: https://policies.google.com/privacy

## Privacy page: current-versus-proposed review

### Claims that must be removed or corrected

| Current claim | Why it is inaccurate | Proposed direction |
|---|---|---|
| “This is a template policy for self-hosted instances.” | `liquiddemocracy.us` is a centrally hosted service. | Identify the hosted service and operator contact. |
| “All data is stored in a PostgreSQL database managed by your organization.” | Production PostgreSQL is operated by the platform on Railway. | Explain platform/operator and organization-admin roles separately. |
| “Your data stays on infrastructure controlled by your organization.” | Railway, Resend, Cloudflare, optional Didit, and optional pol.is participate in service delivery. | Name each provider and why data reaches it. |
| “We do not share your data with any third parties.” | Operational providers necessarily process some data. | Say data is not sold or used for advertising by Liquid Democracy, then disclose service providers. |
| “We support data portability.” | No complete self-service account or organization export was found. | State that export and a self-hosting migration package are not included in the initial pilot and may be considered as future features if an organization needs them. |
| “Upon deletion, your personal information is removed...” | There is no general account-deletion workflow matching this promise, and governance/audit integrity complicates deletion. | Explain that requests are handled case by case and some records may need to be retained, restricted, or de-identified. |
| “Organization admins ... cannot see individual votes unless they have a follow relationship.” | Standard org-admin tools do not expose individual ballots. A restricted platform-admin API—not a normal admin-screen control—can retrieve an unredacted audit entry when given its ID and a written reason, and platform operators have underlying database access. | Describe the exceptional API accurately without implying there is a routine ballot-viewing screen. |

### Proposed complete Privacy page copy

#### Privacy Policy

*Last updated: [PUBLICATION DATE]*

Liquid Democracy is a pilot-stage hosted service for organizational decision-making. This policy explains what information the service at `liquiddemocracy.us` collects, how it is used, when other people or service providers can access it, and the choices available to you.

For privacy questions or requests, contact `support@liquiddemocracy.us`.

#### Information we collect

When you create an account or use Liquid Democracy, we may collect:

- **Account information:** username, display name, email address, password hash, email-verification status, and account-security records.
- **Organization information:** memberships, roles, invitations, organization settings, and administrative actions.
- **Governance activity:** proposals, revisions, comments, votes and ballot selections, delegation choices, vote rationales, election activity, and audit records.
- **Communications:** messages sent through the platform, notification preferences, and email-delivery records.
- **Files you provide:** profile images, organization logos, and other supported uploads.
- **Technical and security information:** IP addresses, request timestamps, request paths, coarse error and health information, and other records needed to operate, secure, and troubleshoot the service.
- **Optional identity-verification information:** verification status, jurisdiction/country results, age-band results, provider/session references, and privacy-preserving hashes derived from verified identity fields. Liquid Democracy does not store raw ID images, selfies, or raw document numbers in its own database.
- **Pilot inquiries and support requests:** contact information and the content you choose to submit when asking about a pilot or requesting help.

Please do not put sensitive personal information into proposal text, comments, pilot-inquiry forms, or support messages unless it is necessary for your organization and you are authorized to provide it.

#### How we use information

We use this information to:

- provide accounts, organizations, voting, delegation, deliberation, messaging, and administrative tools;
- calculate results and preserve the integrity and history of organizational decisions;
- deliver invitations, security messages, notifications, and support;
- prevent abuse, investigate incidents, enforce permissions, and maintain audit records;
- monitor reliability, create encrypted backups, and recover the service after a failure; and
- understand and improve the pilot experience using coarse or aggregated operational information that does not include ballot contents or private proposal/member content.

Liquid Democracy does not sell personal information, run an advertising network, or use ballot contents for advertising.

#### Who can see information inside Liquid Democracy

Visibility depends on the type of information and the choices made by you and your organization:

- **Votes are private from other members by default.** A vote may become visible where you have deliberately enabled a relevant follower relationship or registered as a public delegate on the applicable topic. Public delegates publish the relevant voting record and rationale as an accountability feature.
- **Delegation relationships are not public by default.** A delegate can know that you delegated to them, and approved relationship permissions can make additional activity visible.
- **Organization administrators** can manage members and see organization-level information and aggregate analytics. The standard organization-admin interface does not provide a routine view of individual ballot contents.
- **Platform administrators** do not have a ballot viewer in the ordinary admin screen, and default audit responses redact ballot contents. A restricted platform-admin API exists for exceptional investigation of a specific audit entry. It requires the entry ID and a written reason, can reveal otherwise-redacted ballot fields, creates a separate audit event, and appears in the affected user's Data Access History.
- **Platform operators** can access the underlying hosting systems and database when necessary to operate, secure, troubleshoot, back up, or recover the service. This means Liquid Democracy does not provide the technical secrecy of a conventional paper ballot.
- **Public organizations, proposals, delegate profiles, and activity** may be visible without signing in when the organization or user has chosen a public setting. Members-only and private-organization boundaries remain subject to the platform's access controls.

More detail about these boundaries appears on the Security & Trust page.

#### Service providers and optional integrations

Liquid Democracy uses service providers to operate the hosted service:

- **Railway** hosts the application, database, and uploaded files.
- **Resend** processes email addresses and message contents needed to deliver transactional email.
- **Cloudflare R2** stores encrypted offsite backups. Backups are encrypted before they leave the application environment, and the private recovery key is kept separately from Railway and Cloudflare.
- **Didit** processes identity documents and selfies only when identity verification is initiated. Didit handles those materials under its own privacy policy. Liquid Democracy stores the verification result and derived fields described above; it does not promise that Didit immediately deletes its copy after verification.
- **pol.is** processes participation in a hosted pol.is conversation when an organization chooses to use that optional feature. Liquid Democracy supplies a pseudonymous participant identifier rather than a display name, but platform operators may be able to connect that identifier to an account for moderation or audited export purposes.
- **YouTube/Google** may host optional training and demonstration videos as Unlisted videos after that feature is introduced. The site should show a local preview first and should contact and load YouTube only after you choose Play. YouTube/Google then receives the ordinary browser request and applies its own privacy policy.

These providers operate under their own terms and privacy policies. We may also disclose information when reasonably necessary to comply with law, protect users or the service, investigate abuse, or complete a business transfer, subject to applicable obligations.

#### Browser storage

The application uses browser session storage for sign-in tokens and temporary navigation/interface state. Session storage is normally cleared when the browser session ends. It uses local storage for limited convenience choices such as the last organization visited and dismissed interface prompts. Liquid Democracy does not currently use third-party advertising trackers.

Training and demonstration videos may be hosted as Unlisted YouTube videos. They should not play—or contact and load the YouTube player—unless you choose Play.

#### Security and backups

Passwords are stored as bcrypt hashes rather than plaintext. Connections to the public service use HTTPS. Access tokens are short-lived, refresh tokens rotate, and only one-way refresh-token digests are stored in the database.

The service uses access controls, rate limiting, audit logging, production monitoring, provider-native recovery points, and daily encrypted offsite backups. Both the provider-native volume restore process and the encrypted offsite database restore process have been rehearsed using disposable recovery targets. No internet service can guarantee perfect security or availability.

#### Retention

Account, membership, governance, and audit information is generally retained while needed to provide the service and preserve the history and integrity of organizational decisions. Notifications are ordinarily cleaned up after approximately 90 days. Closed proposals, vote records, and audit events may be retained longer because deleting them could change or obscure the historical decision record.

Backups use rolling retention schedules, so information removed from the live system may remain in encrypted or provider-managed recovery points until those recovery points expire. Backup copies are used for disaster recovery, not ordinary access.

Optional providers, including Didit and pol.is, apply their own retention policies to information they process.

#### Access, correction, export, and deletion requests

You can update some account information in the service. For other access, correction, export, restriction, or deletion requests, contact `support@liquiddemocracy.us`.

The initial pilot does not include a complete self-service account or organization export, a reusable portability package, or a supported self-hosting migration package. Those capabilities may be developed later if a pilot organization needs them, but users and organizations should not rely on them being available. Requests will be reviewed using the tools reasonably available at the time and may require identity verification and coordination with the relevant organization. Some governance, security, backup, or audit records may need to be retained, restricted, or de-identified rather than deleted when necessary to preserve other users' rights, organizational decision integrity, security, or legal obligations.

#### Children

The hosted service is not directed to children under 13. Do not create or administer an account for a child under 13. If you believe a child under 13 has provided personal information through the service, contact `support@liquiddemocracy.us` so the operator can restrict the account and address the information as required.

Nothing in this section limits rights that apply under applicable law.

#### Changes to this policy

This policy may change as the pilot service, providers, or legal obligations change. The page will show the current revision date. Material changes should be communicated through the service or by email when reasonably appropriate.

#### Contact

Privacy questions and requests: `support@liquiddemocracy.us`.

## Terms page: current-versus-proposed review

### Claims that must be removed or corrected

| Current claim | Why it is inaccurate | Proposed direction |
|---|---|---|
| “This is a template for self-hosted instances.” | The public service is hosted and operated centrally. | Write terms for `liquiddemocracy.us`; keep the MIT-licensed source-code distinction. |
| “Availability depends on the hosting organization's infrastructure.” | Production is hosted on Railway by the platform operator. | Promise best-effort service and describe pilot support without an uptime SLA. |
| “We recommend organizations maintain regular database backups.” | Organizations do not control the production database; the platform now maintains and tests recovery layers. | State that the operator maintains backups but cannot guarantee uninterrupted service or lossless recovery. |
| “Organization administrators may update these terms at any time.” | Org administrators cannot set site-wide terms for the hosted service. | The platform operator updates the terms and provides reasonable notice of material changes. |

### Proposed complete Terms page copy

#### Terms of Service

*Last updated: [PUBLICATION DATE]*

These terms govern use of the hosted Liquid Democracy service at `liquiddemocracy.us`, currently operated as an early-stage project by the founder of Liquid Democracy. The service is a pilot-stage tool for organizational decision-making. By creating an account or using the service, you agree to these terms. Questions may be sent to `support@liquiddemocracy.us`.

#### What the service is

Liquid Democracy lets organizations create proposals, deliberate, vote directly, and delegate voting power to trusted people by topic. It includes membership, administrative, notification, identity-verification, and governance tools.

The hosted service is not a certified public-election system and does not itself make an organization's decisions legally binding. Each organization is responsible for determining what authority, if any, it gives to a platform decision and whether separate notices, meetings, records, ballots, approvals, or legal procedures are required.

Do not use the pilot service as the sole system for governmental elections, legally mandated secret ballots, emergency decisions, or decisions where an outage, error, or later correction would create unacceptable harm.

#### Accounts and security

Provide accurate account information, keep your credentials secure, and do not allow another person to use your account. Do not create duplicate accounts to obtain additional voting power or evade an organization rule. Notify `support@liquiddemocracy.us` if you believe an account or organization has been compromised.

The hosted service is not directed to children under 13. Do not create or administer an account for a child under 13.

The operator may restrict or suspend access when reasonably necessary to protect users, investigate abuse, comply with law, or preserve service integrity.

#### Member responsibilities

You agree not to:

- manipulate voting, identity, delegation, invitation, or verification systems;
- impersonate another person or misrepresent your authority;
- harass, threaten, defraud, or unlawfully discriminate against others;
- upload malicious code or attempt unauthorized access;
- publish information you do not have the right to share; or
- use the service in violation of applicable law or an organization's valid rules.

Members remain responsible for the proposals, comments, messages, rationales, profile information, and files they submit.

#### Organization responsibilities

The people who create and administer an organization are responsible for:

- having authority to invite or enroll members and administer the organization's use;
- selecting settings and voting methods appropriate to the organization's rules and decisions;
- explaining the pilot, relevant privacy boundaries, and whether results are advisory or authoritative;
- providing fair notice and sufficient time for participation;
- responding to member questions, moderation needs, and requests involving organization-controlled information;
- maintaining any legally required records outside the platform; and
- avoiding a use case that requires legal, security, accessibility, or election guarantees the pilot service does not provide.

An organization's administrators can manage substantial parts of its configuration and membership. Their actions are attributable to the organization, not automatically endorsed by the platform operator.

#### Pilot-stage service and support

The service is provided on a best-effort pilot basis. Features may change, errors may occur, and planned maintenance or provider failures may interrupt access. The operator maintains monitoring and tested backup/recovery procedures but does not promise uninterrupted availability, a particular recovery time, or that no data can ever be lost.

Pilot support arrangements described on `/pilot` or in a separate Pilot Participation Understanding supplement these general terms for an accepted pilot organization. They do not create an uptime or response-time guarantee unless a signed agreement explicitly says otherwise.

#### Privacy

The Privacy Policy explains the information the service processes, visibility boundaries, service providers, backups, and available requests. The Security & Trust page explains why liquid democracy does not provide the same technical ballot secrecy as a conventional paper election.

#### Organization and user content

You retain any rights you hold in content you submit. You give the operator permission to host, copy, process, transmit, back up, and display that content as needed to provide, secure, and recover the service and to honor the visibility settings you or your organization select.

Do not submit content that infringes another person's rights or that you are not authorized to disclose. The operator may restrict or remove content when reasonably necessary to address abuse, security, legal obligations, or harm, while preserving an appropriate audit record where the platform supports it.

#### Ending use

You may stop using the service. Organization leaders may remove members or stop their organization's participation according to their authority and the organization's settings. The initial pilot has no preset end date, and continued use is welcome when the platform works for the organization. Support is concentrated during setup and early decisions and becomes lighter as the organization becomes self-sufficient.

Complete self-service organization export and deletion, a reusable portability package, and a supported self-hosting migration package are not included in the initial pilot. They may be considered as future features if requested, but an organization should not rely on them without a separate written commitment.

Some decision, audit, security, and backup records may remain as described in the Privacy Policy. The operator may discontinue the pilot service, but should provide reasonable notice and a practical opportunity to discuss available data handling when circumstances permit.

#### Open-source software

The source code is available under the MIT License on GitHub. The MIT License governs use, copying, modification, and distribution of the source code. These hosted-service terms govern accounts and use of `liquiddemocracy.us`; they do not replace the source-code license.

#### Disclaimers and liability

To the fullest extent permitted by applicable law, the hosted service is provided “as is” and “as available,” without a promise that it will always be available, error-free, secure, or suitable for a particular legal or governance purpose. The operator is not responsible for indirect, incidental, special, consequential, or punitive losses arising from use of or inability to use the service. Nothing in these terms excludes a warranty, right, remedy, or liability that applicable law does not allow to be excluded or limited.

If any part of these terms cannot be enforced, the remaining parts continue to apply. These terms and any accepted pilot understanding are the entire agreement about use of the hosted pilot service unless the operator and an organization agree to something different in writing.

#### Changes

The operator may update these terms as the pilot service changes. The page will show the current revision date. Material changes should be communicated through the service or by email when reasonably appropriate. Continued use after the effective date of updated terms constitutes acceptance to the extent permitted by applicable law.

#### Contact

Questions about these terms: `support@liquiddemocracy.us`.

## Security & Trust page: targeted proposed changes

The existing page's core explanation of institutional privacy versus technical ballot secrecy is valuable and should remain. Make these focused updates.

### Replace “About this demo specifically” with “About this hosted pilot service”

**Current gist:** The deployment is only a public demo, lacks recovery/monitoring, and formal pilots will establish safeguards later.

**Proposed copy:**

> The current deployment at liquiddemocracy.us is a hosted, pilot-stage service operated by the project's founder with assistance from AI development agents. It has not received a formal penetration test or certification by an independent election-security firm, and there is not yet an independent oversight body separating platform operations from the founder's access.
>
> The operational safeguards are stronger than the original public demo. The service now has external and internal health monitoring, actionable administrator alerts, provider-native volume recovery points, daily encrypted offsite backups stored with a separate provider, and successful restore rehearsals using isolated disposable targets. Those controls reduce operational risk; they do not create conventional ballot secrecy or eliminate the need to trust the platform operator.
>
> This is appropriate for an early organizational pilot involving known members and correctable decisions. It is not appropriate as the sole system for governmental elections, legally mandated secret ballots, or decisions where an outage, error, or later correction would create unacceptable harm. Organizations considering a pilot should review these boundaries openly with their members.

### Replace the current security-practices paragraph

**Current gist:** OWASP review, bcrypt, tokens, email verification, password reset, and rate limiting.

**Proposed copy:**

> We've built and tested the security controls appropriate to the current pilot stage. The codebase has undergone repeated authorization, privacy, dependency, and adversarial review passes, including checks based on the OWASP Top 10 and OWASP ASVS. The backend has more than 3,000 automated tests, supplemented by browser verification of important user journeys. Authentication uses bcrypt password hashing, short-lived access tokens, rotating refresh tokens stored only as one-way digests, email verification, password reset, and rate limiting. Privileged access and state-changing actions are audited, and the public backend is isolated behind Railway private networking.
>
> Production monitoring checks database connectivity and capacity, background workers, repeated server errors, upload capacity, and email failures. A separate external check can report a total outage even if the application cannot send its own alert. Daily offsite backups are encrypted before upload with a recovery key that is not stored in the application environment, and both native-volume and offsite database restoration have been rehearsed against disposable targets.
>
> These are meaningful safeguards, not a claim that the service is invulnerable or certified for high-stakes public elections. Independent professional security testing remains a future requirement before higher-risk deployment.

### Clarify exceptional ballot access

Add near the existing institutional-privacy explanation:

> The ordinary platform-admin screen does not include a ballot viewer, and the normal audit API redacts ballot fields. A restricted platform-admin API can retrieve a specific unredacted audit entry for exceptional investigation when supplied with the entry ID and a written reason. That access creates its own audit event and appears in the affected user's Data Access History. The platform operator also has underlying database access, so these controls provide accountability and deterrence rather than cryptographic ballot secrecy.

### Add a short “Service providers” paragraph

> The hosted service depends on specialized providers: Railway for application and database hosting, Resend for transactional email, Cloudflare R2 for encrypted offsite backups, optional Didit identity verification, and optional hosted pol.is deliberation. The Privacy Policy explains what each provider processes. Provider use is part of the trust boundary and is not hidden behind a claim that the service is entirely self-contained.

### Hold the pilot call to action during preview

Ship the updated trust copy in Phase 99, but do not add a prominent `/pilot` button yet. Retain the existing `Try the demo`, `View on GitHub`, and direct-email paths. A later activation pass can add `Learn about a supported pilot` after Z reviews the built `/pilot` page.

## About page: targeted proposed changes

### Replace the opening of “What's built”

**Current:**

> The platform is live at liquiddemocracy.us and in pilot use by real organizations. Everything below is shipped and running.

**Proposed:**

> The platform is live at liquiddemocracy.us and ready for its first supported external pilots. Everything below is shipped and running; the next step is learning how it performs for real organizations making recurring, correctable decisions.

### Adjust the identity-verification paragraph

Replace “integrated with Didit for real KYC verification” with:

> **Identity verification.** Five-level verification state model from email-only through residency-verified, with optional Didit-hosted identity checks. Liquid Democracy stores verification results and privacy-preserving derived hashes rather than raw identity-document images or document numbers. Organizations can leave verification off or set proposal-level verification and jurisdiction requirements. An age threshold is available only as part of the optional identity-verification flow; the platform does not otherwise verify a member's age.

### Expand the operations paragraph

Append:

> Production monitoring covers database health and capacity, background workers, repeated server errors, upload capacity, and email delivery, with both internal email alerts and an external GitHub-based outage path. Recovery uses provider-native volume backups plus daily encrypted offsite backups stored separately in Cloudflare R2. Both restore paths have been successfully rehearsed using disposable targets rather than production.

### Replace “Get involved” pilot language

**Proposed:**

> If you are part of an organization interested in trying liquid democracy, we're recruiting a small number of supported pilot groups. The strongest early fit is a known-membership organization with a committed steward, roughly 20–200 members, and one or more meaningful but correctable decisions to make. We'll help configure the organization, rehearse the member experience, and learn from what works and what does not.

For the Phase 99 preview, update this prose but retain `Try the demo`, `View on GitHub`, and the direct email link without adding a `/pilot` button. A later activation pass can promote `/pilot` after Z reviews the built page.

## Legal-research boundary behind this draft

The August 2026 review did not identify a general U.S. requirement that this low-risk, general-audience pilot publish the founder's home address. The draft therefore uses the monitored `support@liquiddemocracy.us` address and the functional description “operated ... by the founder of Liquid Democracy.” It does not invent a company identity, postal address, governing law, or arbitration clause.

Two changes in scope would require revisiting that choice:

- The FTC says COPPA applies to a general-audience service when it has actual knowledge it is collecting personal information from a child under 13. A covered children's privacy notice must identify an operator and provide an address, phone number, and email address. General-audience services are not required to investigate every user's age, but receiving age information that establishes a user is under 13 can create actual knowledge. Sources: [FTC COPPA FAQ](https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions) and [FTC general-audience guidance](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-not-just-kids-sites).
- GDPR Article 13 requires the identity and contact details of the controller when its notice duties apply. Deliberately targeting EU organizations or residents should therefore trigger a jurisdiction-specific review before outreach. Source: [GDPR Article 13](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679).

California's CalOPPA is a practical reason to publish an accurate, conspicuous Privacy Policy: it applies to commercial sites or online services collecting personally identifiable information from California consumers and calls for disclosure of collected categories, third-party categories, review/change procedures, and the effective date. The California Attorney General's published summary does not list a public street address among those baseline disclosures. Sources: [California Attorney General privacy-policy guidance](https://oag.ca.gov/node/36676) and [CalOPPA enforcement summary](https://oag.ca.gov/news/press-releases/attorney-general-kamala-d-harris-launches-new-tool-help-consumers-report).

If a postal address later becomes advisable, use a business mailing address or post-office box rather than publishing a home address. A separate AI review can help critique language but is not a substitute for counsel in a higher-risk deployment.

## Decisions recorded from Z's review

1. Use `support@liquiddemocracy.us` as the public privacy, terms, and pilot-support address. (`z@liquiddemocracy.us` reaches the same Gmail account but need not be published as a second contact.)
2. Describe the supported pilot as free, with no preset end date. Concentrate support during setup and the first decisions, taper it as the organization becomes self-sufficient, and welcome continued use when the platform works for the organization.
3. Use “first supported external pilot(s).” Existing example organizations and participation by friends/family are not represented as established organizational adoption.
4. Do not emphasize a general minimum age that the service cannot independently enforce. State only that the hosted service is not directed to children under 13 and that optional age thresholds depend on identity verification.
5. Do not promise account/organization export, a portability package, or a self-hosting setup package for the initial pilot. Describe them as possible future capabilities that may be built if requested.
6. Use the best-judgment Terms draft above for the initial low-risk pilot; legal review is a future gate for higher-risk, paid, regulated, child-directed, or deliberately EU-facing use.
7. Publish the YouTube disclosure only when click-to-load training or demonstration video support ships.

**Implementation decision:** Z approved this copy for Phase 99. Use the deployment date as the visible Privacy/Terms revision date. The preview phase does not build a permanent inquiry intake, so that separate pipeline decision does not block this pass.
