import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';

const PILOT_EMAIL = 'mailto:support@liquiddemocracy.us?subject=Pilot%20conversation';

function usePilotMetadata() {
  useEffect(() => {
    const previousTitle = document.title;
    const existingDescription = document.querySelector('meta[name="description"]');
    const previousDescription = existingDescription?.getAttribute('content') ?? null;
    const description = existingDescription || document.createElement('meta');

    if (!existingDescription) {
      description.setAttribute('name', 'description');
      document.head.appendChild(description);
    }

    document.title = 'Supported organizational pilots | Liquid Democracy';
    description.setAttribute(
      'content',
      'A supported, no-cost Liquid Democracy pilot for known-member organizations making meaningful, correctable decisions.',
    );

    return () => {
      document.title = previousTitle;
      if (existingDescription) {
        if (previousDescription == null) description.removeAttribute('content');
        else description.setAttribute('content', previousDescription);
      } else {
        description.remove();
      }
    };
  }, []);
}

function ActionLink({ children, secondary = false, ...props }) {
  const className = secondary
    ? 'inline-flex min-h-11 items-center justify-center rounded-lg border border-[#B8C2CC] bg-white px-5 py-3 text-sm font-semibold text-[var(--brand-primary)] transition-colors hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)]'
    : 'inline-flex min-h-11 items-center justify-center rounded-lg bg-[var(--brand-primary)] px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-[var(--brand-accent)]';
  return <a className={className} {...props}>{children}</a>;
}

function Section({ eyebrow, title, children, tinted = false }) {
  return (
    <section className={tinted ? 'bg-[#EDF3F7]' : 'bg-white'}>
      <div className="mx-auto max-w-5xl px-6 py-14 sm:py-20">
        {eyebrow && (
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[var(--brand-accent)]">
            {eyebrow}
          </p>
        )}
        <h2 className="mt-2 max-w-3xl text-3xl font-semibold tracking-tight text-[var(--brand-primary)] sm:text-4xl">
          {title}
        </h2>
        <div className="mt-7 text-base leading-7 text-[#34495E] sm:text-lg sm:leading-8">
          {children}
        </div>
      </div>
    </section>
  );
}

function Step({ number, title, children }) {
  return (
    <li className="relative rounded-xl border border-[#D8E0E7] bg-white p-5 shadow-sm">
      <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[var(--brand-primary)] text-sm font-bold text-white">
        {number}
      </span>
      <h3 className="mt-4 text-lg font-semibold text-[var(--brand-primary)]">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-[#4A5B6A]">{children}</p>
    </li>
  );
}

function Faq({ question, children }) {
  return (
    <div className="border-b border-[#D8E0E7] py-6 last:border-b-0">
      <h3 className="text-lg font-semibold text-[var(--brand-primary)]">{question}</h3>
      <div className="mt-2 text-base leading-7 text-[#465A69]">{children}</div>
    </div>
  );
}

export default function Pilot() {
  usePilotMetadata();

  return (
    <PublicLayout>
      <main className="bg-[#F8F9FA] text-[#2C3E50] print:bg-white">
        <section className="relative overflow-hidden border-b border-[#D8E0E7] bg-white">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-[#DCEAF3] opacity-70 motion-safe:transition-transform motion-reduce:transition-none"
          />
          <div className="relative mx-auto grid max-w-6xl gap-10 px-6 py-16 sm:py-24 lg:grid-cols-[1.25fr_0.75fr] lg:items-center">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--brand-accent)]">
                Supported organizational pilots
              </p>
              <h1 className="mt-4 max-w-4xl text-4xl font-semibold tracking-tight text-[var(--brand-primary)] sm:text-6xl sm:leading-[1.05]">
                Pilot Liquid Democracy with your organization
              </h1>
              <p className="mt-6 max-w-3xl text-lg leading-8 text-[#425466] sm:text-xl">
                Give members a direct vote when they want one and the ability to delegate by topic when they do not. We are recruiting a small number of organizations for a supported, no-cost pilot of Liquid Democracy.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row print:hidden">
                <ActionLink href={PILOT_EMAIL}>Request a pilot conversation</ActionLink>
                <Link
                  to="/demo"
                  className="inline-flex min-h-11 items-center justify-center rounded-lg border border-[#B8C2CC] bg-white px-5 py-3 text-sm font-semibold text-[var(--brand-primary)] transition-colors hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)]"
                >
                  Explore the live demo
                </Link>
              </div>
              <p className="mt-6 max-w-3xl border-l-4 border-[var(--brand-accent)] pl-4 text-sm leading-6 text-[#526475]">
                Best suited to known-member organizations making meaningful but correctable internal decisions. Not a certified public-election system.
              </p>
            </div>
            <aside className="rounded-2xl border border-[#C7D4DE] bg-[#F4F8FA] p-6 shadow-sm sm:p-8">
              <p className="text-sm font-semibold uppercase tracking-wider text-[var(--brand-accent)]">The basic idea</p>
              <ol className="mt-5 space-y-5">
                <li><strong className="block text-[var(--brand-primary)]">Vote when it matters to you.</strong><span className="text-sm leading-6 text-[#526475]">Every member keeps the right to vote directly.</span></li>
                <li><strong className="block text-[var(--brand-primary)]">Delegate by topic.</strong><span className="text-sm leading-6 text-[#526475]">Trust different people on budgets, policy, operations, or any topic your group defines.</span></li>
                <li><strong className="block text-[var(--brand-primary)]">Take your voice back immediately.</strong><span className="text-sm leading-6 text-[#526475]">A direct vote overrides delegation, and delegations can be revoked.</span></li>
              </ol>
            </aside>
          </div>
        </section>

        <Section eyebrow="Member value" title="Representation without giving up your own voice">
          <div className="grid gap-6 md:grid-cols-2">
            <p>
              Members can vote directly on any proposal or delegate topic by topic to people whose judgment they trust. A direct vote always takes priority, and a delegation can be overridden for one decision or revoked entirely without waiting for an election cycle.
            </p>
            <p>
              Organizations can use binary, approval, ranked-choice, and budget voting methods. Public delegates make their relevant record and reasoning accountable; private delegation relationships require consent and remain subject to the platform&apos;s visibility boundaries.
            </p>
          </div>
        </Section>

        <Section eyebrow="Initial fit" title="A good fit for the first supported pilot" tinted>
          <p className="max-w-4xl">
            The strongest early fit is a known-member organization with roughly 20–200 members, a committed primary steward and backup contact, recurring decisions, and room to correct a result or process if something goes wrong.
          </p>
          <div className="mt-8 grid gap-6 md:grid-cols-2">
            <div className="rounded-xl bg-white p-6 shadow-sm">
              <h3 className="text-lg font-semibold text-[var(--brand-primary)]">Promising examples</h3>
              <p className="mt-3 text-base leading-7">Clubs, associations, cooperatives, volunteer networks, student or community groups, advocacy organizations, and committees making real internal choices.</p>
            </div>
            <div className="rounded-xl border border-[#E2C7C7] bg-[#FFF9F9] p-6">
              <h3 className="text-lg font-semibold text-[#7A3030]">Not appropriate for the initial pilot</h3>
              <p className="mt-3 text-base leading-7">Governmental elections, legally mandated secret ballots, contentious officer elections, contract ratification, emergency decisions, or any process where an outage, error, or correction would create unacceptable harm.</p>
            </div>
          </div>
        </Section>

        <Section eyebrow="What the pilot includes" title="Supported from setup to self-sufficiency">
          <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Step number="1" title="Discovery conversation">We learn how your organization works and identify a suitable first decision.</Step>
            <Step number="2" title="Guided setup">We help configure membership, topics, permissions, and voting settings.</Step>
            <Step number="3" title="Steward rehearsal">Your steward and backup contact practice the member and administrator experience.</Step>
            <Step number="4" title="Early decisions">Run one to three real but correctable decisions with close support.</Step>
            <Step number="5" title="Reflection">Review comprehension, participation, workload, missing features, and trust.</Step>
          </ol>
          <p className="mt-8 max-w-4xl">
            Support is closest during setup and the first decisions, then becomes lighter as the organization becomes comfortable and self-sufficient. The pilot has no preset end date, and continued use is welcome when the platform works for the organization.
          </p>
        </Section>

        <Section eyebrow="Your part" title="What the organization contributes" tinted>
          <ul className="grid gap-4 sm:grid-cols-2">
            {[
              'Name a primary steward and a backup contact.',
              'Recruit a genuine member cohort rather than a purely fictional test group.',
              'Tell members the service is pilot-stage and explain how results will be used.',
              'Run at least one real, appropriate, correctable decision.',
              'Share candid feedback on comprehension, participation, workload, missing features, and trust.',
            ].map(item => (
              <li key={item} className="rounded-lg border border-[#D6E0E7] bg-white px-5 py-4 text-base leading-7">{item}</li>
            ))}
          </ul>
        </Section>

        <Section eyebrow="Trust" title="Honest boundaries, tested recovery">
          <div className="space-y-5">
            <p>
              Liquid Democracy provides institutional privacy controls, not the technical secrecy of a paper ballot. Ordinary organization-admin and platform-admin screens do not provide a routine ballot viewer. A restricted platform-admin API can retrieve one specific unredacted audit entry only with its entry ID and a written reason; that access creates another audit event and appears in the affected user&apos;s Data Access History. The platform operator also has underlying database access for operations, security, troubleshooting, backup, and recovery.
            </p>
            <p>
              The hosted service uses HTTPS, hashed passwords, short-lived access tokens, rotating refresh credentials stored as one-way digests, scoped permissions, audit logging, rate limits, internal and external monitoring, provider-native recovery points, and daily encrypted offsite backups. Both native-volume restoration and encrypted offsite database restoration have been rehearsed successfully against isolated disposable targets.
            </p>
            <p>
              Government-ID verification is optional and normally off unless an organization needs it. When used, Didit processes the documents and selfies. Liquid Democracy stores verification results and privacy-preserving derived fields rather than raw ID images or document numbers.
            </p>
            <nav aria-label="Pilot trust resources" className="flex flex-wrap gap-x-6 gap-y-3 pt-2 print:hidden">
              <Link to="/security" className="font-semibold text-[var(--brand-accent)] underline hover:text-[var(--brand-primary)]">Security &amp; Trust</Link>
              <Link to="/privacy" className="font-semibold text-[var(--brand-accent)] underline hover:text-[var(--brand-primary)]">Privacy Policy</Link>
              <a href="https://github.com/Zachrelius/liquid-democracy" target="_blank" rel="noopener noreferrer" className="font-semibold text-[var(--brand-accent)] underline hover:text-[var(--brand-primary)]">GitHub source</a>
            </nav>
          </div>
        </Section>

        <Section eyebrow="Questions" title="Pilot FAQ" tinted>
          <div className="rounded-xl border border-[#D8E0E7] bg-white px-6 sm:px-8">
            <Faq question="Does the pilot cost anything?">
              <p>No. Liquid Democracy is free to use during and after the pilot. There is no subscription fee. Pilot organizations also receive hands-on setup and early support at no charge.</p>
            </Faq>
            <Faq question="How many members do we need?">
              <p>Roughly 20–200 members is the strongest initial range, but a committed steward and an appropriate, correctable decision matter more than an exact number.</p>
            </Faq>
            <Faq question="Does everyone have to verify their identity?">
              <p>No. Government-ID verification is optional and normally off unless an organization&apos;s use case needs it. An age threshold works only through that optional verification flow; the platform does not otherwise verify age.</p>
            </Faq>
            <Faq question="Can administrators see how members voted?">
              <p>No. Organization administrators can see membership and aggregate results, but not individual members&apos; ballots. Members can choose to make some voting activity visible through public-delegate or follower settings. Because Liquid Democracy is a hosted service, the platform operator can technically access stored data; the Privacy and Security &amp; Trust pages explain that narrow trust boundary.</p>
            </Faq>
            <Faq question="Is this a legally binding election system?">
              <p>No. The organization decides what authority to give a platform result and remains responsible for any separate legal, procedural, notice, meeting, record, or ballot requirements.</p>
            </Faq>
            <Faq question="Can we keep using the platform if the pilot works for us?">
              <p>Yes. There is no preset end, although ongoing support becomes lighter. Complete export, portability, and supported self-hosting migration packages are not included in the initial pilot; they may be considered as future work if requested.</p>
            </Faq>
            <Faq question="What if we find a bug or need help?">
              <p>Email <a className="text-[var(--brand-accent)] underline" href="mailto:support@liquiddemocracy.us">support@liquiddemocracy.us</a>. The service has operational monitoring and alerts, but the pilot does not promise an uptime SLA or a fixed response time.</p>
            </Faq>
          </div>
        </Section>

        <section className="bg-[var(--brand-primary)] text-white print:bg-white print:text-[#2C3E50]">
          <div className="mx-auto max-w-4xl px-6 py-16 text-center sm:py-20">
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">Interested in trying it with your organization?</h2>
            <p className="mx-auto mt-5 max-w-2xl text-base leading-7 text-[#E6EEF4] print:text-[#2C3E50]">
              You do not need a finished plan. Share only enough context for us to understand your organization and a possible first use.
            </p>
            <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row print:hidden">
              <ActionLink href={PILOT_EMAIL}>Email about a pilot</ActionLink>
              <Link to="/demo" className="inline-flex min-h-11 items-center justify-center rounded-lg border border-white/60 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-white hover:text-[var(--brand-primary)]">Explore the demo</Link>
            </div>
            <p className="mx-auto mt-6 max-w-3xl text-sm leading-6 text-[#CAD7E1] print:text-[#526475]">
              Please do not email member lists, ballots, identity documents, confidential disputes, or other sensitive personal information.
            </p>
          </div>
        </section>
      </main>
    </PublicLayout>
  );
}
