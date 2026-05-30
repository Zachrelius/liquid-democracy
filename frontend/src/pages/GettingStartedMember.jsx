import { Link } from 'react-router-dom';
import HelpBackLink from '../components/HelpBackLink';
import HelpScreenshot from '../components/HelpScreenshot';

/**
 * Phase 43 Cluster C — Getting started as a member.
 * Copy wired verbatim from phase43_help_content.md (planning-agent authored).
 * Screenshots wired in Phase 43a; captured from Cedar Hollow demo.
 */
export default function GettingStartedMember() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">
          Getting started as a member
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          You've joined an organization — here's how to take part.
        </p>
      </div>

      <Section title="What this platform is for">
        <p>
          Your organization makes decisions here together. Anyone can weigh in on a proposal by voting directly. And for the topics you'd rather not track closely, you can hand your vote to someone you trust — a delegate — who votes on your behalf. You stay in control: you can change or take back a delegation at any time, and you can always step in and vote yourself.
        </p>
        <p>
          That's the whole idea of liquid democracy: vote directly when you want to, delegate when you don't, on a topic-by-topic basis.
        </p>
      </Section>

      <Section title="Find what's being decided">
        <p>
          Open the <strong>Proposals</strong> tab to see everything your organization is working on. Each proposal moves through stages, and you can filter by them:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>Deliberation</strong> — the discussion phase. The proposal is being shaped; you can read it and join the conversation before voting opens.</li>
          <li><strong>Voting</strong> — voting is open. Cast your vote before the deadline shown on the proposal.</li>
          <li><strong>Passed / Failed</strong> — decided. You can see the outcome and how the vote went.</li>
        </ul>
        <p>
          Each proposal shows who wrote it, the topics it touches, how many votes have been cast, and how much time is left.
        </p>
        <HelpScreenshot
          src="/help-screenshots/member-proposals-list.png"
          caption="The Proposals list in Cedar Hollow showing the All/Deliberation/Voting/Passed/Failed filter row and proposal cards with vote tallies and time remaining."
        />
      </Section>

      <Section title="Cast your vote">
        <p>
          Open any proposal that's in <strong>Voting</strong>. You'll choose <strong>Yes</strong>, <strong>No</strong>, or <strong>Abstain</strong> (some proposals use other methods, like approval or ranked-choice — the proposal will show you what's available). Your choice is recorded immediately; there's no separate submit step.
        </p>
        <p>
          Changed your mind? As long as voting is still open, you can change your vote any time — just select a different option.
        </p>
        <HelpScreenshot
          src="/help-screenshots/member-vote-cast.png"
          caption="A single proposal detail in the Voting stage showing the Yes / No / Abstain vote options."
        />
      </Section>

      <Section title="Join the discussion">
        <p>
          Proposals have a comment section. Before voting opens — and while it's open — you can post your thoughts, ask questions, and read what your neighbors or colleagues are saying. Good decisions usually start with good discussion, so this is where a lot of the real work happens.
        </p>
      </Section>

      <Section title="Delegate your vote (optional)">
        <p>
          You won't have an opinion on everything, and that's fine. Open <strong>Delegates</strong> to browse the people in your organization accepting delegations — each one shows a short bio, the topics they cover, and how many people already delegate to them. Then open <strong>My Delegations</strong>, find a topic, and select <strong>Set Delegate</strong> to choose who votes for you on it. You can pick a different delegate for each topic, and optionally a default delegate for topics you haven't assigned.
        </p>
        <p>Two things worth knowing:</p>
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>It's per topic.</strong> You might delegate "Budget" to one person and vote on everything else yourself.</li>
          <li><strong>You're always in control.</strong> Your delegate's vote applies until you change or revoke it — and if you vote directly on a specific proposal, your direct vote overrides the delegation just for that one.</li>
        </ul>
        <HelpScreenshot
          src="/help-screenshots/member-browse-delegates.png"
          caption="The Browse Delegates page showing delegate cards (bio, topic tags, delegator count, View Profile)."
        />
      </Section>

      <Section title="Stay in the loop">
        <p>
          The bell icon in the top bar shows your <strong>Notifications</strong> — new proposals, approaching deadlines, and activity that involves you. You can tune what you're notified about in your account settings.
        </p>
      </Section>

      <Section title="Where to go next">
        <ul className="list-disc pl-5 space-y-1">
          <li>Curious how the different voting methods work? See <Link to="/help/voting-methods" className="text-[var(--brand-accent)] hover:underline">Voting methods</Link>.</li>
          <li>Want to understand delegates more deeply before you delegate? See <Link to="/help/public-delegates" className="text-[var(--brand-accent)] hover:underline">Public delegates</Link>.</li>
          <li>Thinking about representing others yourself? See <Link to="/help/getting-started-delegate" className="text-[var(--brand-accent)] hover:underline">Getting started as a delegate</Link>.</li>
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

