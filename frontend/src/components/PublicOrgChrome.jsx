import { Link } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import BrandingThemeApplier from './BrandingThemeApplier';

/**
 * Phase 80 — lightweight chrome for the public read-only org surface.
 *
 * When a non-member (incl. logged-out visitor) browses an
 * `activity_visibility='public'` org's Proposals / Delegates pages, we wrap
 * the reused page in this header instead of the member `<Nav/>` (which
 * assumes an authenticated user with `currentOrg.user_permissions`). It
 * shows the org's brand, a read-only notice, and a clear path to
 * participate (Join) or sign in.
 *
 * `org` is the public org shape from `GET /api/orgs/{slug}/public`
 * (slug, name, logo_url, branding). Branding is applied so colors/logo
 * match the member experience.
 */
export default function PublicOrgChrome({ org, children }) {
  const { user } = useAuth();
  const slug = org?.slug;
  const name = org?.name || 'Organization';
  const logoUrl = org?.logo_url || org?.branding?.logo_url || null;

  return (
    <div className="min-h-screen bg-[#F8F9FA]">
      <BrandingThemeApplier branding={org?.branding} />
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
          <Link to={slug ? `/${slug}` : '/'} className="flex items-center gap-2 min-w-0">
            {logoUrl && (
              <img src={logoUrl} alt="" className="w-8 h-8 rounded object-cover" />
            )}
            <span className="font-semibold text-[var(--brand-primary)] truncate">
              {name}
            </span>
          </Link>
          <div className="flex items-center gap-3 shrink-0">
            {!user && (
              <Link
                to="/login"
                className="text-sm text-[var(--brand-accent)] hover:underline"
              >
                Sign in
              </Link>
            )}
            {slug && (
              <Link
                to={`/${slug}`}
                className="text-sm px-4 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
              >
                Join to participate
              </Link>
            )}
          </div>
        </div>
      </header>
      {/* Read-only notice band */}
      <div className="bg-[#F0F4F8] border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 py-2 text-xs text-gray-500">
          You&apos;re viewing <span className="font-medium">{name}</span> in
          read-only mode. Join to vote, comment, and delegate.
        </div>
      </div>
      <main>{children}</main>
    </div>
  );
}
