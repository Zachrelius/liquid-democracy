import { useEffect, useState, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import api from '../api';
import { useToast } from '../components/Toast';
import BrandingThemeApplier from '../components/BrandingThemeApplier';
import PublicLayout from '../components/PublicLayout';
import Nav from '../components/Nav';
import EmailVerificationBanner from '../components/EmailVerificationBanner';
import renderMarkdown from '../utils/renderMarkdown';
import { urlFor } from '../utils/urls';

/**
 * Phase 14 F2 — public org landing page (the splash at bare /{slug}).
 *
 * Renders the §F2 12-state matrix across:
 *   policy ∈ {invite_only_secret, invite_only_public, approval_required, open}
 *   visitor ∈ {logged-out, logged-in non-member (no pending), logged-in
 *              non-member (pending — approval_required only), member}
 *
 * The component is the single entry point for all 12 states; the join CTA
 * is the only piece of UI that varies materially. Header (logo + name +
 * description), intro markdown section, and brand theming render
 * identically across the four public policies. invite_only_secret renders
 * a generic not-found surface — the public endpoint returns 404 for that
 * policy so we can't distinguish "secret org" from "no such slug" here,
 * which is the deliberate security posture.
 *
 * The component is NOT wrapped in OrgScopedLayout (which auth-gates and
 * member-gates). It IS wrapped in OrgProvider at the route level so we
 * can read userOrgs to determine membership + pending state without an
 * extra round-trip — `userOrgs` is the same data the rest of the app
 * uses, just pivoted by slug.
 *
 * Brand-color theming reuses Phase 12.7's BrandingThemeApplier (extracted
 * from App.jsx into a standalone prop-shaped component) so the splash
 * picks up org branding via CSS variables on document.documentElement.
 */

// Helper: build a `?next=` query string for the auth CTAs so post-login
// the visitor returns to this splash (where they can complete the join
// they came for). Login page reads this via useLocation.search.
function authHref(base, slug) {
  return `${base}?next=${encodeURIComponent('/' + slug)}`;
}

export default function OrgPublicLanding() {
  const { org_slug: slug } = useParams();
  const { user, loading: authLoading } = useAuth();
  const { userOrgs, loading: orgsLoading, refreshOrgs } = useOrg();
  const navigate = useNavigate();
  const toast = useToast();

  const [orgData, setOrgData] = useState(null);
  const [fetchStatus, setFetchStatus] = useState('loading'); // 'loading' | 'ok' | 'not_found' | 'error'
  const [actionInFlight, setActionInFlight] = useState(false);

  // Fetch the public-endpoint payload. 404 covers both "no such org" and
  // "invite_only_secret" per the security posture (B2 spec).
  const fetchPublic = useCallback(async () => {
    setFetchStatus('loading');
    try {
      const data = await api.get(`/api/orgs/${slug}/public`);
      setOrgData(data);
      setFetchStatus('ok');
    } catch (err) {
      if (err?.status === 404) {
        setFetchStatus('not_found');
      } else {
        setFetchStatus('error');
      }
      setOrgData(null);
    }
  }, [slug]);

  useEffect(() => { fetchPublic(); }, [fetchPublic]);

  // Determine the visitor's relationship to this org. We deliberately don't
  // ask the public endpoint for this — it's user-state-free per spec — and
  // instead pivot userOrgs (already loaded by OrgProvider for logged-in
  // users; empty for logged-out). The membership object includes a status
  // field; "pending" means approval_required + waiting; "active" means
  // member. Sub-orgs are filtered out (parent_org_id is non-null on those).
  const membership = (() => {
    if (!user) return null;
    return userOrgs.find(o => o.slug === slug && !o.parent_org_id) || null;
  })();
  // For most fields backend returns user_role + status on the org object
  // (the same payload OrgSelector consumes). A pending request is one with
  // status==='pending'; an active membership is everything else (the
  // existing /api/orgs filter only returns active rows today, so we treat
  // any matched row without a 'pending' status as active).
  const isMember = !!membership && membership.status !== 'pending';
  const isPendingRequest = !!membership && membership.status === 'pending';

  // -------------------- Render: loading + error gates --------------------
  // While auth + public fetch resolve, show a small loading placeholder.
  // Don't show the splash until orgData is loaded; otherwise we'd flash
  // the wrong CTA.
  if (authLoading || fetchStatus === 'loading') {
    return (
      <PublicLayout>
        <div className="flex items-center justify-center py-32">
          <div className="text-gray-500 text-sm">Loading…</div>
        </div>
      </PublicLayout>
    );
  }

  if (fetchStatus === 'not_found') {
    // Per spec security posture: indistinguishable from "no such org".
    return (
      <PublicLayout>
        <div className="max-w-xl mx-auto px-4 py-24 text-center space-y-3">
          <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">
            Organization not found
          </h1>
          <p className="text-sm text-gray-600">
            We couldn&apos;t find an organization at this URL. Check the link
            for typos, or ask the person who shared it to resend.
          </p>
          <div className="pt-3">
            <Link
              to="/"
              className="inline-block px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
            >
              Back to Liquid Democracy
            </Link>
          </div>
        </div>
      </PublicLayout>
    );
  }

  if (fetchStatus === 'error' || !orgData) {
    return (
      <PublicLayout>
        <div className="max-w-xl mx-auto px-4 py-24 text-center space-y-3">
          <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">
            Something went wrong
          </h1>
          <p className="text-sm text-gray-600">
            We couldn&apos;t load this organization just now. Please refresh
            the page or try again in a moment.
          </p>
        </div>
      </PublicLayout>
    );
  }

  // -------------------- Action handlers --------------------

  async function handleJoinAction() {
    setActionInFlight(true);
    try {
      // Backend dispatches by policy: open → active row, approval_required
      // → pending row + notification fire. invite_only_public returns 403,
      // which we shouldn't hit because we don't render the button in that
      // policy, but we surface the error gracefully if it does.
      const res = await api.post(`/api/orgs/${slug}/join-request`, {});
      if (res?.status === 'active') {
        toast.success('You’re now a member.');
      } else {
        toast.success('Request submitted. You’ll get an email when an admin reviews it.');
      }
      // Refresh both the public payload (in case the steward edited mid-flow)
      // and the user's org list (so member/pending state updates).
      await Promise.all([fetchPublic(), refreshOrgs()]);
    } catch (err) {
      toast.error(err?.message || 'Couldn’t complete that action.');
    } finally {
      setActionInFlight(false);
    }
  }

  async function handleCancelRequest() {
    setActionInFlight(true);
    try {
      await api.delete(`/api/orgs/${slug}/join-request`);
      toast.success('Request cancelled.');
      await Promise.all([fetchPublic(), refreshOrgs()]);
    } catch (err) {
      toast.error(err?.message || 'Couldn’t cancel the request.');
    } finally {
      setActionInFlight(false);
    }
  }

  // -------------------- Splash UI --------------------

  const policy = orgData.join_policy;
  const branding = orgData.branding || {};
  const logoUrl = orgData.logo_url || branding.logo_url || null;
  const intro = orgData.intro_text || '';

  // The splash chrome differs based on whether the visitor is a logged-in
  // member: members get the full Nav (so they can navigate onward to
  // /{slug}/proposals, /{slug}/admin/settings, etc.). Logged-out and
  // logged-in non-members get the minimal PublicLayout chrome — they have
  // no member nav to render.
  //
  // For logged-in members, OrgProvider has been mounted at the route level
  // so currentOrg resolves correctly and Nav can render the org switcher,
  // admin dropdown, etc. For non-members, useOrg().currentOrg is null
  // (the slug isn't in their userOrgs) and Nav hides the per-org links by
  // design — but we still don't want to show the auth Nav to logged-out
  // visitors, so we branch on user presence.
  const memberChrome = user && isMember;

  const splashContent = (
    <>
      {/* Apply org branding to document.documentElement for the lifetime of
          this page. Cleanup runs on unmount so navigating away to a
          non-org-scoped page restores platform defaults. */}
      <BrandingThemeApplier branding={branding} />

      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-12 sm:py-16">
        {/* Header: logo + name */}
        <div className="text-center mb-8">
          {logoUrl && (
            <img
              src={logoUrl}
              alt={`${orgData.name} logo`}
              className="h-16 sm:h-20 w-auto max-w-[260px] object-contain mx-auto mb-4"
            />
          )}
          <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight text-[var(--brand-primary)]">
            {orgData.name}
          </h1>
          {orgData.description && (
            <p className="mt-3 text-base text-[#2C3E50] max-w-xl mx-auto">
              {orgData.description}
            </p>
          )}
        </div>

        {/* Optional markdown intro section. Hidden entirely if empty. */}
        {intro && (
          <div className="bg-white border border-gray-200 rounded-xl p-6 sm:p-8 mb-8">
            <div
              className="prose text-[#2C3E50] text-sm leading-relaxed"
              // The same renderer + sanitization story as proposal bodies
              // (see utils/renderMarkdown.js): minimal escape-then-substitute,
              // no raw HTML passthrough. The wrapping <p> matches what
              // ProposalDetail does for its body.
              dangerouslySetInnerHTML={{ __html: `<p>${renderMarkdown(intro)}</p>` }}
            />
          </div>
        )}

        {/* Join CTA — varies by policy + visitor state. */}
        <div className="bg-white border border-gray-200 rounded-xl p-6 text-center">
          <JoinCta
            policy={policy}
            slug={slug}
            user={user}
            orgsLoading={orgsLoading}
            isMember={isMember}
            isPendingRequest={isPendingRequest}
            actionInFlight={actionInFlight}
            onJoin={handleJoinAction}
            onCancelRequest={handleCancelRequest}
            onGoToProposals={() => navigate(urlFor(slug, 'proposals'))}
          />
        </div>
      </div>
    </>
  );

  if (memberChrome) {
    return (
      <div className="min-h-screen bg-[#F8F9FA] flex flex-col">
        <Nav />
        <EmailVerificationBanner />
        <main className="flex-1">{splashContent}</main>
      </div>
    );
  }
  return <PublicLayout>{splashContent}</PublicLayout>;
}

/**
 * The §F2 state matrix's join-CTA cell. Splitting this out keeps the parent
 * component focused on chrome/branding and lets the matrix logic live in
 * one place. Each branch maps directly to a row in the spec table.
 */
function JoinCta({
  policy, slug, user, orgsLoading,
  isMember, isPendingRequest, actionInFlight,
  onJoin, onCancelRequest, onGoToProposals,
}) {
  // While orgs are still loading for a logged-in user we don't yet know if
  // they're a member; show a small placeholder rather than flashing a
  // wrong CTA.
  if (user && orgsLoading) {
    return <p className="text-sm text-gray-400">Checking your membership…</p>;
  }

  // Member view (any policy): "✓ You're a member" + go-to-proposals link.
  if (user && isMember) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-green-700 font-medium">
          <span aria-hidden="true">✓ </span>You&apos;re a member
        </p>
        <button
          type="button"
          onClick={onGoToProposals}
          className="inline-block px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
        >
          Go to proposals
        </button>
      </div>
    );
  }

  // ---------------------------------------------------------------------
  // Non-member views by policy.
  // ---------------------------------------------------------------------

  if (policy === 'invite_only_public') {
    return (
      <div className="space-y-3">
        <p className="text-sm text-gray-700">
          This organization is invite-only. If you&apos;ve been invited,
          check your email for the invitation link.
        </p>
        {!user && (
          <p className="text-xs text-gray-500">
            Already have an account?{' '}
            <Link
              to={authHref('/login', slug)}
              className="text-[var(--brand-accent)] hover:underline"
            >
              Sign in
            </Link>
            {' or '}
            <Link
              to={authHref('/register', slug)}
              className="text-[var(--brand-accent)] hover:underline"
            >
              Register
            </Link>
            .
          </p>
        )}
      </div>
    );
  }

  if (policy === 'approval_required') {
    if (!user) {
      return (
        <div className="space-y-3">
          <p className="text-sm text-gray-700">
            Sign in or register to request access.
          </p>
          <div className="flex items-center justify-center gap-3">
            <Link
              to={authHref('/login', slug)}
              className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
            >
              Sign in
            </Link>
            <Link
              to={authHref('/register', slug)}
              className="px-5 py-2 border border-gray-300 text-gray-700 text-sm rounded-lg hover:bg-gray-50 transition-colors"
            >
              Register
            </Link>
          </div>
        </div>
      );
    }
    if (isPendingRequest) {
      return (
        <div className="space-y-3">
          <p className="text-sm text-gray-700 font-medium">
            Request pending review
          </p>
          <p className="text-xs text-gray-500">
            An admin will review your request and you&apos;ll be notified by
            email.
          </p>
          <button
            type="button"
            onClick={onCancelRequest}
            disabled={actionInFlight}
            className="text-xs text-gray-500 hover:text-red-600 hover:underline disabled:opacity-50"
          >
            Cancel request
          </button>
        </div>
      );
    }
    return (
      <button
        type="button"
        onClick={onJoin}
        disabled={actionInFlight}
        className="px-6 py-2.5 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
      >
        {actionInFlight ? 'Submitting…' : 'Request to join'}
      </button>
    );
  }

  if (policy === 'open') {
    if (!user) {
      return (
        <div className="space-y-3">
          <p className="text-sm text-gray-700">
            Sign in or register to join.
          </p>
          <div className="flex items-center justify-center gap-3">
            <Link
              to={authHref('/login', slug)}
              className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
            >
              Sign in
            </Link>
            <Link
              to={authHref('/register', slug)}
              className="px-5 py-2 border border-gray-300 text-gray-700 text-sm rounded-lg hover:bg-gray-50 transition-colors"
            >
              Register
            </Link>
          </div>
        </div>
      );
    }
    return (
      <button
        type="button"
        onClick={onJoin}
        disabled={actionInFlight}
        className="px-6 py-2.5 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
      >
        {actionInFlight ? 'Joining…' : 'Join'}
      </button>
    );
  }

  // Defensive: unknown policy. The public endpoint shouldn't return
  // invite_only_secret (that's a 404), and the four-value enum is the
  // contract from B5. If a stale frontend bundle hits a future policy
  // value, render nothing visible rather than a broken control.
  return null;
}
