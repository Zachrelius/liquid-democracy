import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';

export default function Security() {
  return (
    <PublicLayout>
      <article className="max-w-3xl mx-auto px-6 py-16 sm:py-20 text-[#2C3E50]">
        <header className="mb-12">
          <p className="text-sm font-medium text-[#2E75B6] uppercase tracking-wider">
            Security & Trust
          </p>
          <h1 className="mt-2 text-4xl sm:text-5xl font-semibold text-[#1B3A5C] tracking-tight">
            The tradeoff we made, and why
          </h1>
          <div className="mt-5 space-y-4 text-lg text-[#2C3E50] leading-relaxed">
            <p>
              Liquid democracy requires a choice that traditional voting
              doesn't. In a conventional election, the system verifies your
              identity at the door and then severs the link — your ballot
              goes into a pile, and nobody can reconnect it to you. That's
              the secret ballot, and it's a genuinely important protection.
              It prevents your employer from watching how you vote, your
              party from punishing dissent, and anyone from buying your
              vote and verifying you delivered.
            </p>
            <p>
              Our system can't offer that guarantee in the same way, and we
              want to be upfront about why.
            </p>
            <p>
              For delegation to work — for the system to know that you've
              entrusted your healthcare votes to one person and your
              economic votes to another, and to let you revoke that trust
              at any time — it has to maintain a persistent link between
              you and your choices. It can't sever the connection the way
              a ballot box does, because the whole point is that the
              connection is live, continuous, and yours to change.
            </p>
            <p>
              This is not a technical limitation we're working around. It's
              a structural feature of what liquid democracy is. Any system
              that offers revocable, topic-specific delegation has this
              property. If someone tells you they've built a liquid
              democracy platform with a fully secret ballot, they're either
              confused about what they've built or not being honest with
              you.
            </p>
          </div>
        </header>

        <Section title="What we do instead">
          <p>
            We can't offer technical ballot secrecy — the guarantee that
            nobody can see your vote. What we offer instead is institutional
            privacy — a set of layered protections that control who does
            see your vote.
          </p>
          <p>
            <strong>Your votes are private from other users by default.</strong>{' '}
            No member of your organization can see how you voted unless
            you've granted them access — by approving them as a follower,
            or by registering yourself as a public delegate on specific
            topics (in which case your votes on those topics are public by
            choice — that's the accountability mechanism that makes public
            delegation trustworthy).
          </p>
          <p>
            <strong>Access between users requires consent.</strong> Other
            organization members cannot see your voting record without your
            explicit approval. They cannot see who you've delegated to
            without that approval either. The follow/permission system is
            the only path to user-to-user visibility, and it's gated on
            both sides.
          </p>
          <p>
            <strong>The platform itself can see your data</strong> — and
            we want to be specific about what that means. Three categories
            of access exist beyond user-to-user consent:
          </p>
          <ul className="list-disc pl-6 space-y-2">
            <li>
              <strong>Organization administrators</strong> see member lists
              and aggregate analytics for their own organization
              (participation rates, delegation patterns), but they don't
              have an interface that exposes individual ballot contents
              from the standard org admin tools.
            </li>
            <li>
              <strong>Platform operators</strong> — the people running the
              underlying software — have direct database access. This is
              true of any digital system that tracks delegation
              relationships, and it's true of our system. We don't pretend
              otherwise.
            </li>
            <li>
              <strong>Platform-level administrators</strong> (a privileged
              role separate from organization administrators) have access
              to a system-wide audit log. Ballot contents are redacted
              from the default audit view; viewing them requires explicit
              elevation by a platform administrator with a reason
              captured, and that elevation is itself recorded as an audit
              event. Every user can see who has accessed their data —
              including any platform-level access events that touched
              their account — in the{' '}
              <Link
                to="/settings"
                className="text-[#2E75B6] hover:text-[#1B3A5C] underline"
              >
                Data Access History
              </Link>{' '}
              section of their account settings. We don't ask you to take
              our word for it.
            </li>
          </ul>
          <p>
            <strong>Open source as a baseline accountability mechanism.</strong>{' '}
            All of the above can be verified against the actual code,
            which is publicly available on GitHub. If we describe a
            privacy boundary that the code doesn't enforce, anyone can
            find it.
          </p>
          <p>
            <strong>Audit logging.</strong> Every state-changing action —
            votes cast, delegations created, follows approved, admin
            actions — is recorded in an append-only audit log. The
            application's API has no method to delete entries from this
            log. It's not cryptographically tamper-evident (that's a
            future improvement), but within the application's normal
            operation, the log is immutable.
          </p>
          <p>
            <strong>You control the consent boundary.</strong> If you want
            maximum privacy from other users, delegate to public delegates
            only and vote directly when you disagree. Your delegation
            choices are visible to the system but your individual votes
            look no different from any other participant's. If you want
            maximum convenience, approve followers and let trusted people
            see your record. The system doesn't force you into either
            posture.
          </p>
        </Section>

        <Section title="Why we think this is the right trade">
          <p>
            The secret ballot solves a real problem: coercion. Someone
            can't punish you for how you voted if they can't find out how
            you voted. We don't dismiss that.
          </p>
          <p>
            But the secret ballot also has a cost that rarely gets
            discussed. It makes representatives completely unaccountable
            between elections. Your senator votes against your interests
            on Tuesday, and your only recourse is to remember that in
            November — two, four, or six years later, against a challenger
            you may like even less. The secret ballot protects the moment
            of voting, but it does nothing about the years of governance
            that follow.
          </p>
          <p>
            Liquid democracy trades some protection at the moment of
            voting for continuous accountability afterward. Your
            delegate's votes are visible to you. You can revoke your
            delegation the same day. You don't have to wait years for a
            chance to respond, and you don't have to settle for one
            alternative. The feedback loop tightens from years to hours.
          </p>
          <p>
            Whether that trade is worth it depends on context. For a
            high-stakes national election where state actors might try to
            coerce millions of voters, the secret ballot is essential, and
            we'd never propose replacing it for that purpose. For an
            organization deciding how to allocate its budget, or a
            community choosing between policy proposals, the coercion risk
            is low and the accountability gain is high. That's where
            liquid democracy belongs right now, and that's what we've
            built for.
          </p>
        </Section>

        <Section title="About this demo specifically">
          <p>
            The current deployment at liquiddemocracy.us is a public demo,
            run informally by the project's founder. There is not yet a
            formal operator agreement, an independent oversight body, or a
            separation between platform operations and the founder's
            individual access. As the platform matures toward real pilot
            deployments, those institutional safeguards will be
            established and documented. Until then, the trust model for
            the demo is "the founder is operating in good faith and the
            code is open for inspection." If that's not enough for your
            use case, that's a fair conclusion — wait for the formal
            pilot deployments.
          </p>
        </Section>

        <Section title="What about online voting security?">
          <p>
            There's a separate question that sometimes gets tangled with
            the ballot secrecy issue: is it safe to vote over the internet
            at all?
          </p>
          <p>
            The honest answer, backed by broad consensus among computer
            security researchers, is that binding internet voting for
            high-stakes elections is not currently secure enough. The
            problems are fundamental, not incremental. Malware on your
            device can change your vote without you knowing. Server-side
            attacks can alter results at scale. Remote voting eliminates
            the supervised environment that prevents coercion and
            vote-buying. These aren't theoretical concerns — they're the
            reason that the National Academies, the AAAS, and leading
            researchers like Bruce Schneier, Ronald Rivest, and J. Alex
            Halderman have consistently recommended against internet
            voting for governmental elections.
          </p>
          <p>
            We take this consensus seriously. We're not going to tell you
            the experts are wrong or that we've solved what they say is
            unsolved. Here's how we handle it:
          </p>
          <p>
            <strong>For organizational decision-making</strong> — our
            current use case — the risk calculus is different. The
            security concerns about internet voting are calibrated to
            national elections, where a single attacker could alter
            millions of votes and the outcome is irreversible. An
            organization voting on its budget priorities is a different
            threat model: the stakes per decision are lower, the
            participant pool is smaller and known, manipulation is easier
            to detect socially, and the consequences are correctable. This
            doesn't mean security doesn't matter — it means the
            appropriate level of security is different.
          </p>
          <p>
            <strong>Our architecture is designed to support graduated
            security as the platform scales.</strong> Today, only the
            digital tier is implemented — appropriate for organizational
            decisions of the kind we're targeting. The architecture leaves
            room for higher-stakes decisions to use supervised voting
            kiosks, mail-in processes, or paper ballots with cryptographic
            verification. The same delegation model would work across all
            tiers; what changes is how the final vote is physically cast.
            Those higher tiers aren't built. We mention them so you know
            our thinking, not so you think they exist.
          </p>
          <p>
            <strong>We've done the security work that's appropriate for
            the current stage.</strong> The codebase has been reviewed
            against the OWASP Top 10. State-changing actions are recorded
            in the audit log described above. Authentication uses
            industry-standard practices: bcrypt password hashing,
            short-lived access tokens with rotation, email verification,
            password reset, rate limiting on auth endpoints. The code is
            open source and publicly auditable. We're not claiming this is
            battle-hardened for national elections — we're claiming it's
            responsibly built for organizational governance, which is what
            it's for right now.
          </p>
        </Section>

        <Section title="What we'd want to see before scaling up">
          <p>
            We're not pretending the current system is ready for
            city-level elections tomorrow. Before liquid democracy moves
            into governmental decision-making, several things would need
            to be true:
          </p>
          <p>
            Formal security audits by independent firms, not just
            self-review. Identity verification tied to official records,
            not just email addresses. An independent oversight body with
            ideologically diverse staffing, consensus governance, and
            legal accountability for system integrity. Formal operator
            agreements that bind anyone running the platform to specified
            behavior. And probably advances in areas like end-to-end
            verifiable voting and trusted computing that make the
            device-security problem more tractable than it is today.
          </p>
          <p>
            Some of these are technical challenges. Some are institutional
            ones. None of them are reasons not to start building and
            testing at the organizational scale where the system is
            appropriate now.
          </p>
        </Section>

        <Section title="The bottom line">
          <p>
            We're asking you to trust a system with less ballot secrecy
            than a traditional election, and we've tried to be specific
            about exactly how that's true rather than burying it in fine
            print.
          </p>
          <p>
            What you get in return is a form of representation that's more
            responsive, more granular, and more accountable than anything
            the traditional system offers. Your vote follows your values
            on every issue, not just the ones that happen to come up
            during an election year. You can change your mind instantly.
            You can see exactly how your delegate is using the trust
            you've placed in them.
          </p>
          <p>
            Whether that trade is worth it is a judgment call, and it
            might be different for different contexts and different
            people. We've made our bet. We think accountability every day
            beats secrecy once every few years, at least for the kinds of
            decisions organizations and communities are making right now.
            If you're curious whether we're right, the software is free,
            the code is open, and we'd love to hear what you think.
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
