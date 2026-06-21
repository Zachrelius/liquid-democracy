import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';
import { useAuth } from '../AuthContext';
import { useIsDemoUser } from '../hooks/useIsDemoUser';

export default function Landing() {
  // Phase 43 Cluster F: the "Create an org" CTA routes by auth state.
  // Logged-in users go directly to /orgs/create. Logged-out users go through
  // /register?next=/orgs/create — Login.jsx already honors `next` post-auth
  // and post-register, and VerifyEmail.jsx persists the intent across the
  // email-verification round-trip via sessionStorage.
  const { user } = useAuth();
  const startOrgTo = user ? '/orgs/create' : '/register?next=/orgs/create';
  // Phase 59 D1 — hide the "Create an org" CTA for demo users (the backend
  // rejects their POST anyway; the FE shouldn't surface a dead control).
  // Logged-out visitors still see it. Phase 79 auto-logs demo users out of
  // `/` so this is belt-and-suspenders.
  const isDemoUser = useIsDemoUser();

  // Phase 78 — shared CTA row, reused in the hero and the bottom CTA.
  const ctaButtons = (
    <>
      <Link
        to="/explore"
        className="inline-flex items-center justify-center px-6 py-3 bg-[var(--brand-primary)] text-white text-sm font-medium rounded-lg hover:bg-[var(--brand-accent)] transition-colors shadow-sm w-full sm:w-auto"
      >
        Browse and join public orgs
      </Link>
      <Link
        to="/demo"
        className="inline-flex items-center justify-center px-6 py-3 bg-white text-[var(--brand-primary)] text-sm font-medium rounded-lg border border-gray-300 hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)] transition-colors w-full sm:w-auto"
      >
        Explore a demo org
      </Link>
      {!isDemoUser && (
        <Link
          to={startOrgTo}
          className="inline-flex items-center justify-center px-6 py-3 bg-white text-[var(--brand-primary)] text-sm font-medium rounded-lg border border-gray-300 hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)] transition-colors w-full sm:w-auto"
        >
          Create an org for your group
        </Link>
      )}
      <Link
        to="/about"
        className="inline-flex items-center justify-center px-6 py-3 bg-white text-[var(--brand-primary)] text-sm font-medium rounded-lg border border-gray-300 hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)] transition-colors w-full sm:w-auto"
      >
        About the project
      </Link>
    </>
  );

  return (
    <PublicLayout>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-white via-[#F8F9FA] to-[#EEF3F9] pointer-events-none" />
        <div className="relative max-w-5xl mx-auto px-6 pt-20 pb-16 sm:pt-28 sm:pb-24 text-center">
          <img
            src="/logo.png"
            alt="Liquid Democracy logo"
            className="mx-auto w-20 h-20 sm:w-28 sm:h-28 rounded-2xl mb-6"
          />
          <h1 className="text-4xl sm:text-6xl font-semibold text-[var(--brand-primary)] tracking-tight">
            Liquid Democracy
          </h1>
          <p className="mt-5 text-lg sm:text-xl text-[#2C3E50] max-w-2xl mx-auto leading-relaxed">
            Vote directly or delegate to people you trust, on every issue, any time.
            An open-source platform for flexible accountable governance at any level.
          </p>

          {/* Phase 78 — reordered CTAs. Create-an-org hidden for demo users. */}
          <div className="mt-10 flex flex-col sm:flex-row sm:flex-wrap items-center justify-center gap-3">
            {ctaButtons}
            {!user && (
              <Link
                to="/login"
                className="inline-flex items-center justify-center px-6 py-3 text-[var(--brand-accent)] text-sm font-medium rounded-lg hover:underline w-full sm:w-auto"
              >
                Sign in
              </Link>
            )}
          </div>
        </div>
      </section>

      {/* Feature grid (grouped) */}
      <section className="max-w-5xl mx-auto px-6 pb-16">
        <p className="text-xs font-medium uppercase tracking-wider text-gray-400 text-center">
          What you can do with it
        </p>

        {/* Group A: Voice and voting */}
        <h2 className="mt-8 text-sm font-semibold text-[var(--brand-primary)]">
          Voice and voting
        </h2>
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-6">
          <FeatureCard
            title="Topic-based delegation"
            body="Delegate budget votes to the person who actually reads the financials, building policy to the architect on your board, and vote directly whenever you want."
          />
          <FeatureCard
            title="Multiple voting methods"
            body="Binary, approval, ranked-choice, and budget allocation voting. The method fits the decision."
          />
          <FeatureCard
            title="Instant revocability"
            body="Change or revoke a delegation at any time, for any reason, without explanation."
          />
          <FeatureCard
            title="Private by default"
            body="Your delegation choices are always between you and your delegate. Public delegates opt into open profiles with published voting records and rationales, so you can find people worth trusting."
          />
        </div>

        {/* Group B: Structure and trust */}
        <h2 className="mt-10 text-sm font-semibold text-[var(--brand-primary)]">
          Structure and trust
        </h2>
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-6">
          <FeatureCard
            title="Elections and offices"
            body="Define titled positions (tied to platform admin powers or not), run elections for a set term or until recall."
          />
          <FeatureCard
            title="Configurable governance"
            body="Single steward, admin council, multi-admin approval for high-stakes changes. Set the rules that fit your org, then let the platform enforce them."
          />
          <FeatureCard
            title="Identity verification"
            body="Privacy-preserving identity checks so one person means one vote. Optionally set a residency requirement or require real name matching where displayed publicly."
          />
          <FeatureCard
            title="Public delegate accountability"
            body="Delegates who opt into public profiles publish their voting records and rationales. All governance actions carry an audit trail."
          />
        </div>
      </section>

      {/* Audience section */}
      <section className="max-w-5xl mx-auto px-6 pb-16">
        <p className="text-xs font-medium uppercase tracking-wider text-gray-400 text-center">
          Built for groups that make real decisions
        </p>
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-6">
          <AudienceCard
            title="Homeowner associations"
            body="Board decisions shouldn't happen behind closed doors. Give every owner a direct vote on the issues that affect their property and their dues."
          />
          <AudienceCard
            title="Unions and locals"
            body="Contract ratification, officer elections, strike authorization. Run them transparently, with delegation so members who can't attend still have a voice."
          />
          <AudienceCard
            title="Student governments"
            body="Stop governing on behalf of students and start governing with them. Real proposals, real votes, real accountability to the people you represent."
          />
          <AudienceCard
            title="Civic and community organizations"
            body="Tenant coalitions, neighborhood councils, advocacy groups. When your organization outgrows a group chat, you need governance infrastructure, not another poll."
          />
        </div>
      </section>

      {/* Pilot explainer */}
      <section className="bg-[#F0F4F8] border-t border-b border-gray-200">
        <div className="max-w-3xl mx-auto px-6 py-16 text-center">
          <h2 className="text-xl sm:text-2xl font-semibold text-[var(--brand-primary)]">
            What "pilot stage" means
          </h2>
          <div className="mt-6 space-y-4 text-sm sm:text-base text-[#2C3E50] leading-relaxed text-left">
            <p>
              We've built all these features and tested them with 2,500+ unit tests
              and extensive in-browser testing, but we know that real organizations
              using the platform will find things that could work better. We can act
              on bug reports and feature requests quickly.
            </p>
            <p>
              If you're part of a group that wants to try making decisions with
              Liquid Democracy, feel free to create an org. The platform is set up
              for anyone to do that. But orgs are meant to be very configurable for
              different use cases, so there are a lot of settings that can be
              intimidating when you're getting started.{' '}
              <a
                href="mailto:z@liquiddemocracy.us"
                className="text-[var(--brand-accent)] font-medium hover:underline"
              >
                Reach out
              </a>{' '}
              and I'm happy to walk early orgs through the setup process and discuss
              what configuration makes sense for your group.
            </p>
            <p>
              Once we get a few orgs up and running, we'll create templates that make
              initial setup easier. I want to see real use cases in action rather
              than assume.
            </p>
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="max-w-5xl mx-auto px-6 py-16">
        <div className="flex flex-col sm:flex-row sm:flex-wrap items-center justify-center gap-3">
          {ctaButtons}
        </div>
      </section>
    </PublicLayout>
  );
}

function FeatureCard({ title, body }) {
  return (
    <div className="p-6 bg-white rounded-xl border border-gray-200 shadow-sm hover:border-[var(--brand-accent)] transition-colors">
      <h3 className="text-base font-semibold text-[var(--brand-primary)] mb-2">{title}</h3>
      <p className="text-sm text-[#2C3E50] leading-relaxed">{body}</p>
    </div>
  );
}

function AudienceCard({ title, body }) {
  return (
    <div className="p-6 bg-white rounded-xl border border-gray-200 shadow-sm hover:border-[var(--brand-accent)] transition-colors">
      <h3 className="text-base font-semibold text-[var(--brand-accent)] mb-2">{title}</h3>
      <p className="text-sm text-[#2C3E50] leading-relaxed">{body}</p>
    </div>
  );
}
