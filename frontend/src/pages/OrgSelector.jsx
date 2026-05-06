import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrg } from '../OrgContext';
import { urlFor } from '../utils/urls';

export default function OrgSelector() {
  const { userOrgs, setCurrentOrg, loading } = useOrg();
  const navigate = useNavigate();

  // Phase 11 — UX nicety: a user with exactly one org and a matching
  // localStorage `currentOrgSlug` hint auto-lands in their app rather than
  // staring at a one-button "pick" page. Single-org users without a hint
  // also auto-land — there's no meaningful pick to make. Multi-org users
  // see the picker.
  useEffect(() => {
    if (loading) return;
    if (userOrgs.length !== 1) return;
    const only = userOrgs[0];
    let hint = null;
    try { hint = localStorage.getItem('currentOrgSlug'); } catch { /* ignore */ }
    if (hint && hint !== only.slug) {
      // localStorage points at a different (now-stale) slug — still auto-land
      // since the user only has one org, but write the up-to-date slug.
    }
    setCurrentOrg(only);
    navigate(urlFor(only, 'proposals'), { replace: true });
  }, [loading, userOrgs, navigate, setCurrentOrg]);

  function selectOrg(org) {
    setCurrentOrg(org);
    navigate(urlFor(org, 'proposals'));
  }

  // Phase 9.5 — empty-state CTA when the user is in zero orgs.
  if (userOrgs.length === 0) {
    return (
      <div className="max-w-xl mx-auto px-4 py-20">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-[var(--brand-primary)] mb-3">
            You're not in any organizations yet
          </h1>
          {/* Phase 14 F4 — empty-state copy expanded to acknowledge that
              public organizations (open or approval_required policies) are
              now joinable via direct URL. The previous copy implied
              invitation was the only path; that was misleading once the
              public landing page surface shipped. No new UI affordance is
              added — the platform doesn't yet have a "browse public orgs"
              page (deliberately deferred per spec) — but at least the copy
              no longer steers users away from a real path. */}
          <p className="text-sm text-gray-500 mb-8">
            Create your own organization, follow a public organization&apos;s
            link, or wait for an invitation.
          </p>
          <button
            onClick={() => navigate('/orgs/create')}
            className="inline-block px-6 py-2.5 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
          >
            Create Organization
          </button>
          <p className="text-xs text-gray-400 mt-6">
            Have an invitation? Click the link in the email.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-12">
      <h1 className="text-2xl font-semibold text-[var(--brand-primary)] mb-2">Your Organizations</h1>
      <p className="text-sm text-gray-500 mb-8">Select an organization to continue, or create a new one.</p>

      <div className="grid gap-4 sm:grid-cols-2">
        {userOrgs.map(org => {
          // Phase 12.7 F6 — per-card branding using inline styles, NOT
          // document-level CSS vars. The picker shows multiple orgs at
          // once; choosing one org's branding to apply globally would be
          // wrong. So each card pulls its own org.branding directly.
          // Orgs with no branding configured fall through to platform
          // defaults (no left border accent, default header color).
          const branding = org.branding || {};
          const cardPrimary = branding.primary_color || null;
          const logoUrl = branding.logo_url || null;
          // 4px left-accent border in the org's primary color when set;
          // standard 1px gray border otherwise. Inline style is the only
          // option here since per-card colors can't be expressed via
          // Tailwind classes.
          const cardStyle = cardPrimary
            ? { borderLeft: `4px solid ${cardPrimary}` }
            : {};
          return (
            <button
              key={org.id}
              onClick={() => selectOrg(org)}
              style={cardStyle}
              className="text-left bg-white border border-gray-200 rounded-xl p-5 hover:border-[var(--brand-accent)] hover:shadow-sm transition-all"
            >
              {logoUrl && (
                <img
                  src={logoUrl}
                  alt={`${org.name} logo`}
                  className="h-8 w-auto max-w-[140px] object-contain mb-3"
                />
              )}
              <h3
                className={`text-lg font-semibold mb-1 ${cardPrimary ? '' : 'text-[var(--brand-primary)]'}`}
                style={cardPrimary ? { color: cardPrimary } : undefined}
              >
                {org.name}
              </h3>
              {org.description && (
                <p className="text-sm text-gray-500 mb-3 line-clamp-2">{org.description}</p>
              )}
              <div className="flex items-center gap-4 text-xs text-gray-400">
                {org.member_count != null && <span>{org.member_count} members</span>}
                {org.user_role && (
                  <span className={`px-2 py-0.5 rounded font-medium ${
                    (org.user_role === 'steward' || org.user_role === 'owner') ? 'bg-purple-50 text-purple-700' :
                    org.user_role === 'admin' ? 'bg-blue-50 text-blue-700' :
                    'bg-gray-50 text-gray-600'
                  }`}>
                    {org.user_role === 'owner' ? 'steward' : org.user_role}
                  </span>
                )}
              </div>
            </button>
          );
        })}

        {/* Create New */}
        <button
          onClick={() => navigate('/orgs/create')}
          className="flex items-center justify-center bg-white border-2 border-dashed border-gray-300 rounded-xl p-5 hover:border-[var(--brand-accent)] hover:bg-blue-50/30 transition-all min-h-[120px]"
        >
          <div className="text-center">
            <div className="text-3xl text-gray-300 mb-2">+</div>
            <p className="text-sm font-medium text-gray-500">Create New Organization</p>
          </div>
        </button>
      </div>
    </div>
  );
}
