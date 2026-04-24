// TODO(Z): review and edit — draft copy, calibrate voice before shipping
import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';

export default function About() {
  return (
    <PublicLayout>
      <article className="max-w-3xl mx-auto px-6 py-16 sm:py-20 text-[#2C3E50]">
        <header className="mb-12">
          <p className="text-sm font-medium text-[#2E75B6] uppercase tracking-wider">
            About the project
          </p>
          <h1 className="mt-2 text-4xl sm:text-5xl font-semibold text-[#1B3A5C] tracking-tight">
            Democracy, unbundled.
          </h1>
          <p className="mt-5 text-lg text-[#2C3E50] leading-relaxed">
            Most of us have the ability to vote once every few years on a
            package of positions we didn't choose, represented by a person
            we mostly don't know, on questions we mostly can't see coming.
            We think there's a better way, and we're building a piece of
            software to try it.
          </p>
        </header>

        <Section title="The problem with how we vote now">
          <p>
            Modern representative democracy was designed for a world where
            information travelled on horseback. Its core compromises made
            sense then: voters couldn't weigh in on every issue, so they
            chose a person to weigh in for them. They couldn't update that
            choice often, so they bundled four or six years of decisions
            into a single ballot.
          </p>
          <p>
            Those compromises haven't aged well. Voting is low-frequency:
            the gap between the moment a decision matters and the next
            time you get to express an opinion is measured in years.
            Representation is coarse: a single person somehow stands in
            for you on healthcare, foreign policy, zoning, education,
            and tax policy, even though their expertise and your
            priorities only overlap on a slice of that. And the gap
            between principal and agent keeps widening: the people voting
            on a given issue in a legislature are rarely the people who
            know it best, and there's no channel for someone who does to
            influence the outcome unless they already hold office.
          </p>
          <p>
            None of this is new. Liquid democracy has been discussed for
            decades as a way to fix it. What's been missing is usable
            software.
          </p>
        </Section>

        <Section title="What liquid democracy is">
          <p>
            In a liquid democracy, decisions are made proposal by proposal,
            not candidate by candidate. On every proposal, you can do one
            of two things: vote directly, or delegate your vote to someone
            you trust on that topic. A friend who's a nurse gets your
            healthcare vote. A colleague who's spent their career in
            climate policy gets your climate vote. A neighbor who thinks
            carefully about budgets gets your fiscal vote. You retain
            everything else.
          </p>
          <p>
            Delegations are per-topic, not wholesale. They are revocable
            at any time, for any reason, without explanation — the moment
            you disagree with how your delegate is voting, you can take
            your vote back, either for one proposal or permanently.
            Delegations are transitive: if the person you delegate to
            also delegates, your vote follows that chain (with cycle
            prevention, so it can't loop). And delegates' voting records
            are fully public on the topics they accept delegation for,
            so the people who trust them can see exactly what they've
            been doing with that trust.
          </p>
          <p>
            The result is a system that preserves what representation is
            good at — letting expertise influence decisions — while
            fixing what it's bad at: low granularity, slow correction,
            and weak accountability.
          </p>
        </Section>

        <Section title="Why we're building this">
          <p>
            The idea is old. The implementations are scarce. A few
            academic prototypes, a few abandoned projects, a handful of
            organizations that built something internal and never
            released it. What's missing is a production-quality,
            open-source platform that small organizations — clubs,
            co-ops, non-profits, online communities, student governments —
            can adopt without needing to hire engineers.
          </p>
          <p>
            That's what this is. It's a pilot-stage, open-source
            implementation of liquid democracy, designed to be usable
            today by organizations that want to try governing
            themselves this way. The goal is to start with small groups,
            learn what works at that scale, and grow from there. It is
            deliberately not a replacement for national elections. It's
            a tool for the many smaller decisions people make together,
            which in aggregate matter more than any one election cycle.
          </p>
          <p>
            The platform is built by a small team and is funded by time,
            not grants or equity. We'd rather ship something small and
            real than promise something large and theoretical.
          </p>
        </Section>

        <Section title="What's built, and what's next">
          <p>
            Today, the platform supports:
          </p>
          <ul className="list-disc pl-6 space-y-2">
            <li>
              Binary voting (yes/no/abstain) and approval voting
              (pick any subset of options), with method-aware tallying.
            </li>
            <li>
              Topic-based delegation with transitive resolution and
              cycle prevention, plus an interactive graph view of how
              delegations flow.
            </li>
            <li>
              Fully transparent voting and delegation history for public
              delegates, so accountability is not a promise but a
              receipt.
            </li>
            <li>
              Organization-scoped multi-tenancy: the same platform can
              host many independent groups, each with their own
              members, topics, and proposals.
            </li>
            <li>
              The usual operational necessities — email verification,
              password reset, audit logs, role-based permissions,
              admin analytics.
            </li>
          </ul>
          <p>
            Coming next, in roughly this order: ranked-choice and single
            transferable vote for elections where ranking matters,
            sustained-majority support for decisions that shouldn't be
            decided by a one-day spike, better visualizations of
            delegation networks and vote flow, and richer deliberation
            tooling around proposals themselves.
          </p>
          <p>
            The roadmap is public and the code is open. Progress is
            steady rather than fast, and that's intentional — the cost
            of shipping bad governance software is higher than the cost
            of shipping it slowly.
          </p>
        </Section>

        <Section title="Get involved">
          <p>
            If this is interesting to you, the code lives on GitHub and
            we welcome contributions, issues, and feedback. If you're
            part of an organization that might want to pilot liquid
            democracy internally, or if you just want to argue with us
            about the design, reach out.
          </p>
          <p className="flex flex-wrap items-center gap-3 pt-2">
            <a
              href="https://github.com/Zachrelius/liquid-democracy"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center px-5 py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors"
            >
              View on GitHub
            </a>
            <Link
              to="/demo"
              className="inline-flex items-center px-5 py-2.5 bg-white text-[#1B3A5C] text-sm font-medium rounded-lg border border-gray-300 hover:border-[#2E75B6] hover:text-[#2E75B6] transition-colors"
            >
              Try the demo
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
      <h2 className="text-2xl font-semibold text-[#1B3A5C] mb-4 tracking-tight">
        {title}
      </h2>
      <div className="space-y-4 text-base leading-relaxed text-[#2C3E50]">
        {children}
      </div>
    </section>
  );
}
