import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';

function Section({ title, children }) {
  return (
    <section className="mt-10">
      <h2 className="text-2xl font-semibold tracking-tight text-[var(--brand-primary)]">{title}</h2>
      <div className="mt-4 space-y-4 leading-7 text-[#34495E]">{children}</div>
    </section>
  );
}

export default function Privacy() {
  return (
    <PublicLayout>
      <article className="mx-auto max-w-3xl px-6 py-14 text-[#2C3E50] sm:py-20">
        <header>
          <p className="text-sm font-semibold uppercase tracking-wider text-[var(--brand-accent)]">Hosted service policy</p>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight text-[var(--brand-primary)] sm:text-5xl">Privacy Policy</h1>
          <p className="mt-4 text-sm text-gray-500">Last updated: August 22, 2026</p>
          <p className="mt-6 text-lg leading-8">
            Liquid Democracy is a pilot-stage hosted service for organizational decision-making. This policy explains what information the service at liquiddemocracy.us collects, how it is used, when other people or service providers can access it, and the choices available to you.
          </p>
          <p className="mt-4">For privacy questions or requests, contact <a className="text-[var(--brand-accent)] underline" href="mailto:support@liquiddemocracy.us">support@liquiddemocracy.us</a>.</p>
        </header>

        <Section title="Information we collect">
          <p>When you create an account or use Liquid Democracy, we may collect:</p>
          <ul className="list-disc space-y-2 pl-6">
            <li><strong>Account information:</strong> username, display name, email address, password hash, email-verification status, and account-security records.</li>
            <li><strong>Organization information:</strong> memberships, roles, invitations, organization settings, and administrative actions.</li>
            <li><strong>Governance activity:</strong> proposals, revisions, comments, votes and ballot selections, delegation choices, vote rationales, election activity, and audit records.</li>
            <li><strong>Communications:</strong> messages sent through the platform, notification preferences, and email-delivery records.</li>
            <li><strong>Files you provide:</strong> profile images, organization logos, and other supported uploads.</li>
            <li><strong>Technical and security information:</strong> IP addresses, request timestamps, request paths, coarse error and health information, and other records needed to operate, secure, and troubleshoot the service.</li>
            <li><strong>Optional identity-verification information:</strong> verification status, jurisdiction or country results, age-band results, provider/session references, and privacy-preserving hashes derived from verified identity fields. Liquid Democracy does not store raw ID images, selfies, or raw document numbers in its own database.</li>
            <li><strong>Pilot inquiries and support requests:</strong> contact information and the content you choose to submit when asking about a pilot or requesting help.</li>
          </ul>
          <p>Please do not put sensitive personal information into proposal text, comments, pilot inquiries, or support messages unless it is necessary for your organization and you are authorized to provide it.</p>
        </Section>

        <Section title="How we use information">
          <p>We use this information to:</p>
          <ul className="list-disc space-y-2 pl-6">
            <li>provide accounts, organizations, voting, delegation, deliberation, messaging, and administrative tools;</li>
            <li>calculate results and preserve the integrity and history of organizational decisions;</li>
            <li>deliver invitations, security messages, notifications, and support;</li>
            <li>prevent abuse, investigate incidents, enforce permissions, and maintain audit records;</li>
            <li>monitor reliability, create encrypted backups, and recover the service after a failure; and</li>
            <li>understand and improve the pilot experience using coarse or aggregated operational information that does not include ballot contents or private proposal/member content.</li>
          </ul>
          <p>Liquid Democracy does not sell personal information, run an advertising network, or use ballot contents for advertising.</p>
        </Section>

        <Section title="Who can see information inside Liquid Democracy">
          <p>Visibility depends on the type of information and the choices made by you and your organization:</p>
          <ul className="list-disc space-y-3 pl-6">
            <li><strong>Votes are private from other members by default.</strong> A vote may become visible where you deliberately enabled a relevant follower relationship or registered as a public delegate on the applicable topic. Public delegates publish the relevant voting record and rationale as an accountability feature.</li>
            <li><strong>Delegation relationships are not public by default.</strong> A delegate can know that you delegated to them, and approved relationship permissions can make additional activity visible.</li>
            <li><strong>Organization administrators</strong> can manage members and see organization-level information and aggregate analytics. The standard organization-admin interface does not provide a routine view of individual ballot contents.</li>
            <li><strong>Platform administrators</strong> do not have a ballot viewer in the ordinary admin screen, and default audit responses redact ballot contents. A restricted platform-admin API exists for exceptional investigation of a specific audit entry. It requires the entry ID and a written reason, can reveal otherwise-redacted ballot fields, creates a separate audit event, and appears in the affected user&apos;s Data Access History.</li>
            <li><strong>Platform operators</strong> can access the underlying hosting systems and database when necessary to operate, secure, troubleshoot, back up, or recover the service. This means Liquid Democracy does not provide the technical secrecy of a conventional paper ballot.</li>
            <li><strong>Public organizations, proposals, delegate profiles, and activity</strong> may be visible without signing in when the organization or user has chosen a public setting. Members-only and private-organization boundaries remain subject to the platform&apos;s access controls.</li>
          </ul>
          <p>More detail about these boundaries appears on the <Link className="text-[var(--brand-accent)] underline" to="/security">Security &amp; Trust page</Link>.</p>
        </Section>

        <Section title="Service providers and optional integrations">
          <p>Liquid Democracy uses service providers to operate the hosted service:</p>
          <ul className="list-disc space-y-3 pl-6">
            <li><strong><a className="text-[var(--brand-accent)] underline" href="https://railway.com/legal/privacy" target="_blank" rel="noopener noreferrer">Railway</a></strong> hosts the application, database, and uploaded files.</li>
            <li><strong><a className="text-[var(--brand-accent)] underline" href="https://resend.com/legal/privacy-policy" target="_blank" rel="noopener noreferrer">Resend</a></strong> processes email addresses and message contents needed to deliver transactional email.</li>
            <li><strong><a className="text-[var(--brand-accent)] underline" href="https://www.cloudflare.com/privacypolicy/" target="_blank" rel="noopener noreferrer">Cloudflare R2</a></strong> stores encrypted offsite backups. Backups are encrypted before they leave the application environment, and the private recovery key is kept separately from Railway and Cloudflare.</li>
            <li><strong><a className="text-[var(--brand-accent)] underline" href="https://didit.me/terms/privacy-policy/" target="_blank" rel="noopener noreferrer">Didit</a></strong> processes identity documents and selfies only when identity verification is initiated. Didit handles those materials under its own privacy policy. Liquid Democracy stores the verification result and derived fields described above; it does not promise that Didit immediately deletes its copy after verification.</li>
            <li><strong><a className="text-[var(--brand-accent)] underline" href="https://pol.is/privacy" target="_blank" rel="noopener noreferrer">pol.is</a></strong> processes participation in a hosted pol.is conversation when an organization chooses to use that optional feature. Liquid Democracy supplies a pseudonymous participant identifier rather than a display name, but platform operators may be able to connect that identifier to an account for moderation or audited export purposes.</li>
          </ul>
          <p>These providers operate under their own terms and privacy policies. We may also disclose information when reasonably necessary to comply with law, protect users or the service, investigate abuse, or complete a business transfer, subject to applicable obligations.</p>
        </Section>

        <Section title="Browser storage">
          <p>The application uses browser session storage for sign-in tokens and temporary navigation or interface state. Session storage is normally cleared when the browser session ends. It uses local storage for limited convenience choices such as the last organization visited and dismissed interface prompts. Liquid Democracy does not currently use third-party advertising trackers.</p>
        </Section>

        <Section title="Security and backups">
          <p>Passwords are stored as bcrypt hashes rather than plaintext. Connections to the public service use HTTPS. Access tokens are short-lived, refresh tokens rotate, and only one-way refresh-token digests are stored in the database.</p>
          <p>The service uses access controls, rate limiting, audit logging, production monitoring, provider-native recovery points, and daily encrypted offsite backups. Both the provider-native volume restore process and the encrypted offsite database restore process have been rehearsed using disposable recovery targets. No internet service can guarantee perfect security or availability.</p>
        </Section>

        <Section title="Retention">
          <p>Account, membership, governance, and audit information is generally retained while needed to provide the service and preserve the history and integrity of organizational decisions. Notifications are ordinarily cleaned up after approximately 90 days. Closed proposals, vote records, and audit events may be retained longer because deleting them could change or obscure the historical decision record.</p>
          <p>Backups use rolling retention schedules, so information removed from the live system may remain in encrypted or provider-managed recovery points until those recovery points expire. Backup copies are used for disaster recovery, not ordinary access.</p>
          <p>Optional providers, including Didit and pol.is, apply their own retention policies to information they process.</p>
        </Section>

        <Section title="Access, correction, export, and deletion requests">
          <p>You can update some account information in the service. For other access, correction, export, restriction, or deletion requests, contact <a className="text-[var(--brand-accent)] underline" href="mailto:support@liquiddemocracy.us">support@liquiddemocracy.us</a>.</p>
          <p>The initial pilot does not include a complete self-service account or organization export, a reusable portability package, or a supported self-hosting migration package. Those capabilities may be developed later if a pilot organization needs them, but users and organizations should not rely on them being available. Requests will be reviewed using the tools reasonably available at the time and may require identity verification and coordination with the relevant organization. Some governance, security, backup, or audit records may need to be retained, restricted, or de-identified rather than deleted when necessary to preserve other users&apos; rights, organizational decision integrity, security, or legal obligations.</p>
        </Section>

        <Section title="Children">
          <p>The hosted service is not directed to children under 13. Do not create or administer an account for a child under 13. If you believe a child under 13 has provided personal information through the service, contact <a className="text-[var(--brand-accent)] underline" href="mailto:support@liquiddemocracy.us">support@liquiddemocracy.us</a> so the operator can restrict the account and address the information as required.</p>
          <p>Nothing in this section limits rights that apply under applicable law.</p>
        </Section>

        <Section title="Changes to this policy">
          <p>This policy may change as the pilot service, providers, or legal obligations change. The page will show the current revision date. Material changes should be communicated through the service or by email when reasonably appropriate.</p>
        </Section>

        <Section title="Contact">
          <p>Privacy questions and requests: <a className="text-[var(--brand-accent)] underline" href="mailto:support@liquiddemocracy.us">support@liquiddemocracy.us</a>.</p>
        </Section>
      </article>
    </PublicLayout>
  );
}
