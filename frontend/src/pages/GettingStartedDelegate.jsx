import { Link } from 'react-router-dom';
import HelpBackLink from '../components/HelpBackLink';
import HelpScreenshot from '../components/HelpScreenshot';

/**
 * Phase 43 Cluster C — Getting started as a public delegate.
 * Copy wired verbatim from phase43_help_content.md.
 * Screenshots wired in Phase 43a.
 */
export default function GettingStartedDelegate() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">
          Getting started as a delegate
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          People can hand you their vote on the topics you know best — here's how to represent them well.
        </p>
      </div>

      <Section title="What it means to be a delegate">
        <p>
          A delegate is a member who other members trust to vote on their behalf, topic by topic. If you're knowledgeable or engaged on, say, Budget or infrastructure questions, neighbors or colleagues can delegate those topics to you — your vote then counts for them until they change their mind. It's a real responsibility, and the platform is built so that it's earned through transparency, not just assigned.
        </p>
        <p>
          You manage all of this from <strong>My Delegate Page</strong> (in the menu under your name, top right).
        </p>
        <HelpScreenshot
          src="/help-screenshots/delegate-my-delegate-page.png"
          caption="The 'My Delegate Page' editing view for a delegate, showing the intro/profile area and the per-topic sections."
        />
      </Section>

      <Section title="Step 1: Write your introduction">
        <p>
          On your delegate page, start with a short introduction — who you are and how you approach decisions in this organization. This is the first thing a prospective delegator reads, so be honest and specific. "Cedar Court resident, structural engineer, I read every proposal carefully" tells people far more than "experienced and trustworthy."
        </p>
      </Section>

      <Section title="Step 2: Choose your topics and set their visibility">
        <p>
          You decide which topics you represent, and how visible each one is. Each topic has four visibility settings:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>Private (only me)</strong> — only you can see your activity on this topic. Use this while you're preparing.</li>
          <li><strong>Visible to my approved followers in this org</strong> — a middle step: people who already follow you can see it, but it isn't public yet.</li>
          <li><strong>Public — transparent only</strong> — your voting record on this topic is visible to everyone, but you're not accepting new delegations. Transparency without obligation.</li>
          <li><strong>Public — accepting delegation</strong> — your record is visible <em>and</em> you're open to representing others on this topic.</li>
        </ul>
        <p>
          You can be accepting delegation on Budget while keeping another topic private. Moving a topic to <strong>Public — accepting delegation</strong> uses the <strong>Submit for approval</strong> button and goes through your organization's approval gate, if one is configured (administrators review delegate applications).
        </p>
      </Section>

      <Section title="Step 3: Add a position statement">
        <p>
          For each topic you represent, you can write a position statement — a short summary of where you stand and how you'll weigh decisions. This helps people decide whether to delegate to you, and it holds you accountable to what you said. Treat it like a small platform you're running on.
        </p>
      </Section>

      <Section title="Step 4: Explain your votes">
        <p>
          This is what makes delegation trustworthy. For your votes on public topics, you can attach a <strong>rationale</strong> — a brief note on why you voted the way you did. Your delegators (and anyone viewing your page) can see it. You don't have to explain every vote, but the more you do, the more your record reads as "here's someone who thinks carefully," which is exactly what earns delegations.
        </p>
      </Section>

      <Section title="Step 5: Represent well, and keep it current">
        <p>
          Once you're public and accepting, members can delegate their topics to you from your profile, and you'll start voting on their behalf. A few habits that matter:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>Vote consistently</strong> with the positions you published.</li>
          <li><strong>Keep explaining</strong> the consequential votes.</li>
          <li><strong>Remember they can leave.</strong> Delegators can change or revoke at any time, and they can always override you by voting directly. Your influence lasts exactly as long as their trust does.</li>
        </ul>
      </Section>

      <Section title="Where to go next">
        <ul className="list-disc pl-5 space-y-1">
          <li><Link to="/help/public-delegates" className="text-[var(--brand-accent)] hover:underline">Public delegates</Link> — the full picture of how public delegate pages, visibility, and approval work.</li>
          <li><Link to="/help/getting-started-member" className="text-[var(--brand-accent)] hover:underline">Getting started as a member</Link> — the basics, if you also want a refresher on voting and delegating.</li>
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

