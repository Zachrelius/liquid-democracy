import { Link } from 'react-router-dom';
import HelpBackLink from '../components/HelpBackLink';

/**
 * Phase 14 D1 — public help page for organizations: public landing
 * pages and the four join policies.
 *
 * Route: /help/organizations (public — no `ProtectedRoute` wrapping;
 * mirrors the other /help/* pages).
 *
 * Content covers:
 *   1. The four join policies and what each means for visitors.
 *   2. How to set up a public landing page (description, logo, intro).
 *   3. How approval-required join requests work end-to-end.
 *   4. That `/{slug}` is the canonical public URL stewards can share.
 *   5. Note that invite-only-secret orgs have no public surface.
 */
export default function OrganizationsHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        {/* Phase 15 G1 — back-link uses history.back() with /orgs fallback. */}
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">About Organizations</h1>
        <p className="text-sm text-gray-500 mt-1">
          The four join policies, what each means for visitors, and how to set up a public landing page.
        </p>
      </div>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Finding public organizations</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          The <Link to="/explore" className="text-[var(--brand-accent)] font-medium hover:underline">Explore</Link> page lists every public organization on the platform. An organization appears there when its join policy is set to <em>Invite only (public)</em>, <em>Approval required</em>, or <em>Open</em> — the three policies that have a public landing page. Organizations set to <em>Invite only (private)</em> stay hidden from the index (and from direct-URL probes).
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          Search the list by name or description, and sort by recent activity or member count. Click any card to land on that organization&apos;s public splash, where you can join (or request to join) depending on its policy.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          The platform&apos;s demo organizations live separately at <Link to="/demo" className="text-[var(--brand-accent)] font-medium hover:underline">/demo</Link>. Demo orgs reset daily and never appear on the Explore page — they&apos;re a sandbox, not a real community.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Every org has a slug-based URL</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Each organization has a short slug (like <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">gamenights</code> or <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">demo</code>) and a canonical URL of the form <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">https://www.liquiddemocracy.us/{`{slug}`}</code>. Whether anyone outside the org can see anything at that URL depends on the org's join policy.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">The four join policies</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          A steward (or admin with the right permission) sets the org's join policy in Org Settings. The four options span a spectrum from fully private to fully open:
        </p>
        <div className="text-sm text-gray-700 leading-relaxed space-y-3">
          <div>
            <p className="font-semibold">Invite only (private)</p>
            <p>
              The org is undiscoverable. Visiting <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">/{`{slug}`}</code> returns a not-found page — indistinguishable from a non-existent slug, so a scraper can't probe to see whether an org exists. Members join only via emailed invitations. <strong>Best for orgs that want full privacy.</strong>
            </p>
          </div>
          <div>
            <p className="font-semibold">Invite only (public)</p>
            <p>
              The org has a public landing page that explains who it is — logo, name, description, optional longer intro — but visitors cannot join without an emailed invitation. The page shows "This organization is invite-only" in place of a join button. <strong>Best for orgs that want a recognizable presence on the platform but tightly controlled membership.</strong>
            </p>
          </div>
          <div>
            <p className="font-semibold">Approval required</p>
            <p>
              Anyone visiting the public landing page can request to join. The request appears as a pending member to anyone in the org with the <em>approve member joins</em> permission (Stewards and Admins by default; configurable via the role-permissions matrix). Approve or deny via the admin members page. The requester gets a notification when their request is decided. <strong>Best for community orgs that want to vet new members but stay open to applications.</strong>
            </p>
          </div>
          <div>
            <p className="font-semibold">Open</p>
            <p>
              Anyone with the link can join immediately — no invitation, no approval. New members are added at the Member role and can immediately participate (vote, delegate, comment per the org's role-permission matrix). <strong>Best for fully-open communities and pilot orgs.</strong>
            </p>
          </div>
        </div>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Setting up your public landing page</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Three of the four policies (Invite only public, Approval required, Open) get a public landing page at <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">/{`{slug}`}</code>. Stewards control what visitors see:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li><strong>Logo + name + brand color</strong> — set via Org Settings → Branding. The splash uses your org's primary color for headings + the join button.</li>
          <li><strong>Description</strong> — the existing one-line description shown on OrgSelector cards.</li>
          <li><strong>Intro</strong> — an optional longer markdown block in Org Settings → Public landing page intro. Hidden when empty. Use it to explain the org's purpose, link to a website, or set expectations for new members. Markdown is supported (same renderer used for proposal bodies); links, headings, lists, emphasis all work.</li>
        </ul>
        <p className="text-sm text-gray-700 leading-relaxed">
          You can edit the intro even if your policy is currently "Invite only (private)" — the field is editable but the page itself isn't shown until you flip the policy to a public variant.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">How approval-required join requests work</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          End-to-end flow:
        </p>
        <ol className="text-sm text-gray-700 leading-relaxed list-decimal pl-6 space-y-1">
          <li>A logged-in non-member visits your public landing page and clicks "Request to join."</li>
          <li>They become a pending member. The page now shows "Request pending review" with an option to cancel.</li>
          <li>A notification fires to all org members with the <em>approve member joins</em> permission (subject to their notification preferences).</li>
          <li>Any of those members visits Members in the admin nav and approves or denies the request.</li>
          <li>On approval, the requester becomes an active Member. On denial, the pending row is removed.</li>
        </ol>
        <p className="text-sm text-gray-700 leading-relaxed">
          Logged-out visitors clicking "Request to join" are taken to sign-in / register first; on completion they're returned to the splash to finish the request.
        </p>
      </section>

      <section className="bg-white border border-amber-200 bg-amber-50/30 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What's not on the splash</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          A few things are deliberately not exposed on the public landing page:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li><strong>Member count or activity stats.</strong> Stewards leaning toward "Invite only (public)" may not want this exposed; v1 keeps the surface deliberately minimal.</li>
          <li><strong>Pending requests.</strong> Only members with the <em>approve member joins</em> permission see pending requests, and only via the admin members page.</li>
          <li><strong>Proposals, polises, members.</strong> All sub-paths under <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">/{`{slug}`}/...</code> still require membership; the public splash is the only public surface in v1.</li>
          <li><strong>Search engine indexing.</strong> No SEO meta tags or sitemaps in v1. Browsers default to indexing what they crawl, but the platform doesn't actively help discovery via Google.</li>
        </ul>
      </section>
    </div>
  );
}
