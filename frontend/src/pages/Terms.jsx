import PublicLayout from '../components/PublicLayout';

function Section({ title, children }) {
  return (
    <section className="mt-10">
      <h2 className="text-2xl font-semibold tracking-tight text-[var(--brand-primary)]">{title}</h2>
      <div className="mt-4 space-y-4 leading-7 text-[#34495E]">{children}</div>
    </section>
  );
}

export default function Terms() {
  return (
    <PublicLayout>
      <article className="mx-auto max-w-3xl px-6 py-14 text-[#2C3E50] sm:py-20">
        <header>
          <p className="text-sm font-semibold uppercase tracking-wider text-[var(--brand-accent)]">Hosted pilot terms</p>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight text-[var(--brand-primary)] sm:text-5xl">Terms of Service</h1>
          <p className="mt-4 text-sm text-gray-500">Last updated: August 22, 2026</p>
          <p className="mt-6 text-lg leading-8">These terms govern use of the hosted Liquid Democracy service at liquiddemocracy.us, currently operated as an early-stage project by the founder of Liquid Democracy. The service is a pilot-stage tool for organizational decision-making. By creating an account or using the service, you agree to these terms. Questions may be sent to <a className="text-[var(--brand-accent)] underline" href="mailto:support@liquiddemocracy.us">support@liquiddemocracy.us</a>.</p>
        </header>

        <Section title="What the service is">
          <p>Liquid Democracy lets organizations create proposals, deliberate, vote directly, and delegate voting power to trusted people by topic. It includes membership, administrative, notification, identity-verification, and governance tools.</p>
          <p>The hosted service is not a certified public-election system and does not itself make an organization&apos;s decisions legally binding. Each organization is responsible for determining what authority, if any, it gives to a platform decision and whether separate notices, meetings, records, ballots, approvals, or legal procedures are required.</p>
          <p>Do not use the pilot service as the sole system for governmental elections, legally mandated secret ballots, emergency decisions, or decisions where an outage, error, or later correction would create unacceptable harm.</p>
        </Section>

        <Section title="Accounts and security">
          <p>Provide accurate account information, keep your credentials secure, and do not allow another person to use your account. Do not create duplicate accounts to obtain additional voting power or evade an organization rule. Notify <a className="text-[var(--brand-accent)] underline" href="mailto:support@liquiddemocracy.us">support@liquiddemocracy.us</a> if you believe an account or organization has been compromised.</p>
          <p>The hosted service is not directed to children under 13. Do not create or administer an account for a child under 13.</p>
          <p>The operator may restrict or suspend access when reasonably necessary to protect users, investigate abuse, comply with law, or preserve service integrity.</p>
        </Section>

        <Section title="Member responsibilities">
          <p>You agree not to:</p>
          <ul className="list-disc space-y-2 pl-6">
            <li>manipulate voting, identity, delegation, invitation, or verification systems;</li>
            <li>impersonate another person or misrepresent your authority;</li>
            <li>harass, threaten, defraud, or unlawfully discriminate against others;</li>
            <li>upload malicious code or attempt unauthorized access;</li>
            <li>publish information you do not have the right to share; or</li>
            <li>use the service in violation of applicable law or an organization&apos;s valid rules.</li>
          </ul>
          <p>Members remain responsible for the proposals, comments, messages, rationales, profile information, and files they submit.</p>
        </Section>

        <Section title="Organization responsibilities">
          <p>The people who create and administer an organization are responsible for:</p>
          <ul className="list-disc space-y-2 pl-6">
            <li>having authority to invite or enroll members and administer the organization&apos;s use;</li>
            <li>selecting settings and voting methods appropriate to the organization&apos;s rules and decisions;</li>
            <li>explaining the pilot, relevant privacy boundaries, and whether results are advisory or authoritative;</li>
            <li>providing fair notice and sufficient time for participation;</li>
            <li>responding to member questions, moderation needs, and requests involving organization-controlled information;</li>
            <li>maintaining any legally required records outside the platform; and</li>
            <li>avoiding a use case that requires legal, security, accessibility, or election guarantees the pilot service does not provide.</li>
          </ul>
          <p>An organization&apos;s administrators can manage substantial parts of its configuration and membership. Their actions are attributable to the organization, not automatically endorsed by the platform operator.</p>
        </Section>

        <Section title="Pilot-stage service and support">
          <p>The service is provided on a best-effort pilot basis. Features may change, errors may occur, and planned maintenance or provider failures may interrupt access. The operator maintains monitoring and tested backup/recovery procedures but does not promise uninterrupted availability, a particular recovery time, or that no data can ever be lost.</p>
          <p>Pilot support arrangements described on /pilot or in a separate Pilot Participation Understanding supplement these general terms for an accepted pilot organization. They do not create an uptime or response-time guarantee unless a signed agreement explicitly says otherwise.</p>
        </Section>

        <Section title="Privacy">
          <p>The Privacy Policy explains the information the service processes, visibility boundaries, service providers, backups, and available requests. The Security &amp; Trust page explains why liquid democracy does not provide the same technical ballot secrecy as a conventional paper election.</p>
        </Section>

        <Section title="Organization and user content">
          <p>You retain any rights you hold in content you submit. You give the operator permission to host, copy, process, transmit, back up, and display that content as needed to provide, secure, and recover the service and to honor the visibility settings you or your organization select.</p>
          <p>Do not submit content that infringes another person&apos;s rights or that you are not authorized to disclose. The operator may restrict or remove content when reasonably necessary to address abuse, security, legal obligations, or harm, while preserving an appropriate audit record where the platform supports it.</p>
        </Section>

        <Section title="Ending use">
          <p>You may stop using the service. Organization leaders may remove members or stop their organization&apos;s participation according to their authority and the organization&apos;s settings. The initial pilot has no preset end date, and continued use is welcome when the platform works for the organization. Support is concentrated during setup and early decisions and becomes lighter as the organization becomes self-sufficient.</p>
          <p>Complete self-service organization export and deletion, a reusable portability package, and a supported self-hosting migration package are not included in the initial pilot. They may be considered as future features if requested, but an organization should not rely on them without a separate written commitment.</p>
          <p>Some decision, audit, security, and backup records may remain as described in the Privacy Policy. The operator may discontinue the pilot service, but should provide reasonable notice and a practical opportunity to discuss available data handling when circumstances permit.</p>
        </Section>

        <Section title="Open-source software">
          <p>The source code is available under the MIT License on GitHub. The MIT License governs use, copying, modification, and distribution of the source code. These hosted-service terms govern accounts and use of liquiddemocracy.us; they do not replace the source-code license.</p>
        </Section>

        <Section title="Disclaimers and liability">
          <p>To the fullest extent permitted by applicable law, the hosted service is provided “as is” and “as available,” without a promise that it will always be available, error-free, secure, or suitable for a particular legal or governance purpose. The operator is not responsible for indirect, incidental, special, consequential, or punitive losses arising from use of or inability to use the service. Nothing in these terms excludes a warranty, right, remedy, or liability that applicable law does not allow to be excluded or limited.</p>
          <p>If any part of these terms cannot be enforced, the remaining parts continue to apply. These terms and any accepted pilot understanding are the entire agreement about use of the hosted pilot service unless the operator and an organization agree to something different in writing.</p>
        </Section>

        <Section title="Changes">
          <p>The operator may update these terms as the pilot service changes. The page will show the current revision date. Material changes should be communicated through the service or by email when reasonably appropriate. Continued use after the effective date of updated terms constitutes acceptance to the extent permitted by applicable law.</p>
        </Section>

        <Section title="Contact">
          <p>Questions about these terms: <a className="text-[var(--brand-accent)] underline" href="mailto:support@liquiddemocracy.us">support@liquiddemocracy.us</a>.</p>
        </Section>
      </article>
    </PublicLayout>
  );
}
