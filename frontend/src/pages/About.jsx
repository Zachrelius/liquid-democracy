import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';

export default function About() {
  return (
    <PublicLayout>
      <article className="max-w-3xl mx-auto px-6 py-16 sm:py-20 text-[#2C3E50]">
        <header className="mb-12">
          <p className="text-sm font-medium text-[var(--brand-accent)] uppercase tracking-wider">
            About the project
          </p>
          <h1 className="mt-2 text-4xl sm:text-5xl font-semibold text-[var(--brand-primary)] tracking-tight">
            Democracy, unbundled.
          </h1>
          <p className="mt-5 text-lg text-[#2C3E50] leading-relaxed">
            Most of us get to vote once every few years, on a package of
            positions we didn't choose, represented by a person we mostly
            don't know, on questions we mostly can't see coming. We think
            there's a better way, and we're building software to try it.
          </p>
        </header>

        <Section title="The problem with how we vote now">
          <p>
            Modern representative democracy was designed for a world where
            information traveled on horseback. Its core compromises made
            sense then: voters couldn't weigh in on every issue, so they
            chose a person to weigh in for them. They couldn't update that
            choice often, so they bundled four or six years of decisions
            into a single ballot.
          </p>
          <p>
            Those compromises haven't aged well. Voting is too rare. The
            gap between the moment a decision matters and the next time
            you can express an opinion is measured in years. Representation
            is too coarse. A single person stands in for you on healthcare,
            foreign policy, zoning, education, and tax policy, even though
            their expertise and your priorities only overlap on a slice of
            that. And there's no way to bring outside knowledge in: the
            people voting on a given issue in a legislature are rarely the
            people who know it best, and someone who does has no channel
            to influence the outcome unless they already hold office.
          </p>
          <p>
            None of this is a new observation. Liquid democracy has been
            discussed for a long time as a way to fix it. What's been
            missing is more real test cases and easy to use software to
            run them.
          </p>
        </Section>

        <Section title="What liquid democracy is">
          <p>
            In a liquid democracy, decisions are made proposal by proposal.
            On any given proposal you have three options: vote directly,
            delegate your vote to someone you trust on that topic, or sit
            it out. Most people will delegate most of the time. You're not
            signing up to follow every debate in your city or country.
            You're picking the people whose judgment you trust on the
            topics you care about, and getting on with your life.
          </p>
          <p>
            Delegation comes in two flavors. Public delegates register
            openly on specific topics, post their reasoning and vote in
            public, anyone can delegate to them, and their full voting
            record on those topics is visible to everyone. Most users will
            probably rely on public delegates most of the time, the way
            you follow a journalist or a subject-matter expert today but
            with actual weight behind it. Private delegation is for the
            people in your actual life: a friend who's a nurse, a colleague
            who works in climate policy, a neighbor who thinks carefully
            about budgets. Private delegations require mutual consent, and
            the delegate's votes stay visible only to the people who
            delegated to them.
          </p>
          <p>
            Either way, delegations are per-topic and revocable at any
            time. The moment you disagree with how your delegate is voting,
            you can take your vote back, for one proposal or permanently,
            without explanation. Delegations are non-transitive by default:
            if your delegate also delegates, their delegate doesn't
            automatically get your vote. You decide whether to follow that
            chain, fall back to voting directly, or redelegate.
          </p>
          <p>
            The result is a system that preserves what representation is
            good at, letting expertise influence decisions, while fixing
            what it's bad at: low granularity, slow correction, and weak
            accountability.
          </p>
        </Section>

        <Section title="Why we're building this">
          <p>
            The idea is decades old but implementations are scarce. A few
            academic prototypes, a few abandoned projects, a handful of
            organizations that built something internal and never released
            it. What's missing is a production-quality, open-source
            platform that small organizations (clubs, co-ops, unions,
            non-profits, online communities, student governments) can
            adopt without needing to hire engineers.
          </p>
          <p>
            That's what this is. It's a pilot-stage, open-source
            implementation of liquid democracy, designed to be usable today
            by organizations that want to try governing themselves this
            way.
          </p>
          <p>
            The path we're betting on goes in stages. First, prove the
            model with small organizations: groups already making
            collective decisions, where the cost of trying something new
            is low and the feedback is fast. Learn what works, fix what
            doesn't. From there, the natural next step is local government:
            a city or county adopting liquid democracy for participatory
            budgeting, ordinances, advisory votes or eventually full
            governance. That deployment might be a refinement of this
            platform, or a new implementation inspired and informed by
            what this one taught us. Either is a win. The point is a
            credible path from "interesting idea" to "running
            infrastructure."
          </p>
          <p>
            The "we" on this page is currently one person plus a small
            team of AI coding agents working in partnership. I couldn't
            have built anything near this scope without these amazing new
            tools that are in a lot of ways starting to feel like genuine
            collaborative partners.
          </p>
          <p>
            More on the personal motivation and how this fits into a
            longer arc:{' '}
            <Link
              to="/why"
              className="text-[var(--brand-accent)] hover:text-[var(--brand-primary)] underline"
            >
              the longer answer →
            </Link>
          </p>
        </Section>

        <Section title="What's built">
          <p>
            The platform is live at liquiddemocracy.us and in pilot use by
            real organizations. Everything below is shipped and running.
          </p>
          <p>
            <strong>Voting.</strong> Binary (yes/no/abstain), approval,
            ranked-choice including single transferable vote, and budget
            voting — either allocating a fixed pool of money across competing
            priorities or deciding whether to fund discrete items. Approval and
            ranked-choice voting support single and multi-winner
            configurations, configurable by proposal and by org. Method-aware
            tallying, configurable pass and quorum thresholds, and write-in
            options during deliberation. A sustained-majority mode that
            requires a winning result to hold stable across multiple evaluation
            windows before a proposal resolves — a guard against last-minute
            vote spikes.
          </p>
          <p>
            <strong>Delegation.</strong> Topic-based delegation with public and
            private delegates, mutual-consent permissions, configurable chain
            behavior (accept sub-delegation, revert to direct, or abstain), and
            cycle prevention. Public delegates register on specific topics,
            post position statements, vote in the open, and build a visible
            track record with per-vote rationales. Private delegations require
            a consent-gated follow relationship. Delegation strategy is
            configurable per user: strict topic-precedence ordering or
            relevance-weighted resolution that considers how well a delegate's
            topics match a given proposal. Per-topic delegation can be disabled
            by org admins for decisions that should be direct-vote-only.
          </p>
          <p>
            <strong>Visualization.</strong> Interactive D3 force-directed
            graphs showing how votes and delegations flow through the network
            for each proposal, with method-aware layouts for binary, approval,
            and ranked-choice votes. A Sankey chart for round-by-round RCV
            transfers. A support trajectory chart tracking vote momentum over a
            proposal's voting window. Privacy-preserving by default: unfollowed
            voters appear as unlinkable anonymous nodes.
          </p>
          <p>
            <strong>Governance.</strong> Elections are a proposal subtype that
            reuse the full voting and tally machinery — self-nomination during
            deliberation, any voting method, slate refresh or vacancy-fill
            modes, and configurable quorum. Named titles and offices
            (President, Treasurer, Council Member, etc.) with optional binding
            to platform roles, configurable cardinality, and support for both
            direct appointment and elections. Scheduled fixed-term elections
            with automatic re-election triggers. Cosign-gated proposals let
            members without proposal-create permission petition for a vote by
            gathering signatures. Multi-admin approval for destructive actions
            requiring N-of-M ratification. Organizations can run in
            single-steward mode with one designated leader or admin-council
            mode with shared authority, each with a cardinality floor
            guaranteeing at least one governor at all times.
          </p>
          <p>
            <strong>Organizations.</strong> Multi-tenant: many independent
            organizations on one platform, each with their own members, topics,
            proposals, and configuration. Sub-organizations for nested decision
            scopes (departments, locals, committees). A three-axis access model
            controlling join policy (open, approval, invite-only),
            discoverability (listed, unlisted, hidden), and activity visibility
            (public or members-only) independently. A public discovery page for
            browsing listed organizations. Per-org branding. Email-based
            invitations with role assignment.
          </p>
          <p>
            <strong>Identity verification.</strong> Five-level verification
            state model from email-only through residency-verified, integrated
            with Didit for real KYC verification. Privacy-preserving duplicate
            detection via HMAC-SHA256 hashing. Per-proposal gates on
            verification level, jurisdiction, and minimum age. Org-scoped
            duplicate flags with admin adjudication.
          </p>
          <p>
            <strong>Deliberation.</strong> Pol.is integration as a first-class
            deliberation artifact, structurally linked to proposals. Threaded
            comments on proposals. Proposal revisions with full edit history
            visible to all members. Configurable engagement settings: write-in
            options, advisory pre-voting during deliberation, live tally
            visibility, and edit lockout windows.
          </p>
          <p>
            <strong>Operations.</strong> Configurable role-permission matrix
            with 29+ permission keys across 9 categories, editable per org.
            Notification system with in-app feed, per-event email delivery,
            daily and weekly digests, quiet hours, and signal-level presets.
            Comprehensive audit log with ballot-content redaction and elevated
            access controls. Proposal import from JSON files. A help system
            with role-specific onboarding guides. Three demo organizations with
            daily content reset for evaluation. Rate limiting, input
            sanitization, and a full security review with fixes shipped.
          </p>
        </Section>

        <Section title="What's next">
          <p>
            Whatever you need. The platform is built to be shaped by the
            organizations that use it. If there's a feature that would make
            liquid democracy work for your group, tell us — either in the
            Platform Feedback organization on the site or by emailing{' '}
            <a
              href="mailto:z@liquiddemocracy.us"
              className="text-[var(--brand-accent)] hover:text-[var(--brand-primary)] underline"
            >
              z@liquiddemocracy.us
            </a>.
          </p>
        </Section>

        <Section title="Get involved">
          <p>
            If this is interesting to you, reach out. I'd love to hear
            feedback about what we've built so far. Doubly so if you're
            interested in collaborating or are part of an organization that
            would be interested in learning more and potentially piloting
            a liquid democracy voting project.
          </p>
          <p className="flex flex-wrap items-center gap-3 pt-2">
            <a
              href="mailto:z@liquiddemocracy.us"
              className="inline-flex items-center px-5 py-2.5 bg-white text-[var(--brand-primary)] text-sm font-medium rounded-lg border border-gray-300 hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)] transition-colors"
            >
              z@liquiddemocracy.us
            </a>
            <a
              href="https://github.com/Zachrelius/liquid-democracy"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center px-5 py-2.5 bg-[var(--brand-primary)] text-white text-sm font-medium rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
            >
              View on GitHub
            </a>
            <Link
              to="/demo"
              className="inline-flex items-center px-5 py-2.5 bg-white text-[var(--brand-primary)] text-sm font-medium rounded-lg border border-gray-300 hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)] transition-colors"
            >
              Try the demo
            </Link>
            <Link
              to="/explore"
              className="inline-flex items-center px-5 py-2.5 bg-white text-[var(--brand-primary)] text-sm font-medium rounded-lg border border-gray-300 hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)] transition-colors"
            >
              Browse organizations
            </Link>
            <Link
              to="/security"
              className="inline-flex items-center px-5 py-2.5 bg-white text-[var(--brand-primary)] text-sm font-medium rounded-lg border border-gray-300 hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)] transition-colors"
            >
              Security & Trust
            </Link>
            <Link
              to="/why"
              className="inline-flex items-center px-5 py-2.5 bg-white text-[var(--brand-primary)] text-sm font-medium rounded-lg border border-gray-300 hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)] transition-colors"
            >
              The longer answer
            </Link>
          </p>
        </Section>
      </article>
    </PublicLayout>
  );
}

function Section({ title, children }) {
  return (
    <section className="mt-12">
      <h2 className="text-2xl font-semibold text-[var(--brand-primary)] mb-4 tracking-tight">
        {title}
      </h2>
      <div className="space-y-4 text-base leading-relaxed text-[#2C3E50]">
        {children}
      </div>
    </section>
  );
}