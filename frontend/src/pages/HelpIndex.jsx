import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';

/**
 * Phase 43 Cluster H — Help hub.
 *
 * Public route at /help; lists all topic pages so prospective pilot leaders
 * (and existing users who couldn't find a help link before) have a single
 * discoverable index. Groups by audience-vs-mechanics. New "Getting started"
 * pages (Phase 43 Cluster C) lead; existing concept pages follow.
 */
const TOPICS_GETTING_STARTED = [
  {
    to: '/help/getting-started-member',
    title: 'Getting started — member',
    blurb: "I just got invited or joined an org. What now?",
  },
  {
    to: '/help/getting-started-steward',
    title: 'Getting started — steward',
    blurb: "I just created an org. How do I set it up for real use?",
  },
  {
    to: '/help/getting-started-delegate',
    title: 'Getting started — public delegate',
    blurb: "I just got approved to be a public delegate. What's expected of me?",
  },
];

const TOPICS_HOW_IT_WORKS = [
  {
    to: '/help/voting-methods',
    title: 'Voting methods',
    blurb: 'Binary, approval, ranked-choice, STV — which to pick when.',
  },
  {
    to: '/help/stable-result',
    title: 'Stable Result Required',
    blurb: 'How proposals can extend until their outcome stabilizes.',
  },
  {
    to: '/help/public-delegates',
    title: 'Public delegates',
    blurb: 'Topic-scoped public delegation, accountability, and revocation.',
  },
  {
    to: '/help/organizations',
    title: 'Organizations',
    blurb: 'How orgs, sub-orgs, and membership work.',
  },
  {
    to: '/help/role-permissions',
    title: 'Roles and permissions',
    blurb: 'Per-action permissions, role presets, and the matrix UI.',
  },
  {
    to: '/help/notifications',
    title: 'Notifications',
    blurb: 'Per-event channels, presets, quiet hours, digests.',
  },
  {
    to: '/help/polis',
    title: 'Pol.is conversations',
    blurb: 'How linked pol.is conversations show up alongside proposals.',
  },
];

export default function HelpIndex() {
  return (
    <PublicLayout>
      <div className="max-w-4xl mx-auto px-4 py-12 space-y-10">
        <header>
          <h1 className="text-3xl sm:text-4xl font-semibold text-[var(--brand-primary)] tracking-tight">
            Help
          </h1>
          <p className="mt-3 text-base text-[#2C3E50]">
            Short explainers, organized by what you're trying to do.
          </p>
        </header>

        <section className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">
            Getting started
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {TOPICS_GETTING_STARTED.map((t) => (
              <HelpCard key={t.to} {...t} />
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">
            How it works
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {TOPICS_HOW_IT_WORKS.map((t) => (
              <HelpCard key={t.to} {...t} />
            ))}
          </div>
        </section>

        <p className="text-xs text-gray-500">
          Not finding what you need?{' '}
          <a
            href="mailto:z@liquiddemocracy.us"
            className="text-[var(--brand-accent)] hover:underline"
          >
            z@liquiddemocracy.us
          </a>
        </p>
      </div>
    </PublicLayout>
  );
}

function HelpCard({ to, title, blurb }) {
  return (
    <Link
      to={to}
      className="block p-5 bg-white rounded-xl border border-gray-200 shadow-sm hover:border-[var(--brand-accent)] hover:shadow transition-all"
    >
      <h3 className="text-base font-semibold text-[var(--brand-primary)] mb-1">
        {title}
      </h3>
      <p className="text-sm text-[#2C3E50] leading-relaxed">{blurb}</p>
    </Link>
  );
}
