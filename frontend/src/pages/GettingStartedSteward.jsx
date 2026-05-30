import { Link } from 'react-router-dom';
import HelpBackLink from '../components/HelpBackLink';

/**
 * Phase 43 Cluster C — Getting started as a steward.
 * Copy wired verbatim from phase43_help_content.md.
 */
export default function GettingStartedSteward() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">
          Getting started as a steward
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          You've created an organization — here's how to set it up.
        </p>
      </div>

      <Section title="Welcome — you're the steward">
        <p>
          You just created an organization, which makes you its first administrator (its "steward"). Right now it's an empty space. This page walks you through the handful of steps that turn it into a place your members can actually deliberate and decide. You don't have to do all of it at once — set up the essentials, invite a few people, and grow from there.
        </p>
        <p>
          Everything below lives under the <strong>Admin</strong> menu in the top bar.
        </p>
        <ScreenshotPlaceholder caption="The Admin dropdown menu open, showing Org Settings, Permissions, Members, Proposals, Topics, etc." />
      </Section>

      <Section title="Step 1: Set up your organization">
        <p>
          Open <strong>Admin → Org Settings</strong>. Give your organization a clear description so members and prospective members know what it's for. This is also where you control your <strong>join policy</strong> — whether people join by invitation only, by requesting approval, or freely — and other organization-wide settings.
        </p>
      </Section>

      <Section title="Step 2: Create your topics">
        <p>
          Open <strong>Admin → Topics</strong>. Topics are the subject areas your organization makes decisions about — things like Budget, Governance, or Events. They do two important jobs: they organize your proposals, and they're the unit people delegate on (a member can delegate "Budget" to one person and vote on everything else themselves).
        </p>
        <p>
          Start with a small, clear set of topics that match how your group actually thinks about its decisions. You can always add or adjust them later. (We deliberately don't pre-fill topics for you — the right set depends on your organization, and a short, accurate list beats a long, generic one.)
        </p>
      </Section>

      <Section title="Step 3: Invite your members">
        <p>
          Open <strong>Admin → Members</strong> to invite people in, and <strong>Admin → Permissions</strong> to decide who can do what — for example, who else can administer the organization, who can create proposals, and who reviews delegate applications. Most organizations start with a small set of administrators and open proposal-creation to members; you can tighten or loosen this as you learn what works.
        </p>
      </Section>

      <Section title="Step 4: Post your first proposal">
        <p>
          A proposal is any decision you want the group to weigh in on. Select <strong>Create proposal</strong> (on the Proposals page or under <strong>Admin → Proposals</strong>), describe what's being decided, attach the relevant topic, and choose how it should be voted on. A good first proposal is something real but low-stakes — it gives everyone a chance to learn the flow before anything important is on the line.
        </p>
      </Section>

      <Section title="Step 5 (optional): Set up delegates">
        <p>
          Part of what makes this platform different is that members can delegate their vote, by topic, to people they trust. If your organization wants public delegates — members who openly represent others on certain topics — you'll review their applications under <strong>Admin → Delegate Applications</strong>. You can point prospective delegates to <Link to="/help/getting-started-delegate" className="text-[var(--brand-accent)] hover:underline">Getting started as a delegate</Link>.
        </p>
      </Section>

      <Section title="A note on growing into it">
        <p>
          The <strong>Admin</strong> menu has more than these five steps — Analytics, Polises (group-opinion discussions), Sub-Organizations, and more. You don't need any of it on day one. Set up topics, invite a few people, run one real decision, and let the rest follow as your organization finds its rhythm.
        </p>
      </Section>

      <Section title="Where to go next">
        <ul className="list-disc pl-5 space-y-1">
          <li><Link to="/help/organizations" className="text-[var(--brand-accent)] hover:underline">Organizations</Link> — how organizations and membership work.</li>
          <li><Link to="/help/role-permissions" className="text-[var(--brand-accent)] hover:underline">Role permissions</Link> — the permission system in detail.</li>
          <li><Link to="/help/voting-methods" className="text-[var(--brand-accent)] hover:underline">Voting methods</Link> — choosing the right method for a decision.</li>
        </ul>
      </Section>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
      <h2 className="text-lg font-semibold text-[var(--brand-primary)]">{title}</h2>
      <div className="text-sm text-gray-700 space-y-2 leading-relaxed">{children}</div>
    </section>
  );
}

function ScreenshotPlaceholder({ caption }) {
  return (
    <div className="my-3 p-3 bg-gray-50 border border-dashed border-gray-300 rounded text-xs text-gray-500 italic">
      [Screenshot pending: {caption}]
    </div>
  );
}
