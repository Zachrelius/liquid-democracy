import { useState, useRef, useEffect } from 'react';
import { NavLink, Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import { urlFor } from '../utils/urls';
import { ADMIN_NAV_SUBSECTION_PERMISSIONS } from '../constants/admin_nav_permissions';
import Avatar from './Avatar';
import NotificationBadge from './NotificationBadge';

/**
 * Org switcher tree (Phase 8.5).
 *
 * Renders the user's parent orgs with their sub-orgs nested below. A sub-org's
 * visibility is delegated to the backend `/api/orgs/{slug}/sub-orgs` filter
 * (parent-org admins see all; sub-org members see theirs; Decision-7 default
 * visibility applies).
 */
function OrgSwitcher() {
  const navigate = useNavigate();
  const { currentOrg, userOrgs, fetchSubOrgsFor, subOrgsByParent } = useOrg();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  // userOrgs only ever contains parent orgs (the OrgMembership-driven
  // /api/orgs endpoint). Sub-orgs come from per-parent fetches.
  const parentOrgs = userOrgs.filter(o => !o.parent_org_id);

  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Lazy-load sub-orgs for each parent the user belongs to whenever the
  // dropdown opens, so the tree shows up immediately without manual expand.
  useEffect(() => {
    if (!open) return;
    parentOrgs.forEach(o => {
      if (!subOrgsByParent[o.slug]) {
        fetchSubOrgsFor(o.slug);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, parentOrgs.length]);

  if (!currentOrg) return null;

  // Breadcrumb display: parent → sub-org if currentOrg is a sub-org.
  let labelNode;
  let parentSlug = currentOrg.slug;
  if (currentOrg.parent_org_id) {
    const parent = userOrgs.find(o => o.id === currentOrg.parent_org_id);
    parentSlug = parent?.slug || currentOrg.slug;
    labelNode = (
      <span className="flex items-center gap-1">
        {parent ? <span className="text-blue-300">{parent.name}</span> : null}
        <span className="text-blue-400">/</span>
        <span>{currentOrg.name}</span>
      </span>
    );
  } else {
    labelNode = <span>{currentOrg.name}</span>;
  }

  // Phase 11 — picking an org now navigates rather than mutating localStorage.
  // The URL is the source of truth for currentOrg, so navigation IS the switch.
  // Default landing per spec line 193: simple-and-safe → /{slug}/proposals.
  function pickOrg(org) {
    setOpen(false);
    if (org.parent_org_id) {
      // Sub-org pick. Phase 34.2 E3: land at the NON-admin sub-org
      // proposals page (was admin-sub-org-proposals — admin-gated,
      // non-admin sub-org members hit a permission-gated view).
      // Per locked decision 10: admins also land here; admin nav is
      // reachable via the sidebar from this page.
      const parent = userOrgs.find(o => o.id === org.parent_org_id);
      const pSlug = parent?.slug || parentSlug;
      navigate(urlFor(pSlug, 'sub-org-proposals', org.slug));
    } else {
      navigate(urlFor(org, 'proposals'));
    }
  }

  // Phase 12.7 F5 — when the active org has a logo configured, render it
  // to the left of the org-name label. Both visible (logo + text) per spec
  // line 74; no logo-replaces-text mode in v1. For sub-org scope, the
  // breadcrumb already includes the parent name, so we use the *parent's*
  // logo (not the sub-org's, which doesn't have its own branding in v1).
  const brandedOrgForLogo = currentOrg.parent_org_id
    ? userOrgs.find(o => o.id === currentOrg.parent_org_id) || currentOrg
    : currentOrg;
  const logoUrl = brandedOrgForLogo?.branding?.logo_url || null;

  return (
    <div ref={ref} className="hidden sm:block relative">
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-blue-200 hover:text-white transition-colors flex items-center gap-2"
      >
        {logoUrl && (
          <img
            src={logoUrl}
            alt={`${brandedOrgForLogo.name} logo`}
            // Phase 34 F2 — render at full nav height (bar is h-14 = 56px,
            // logo gets h-10 = 40px with 8px breathing room top/bottom).
            // max-w accommodates wider aspect ratios without distortion.
            className="h-10 w-auto max-w-[200px] object-contain"
          />
        )}
        {labelNode}
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-2 w-72 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-2 max-h-96 overflow-y-auto">
          {parentOrgs.length === 0 && (
            <div className="px-4 py-3 text-xs text-gray-500">No organizations.</div>
          )}
          {parentOrgs.map(parent => {
            const subs = subOrgsByParent[parent.slug] || [];
            const isCurrentParent = currentOrg.id === parent.id;
            const isParentAdmin = parent.user_role === 'admin' || parent.user_role === 'steward' || parent.user_role === 'owner';
            return (
              <div key={parent.id} className="border-b border-gray-100 last:border-0 pb-2 mb-1 last:mb-0">
                <button
                  onClick={() => pickOrg(parent)}
                  className={`w-full text-left px-4 py-1.5 text-sm hover:bg-gray-50 transition-colors flex items-center justify-between ${
                    isCurrentParent ? 'bg-blue-50 font-medium text-[var(--brand-primary)]' : 'text-gray-800'
                  }`}
                >
                  <span>{parent.name}</span>
                  {parent.user_role && (
                    <span className="text-[10px] uppercase tracking-wide text-gray-400">{parent.user_role}</span>
                  )}
                </button>
                {subs.length > 0 && (
                  <div className="pl-4">
                    {subs.map(sub => {
                      const isCurrentSub = currentOrg.id === sub.id;
                      const subAdmin = sub.user_role === 'admin' || sub.user_role === 'steward' || sub.user_role === 'owner';
                      return (
                        <div key={sub.id} className="flex items-center justify-between gap-2 pr-2">
                          <button
                            onClick={() => pickOrg(sub)}
                            className={`flex-1 text-left px-4 py-1.5 text-xs hover:bg-gray-50 transition-colors flex items-center gap-2 ${
                              isCurrentSub ? 'bg-blue-50 font-medium text-[var(--brand-primary)]' : 'text-gray-700'
                            }`}
                          >
                            <span className="text-blue-400">↳</span>
                            <span className="flex-1 truncate">{sub.name}</span>
                            {sub.settings?.private && (
                              <span title="Private — visible only to members" className="text-[10px] text-gray-400">private</span>
                            )}
                          </button>
                          {(subAdmin || isParentAdmin) && (
                            <Link
                              to={urlFor(parent, 'admin-sub-org-settings', sub.slug)}
                              onClick={() => setOpen(false)}
                              className="text-[10px] text-[var(--brand-accent)] hover:underline shrink-0"
                              title="Manage this sub-org"
                            >
                              manage
                            </Link>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
                {isParentAdmin && (
                  <Link
                    to={urlFor(parent, 'admin-sub-orgs')}
                    onClick={() => setOpen(false)}
                    className="block px-4 py-1.5 text-xs text-[var(--brand-accent)] hover:underline pl-8"
                  >
                    + manage sub-organizations
                  </Link>
                )}
              </div>
            );
          })}
          {/* Phase 9.5 — discoverable entry to org creation. Visible to all
              authenticated users, no role gating. */}
          <div className="border-t border-gray-200 mt-1 pt-1">
            <Link
              to="/orgs/create"
              onClick={() => setOpen(false)}
              className="block px-4 py-1.5 text-sm text-[var(--brand-accent)] hover:bg-gray-50 transition-colors"
            >
              + Create new organization
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Nav() {
  const { user, logout } = useAuth();
  const { currentOrg, userOrgs } = useOrg();
  const [menuOpen, setMenuOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuRef = useRef(null);
  const adminRef = useRef(null);

  // Phase 16 F5 — preserve the org-aware top nav on non-org-scoped routes
  // like /settings and /orgs. When `currentOrg` is null (URL has no org
  // slug), fall back to a "navOrg" derived from `localStorage.lastOrgSlug`
  // (written by OrgContext on every org-scoped page mount). The nav then
  // resolves Proposals / Delegations / Admin links against navOrg's slug
  // so the user has working navigation back to their last-visited org.
  // When neither currentOrg nor a valid lastOrgSlug exists (brand-new
  // user, never visited an org, or org membership lost), navOrg falls
  // back to null and the org-context section of the nav is hidden — the
  // brand link still routes to /orgs (the OrgSelector picker).
  //
  // Permissions are read from currentOrg only. The fallback path renders
  // generic nav links (Proposals / Delegations) but does NOT speculate
  // about the user's permissions on the fallback org, so admin-tab
  // visibility on /settings stays correct (hidden, since we don't know).
  // Permissioned subsections only appear when currentOrg is concrete.
  const fallbackOrg = (() => {
    if (currentOrg) return null;
    let lastSlug = null;
    try {
      lastSlug = localStorage.getItem('lastOrgSlug');
    } catch { /* SSR / private mode — no fallback */ }
    if (!lastSlug) return null;
    // Only return a real userOrgs entry — if the user has lost access
    // to that org, we don't want to render broken links. userOrgs only
    // contains parent orgs, which is correct: lastOrgSlug is always
    // a parent slug per the OrgContext write effect.
    return userOrgs.find(o => o.slug === lastSlug && !o.parent_org_id) || null;
  })();
  const navOrg = currentOrg || fallbackOrg;

  // currentOrg is a sub-org when it has a parent_org_id; the legacy admin
  // dropdown (parent-org admin pages) is hidden in that mode because those
  // pages target the parent org's slug. Sub-org admin pages have their own
  // route family.
  const isSubOrgScope = !!currentOrg?.parent_org_id;

  // Phase 12.5 F1 — permission-driven admin nav gating.
  //
  // Top-level Admin tab visibility was previously gated on `isModeratorOrAdmin`
  // (a role-tier check). It is now gated on whether the user holds ANY
  // resolved permission key on the active org. A Member granted a single
  // admin-tier permission (e.g., `proposal.create`) via the matrix sees the
  // Admin tab and the matching subsection only. A Member with no grants sees
  // no Admin tab, same as before.
  //
  // Per-subsection visibility uses ADMIN_NAV_SUBSECTION_PERMISSIONS — each
  // subsection appears iff the user has at least one of its mapped keys.
  //
  // Phase 15 G6a (2026-05-06) — the cache-safety role-tier fallback that
  // covered cached pre-12.5 responses without `user_permissions` has been
  // removed. The 7-day age-out window from Phase 12.5 ship (2026-05-03)
  // would normally close 2026-05-10; Z waived it for this pass based on
  // single-user reality (cached-bundle population the gate was protecting
  // is effectively zero). Audit Items 26-29.
  const userPerms = Array.isArray(currentOrg?.user_permissions)
    ? currentOrg.user_permissions
    : [];

  function hasAny(keys) {
    return keys.some((k) => userPerms.includes(k));
  }

  // Top-level admin tab: any permission at all.
  const hasAnyAdminPerm = userPerms.length > 0;
  const showLegacyAdminDropdown = hasAnyAdminPerm && !isSubOrgScope;

  // Per-subsection visibility flags.
  const showProposals = hasAny(ADMIN_NAV_SUBSECTION_PERMISSIONS.proposals);
  const showTopics = hasAny(ADMIN_NAV_SUBSECTION_PERMISSIONS.topics);
  const showMembers = hasAny(ADMIN_NAV_SUBSECTION_PERMISSIONS.members);
  const showSubOrgs = hasAny(ADMIN_NAV_SUBSECTION_PERMISSIONS.subOrgs);
  const showDelegates = hasAny(ADMIN_NAV_SUBSECTION_PERMISSIONS.delegates);
  const showPolises = hasAny(ADMIN_NAV_SUBSECTION_PERMISSIONS.polises);
  const showSettings = hasAny(ADMIN_NAV_SUBSECTION_PERMISSIONS.settings);
  const showPermissions = hasAny(ADMIN_NAV_SUBSECTION_PERMISSIONS.permissions);
  const showAnalytics = hasAny(ADMIN_NAV_SUBSECTION_PERMISSIONS.analytics);

  // Sub-org admin shortcut still relies on role-tier (sub-org user_role
  // hasn't been fully ported to permission-driven gating; that's tracked
  // as out-of-scope for 12.5 since sub-org settings UI is its own surface).
  const subOrgUserIsAdmin = !!(currentOrg && (
    currentOrg.user_role === 'admin' ||
    currentOrg.user_role === 'steward' ||
    currentOrg.user_role === 'owner'
  ));

  // Phase 11 — resolve parent slug for org-scoped link construction. When
  // the user is scoped to a sub-org, walk up to the parent for parent-org
  // admin links; otherwise currentOrg.slug IS the parent.
  const parentSlugForLinks = (() => {
    if (!currentOrg) return null;
    if (currentOrg.parent_org_id) {
      const parent = userOrgs.find(o => o.id === currentOrg.parent_org_id);
      return parent?.slug || null;
    }
    return currentOrg.slug;
  })();

  useEffect(() => {
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
      if (adminRef.current && !adminRef.current.contains(e.target)) setAdminOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <nav className="bg-[var(--brand-primary)] text-white">
      <div className="max-w-6xl mx-auto px-4 flex items-center justify-between h-14">
        <div className="flex items-center gap-6">
          <Link
            to={navOrg ? urlFor(navOrg, 'proposals') : '/orgs'}
            className="font-semibold text-sm tracking-wide hover:text-blue-100 transition-colors"
          >
            Liquid Democracy
          </Link>

          {/* Org switcher tree (Phase 8.5) */}
          <OrgSwitcher />

          {/* Desktop nav links — Phase 16 F5: render the org-context links
              when navOrg is resolvable (either currentOrg or the fallback
              from localStorage.lastOrgSlug). On /settings and /orgs the
              fallback path keeps Proposals / Delegations links visible
              and pointing at the user's last-visited org so they aren't
              stranded. Notifications is account-scoped and renders below
              regardless. */}
          {navOrg && (
            <div className="hidden md:flex items-center gap-6">
              {/* Phase 34.2 E1 — when navOrg is a sub-org, emit nested
                  /{parent}/sub-orgs/{sub}/{resource} URLs so OrgContext
                  resolves parent + sub correctly. The flat /{sub}/{resource}
                  shape pre-fix hit the top-level org resolver in
                  OrgContext, which couldn't find sub-org slugs in
                  userOrgs unless the sub-org had a duplicated
                  OrgMembership row (Phase 34 hotfix #1 added that for
                  Cedar Court Condos; user-created sub-orgs like
                  Gloomhaven didn't get it). The nested URL resolves via
                  parent-org membership + fetchSubOrgsFor, which works
                  for all sub-orgs regardless of OrgMembership shape. */}
              <NavLink
                to={
                  navOrg.parent_org_id && parentSlugForLinks
                    ? urlFor(parentSlugForLinks, 'sub-org-proposals', navOrg.slug)
                    : urlFor(navOrg, 'proposals')
                }
                end
                className={({ isActive }) =>
                  `text-sm transition-colors ${isActive ? 'text-white font-medium' : 'text-blue-200 hover:text-white'}`
                }
              >
                Proposals
              </NavLink>
              <NavLink
                to={
                  navOrg.parent_org_id && parentSlugForLinks
                    ? urlFor(parentSlugForLinks, 'sub-org-delegations', navOrg.slug)
                    : urlFor(navOrg, 'delegations')
                }
                className={({ isActive }) =>
                  `text-sm transition-colors ${isActive ? 'text-white font-medium' : 'text-blue-200 hover:text-white'}`
                }
              >
                My Delegations
              </NavLink>
              {/* Phase 19 — public delegate browse for all members. */}
              <NavLink
                to={
                  navOrg.parent_org_id && parentSlugForLinks
                    ? urlFor(parentSlugForLinks, 'sub-org-delegates', navOrg.slug)
                    : urlFor(navOrg, 'delegates')
                }
                className={({ isActive }) =>
                  `text-sm transition-colors ${isActive ? 'text-white font-medium' : 'text-blue-200 hover:text-white'}`
                }
              >
                Delegates
              </NavLink>

              {/* Admin dropdown — visible to moderators, admins, stewards on parent-org scope */}
              {showLegacyAdminDropdown && parentSlugForLinks && (
                <div ref={adminRef} className="relative">
                  <button
                    onClick={() => setAdminOpen(!adminOpen)}
                    className={`text-sm transition-colors flex items-center gap-1 ${
                      adminOpen ? 'text-white font-medium' : 'text-blue-200 hover:text-white'
                    }`}
                  >
                    Admin
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  {adminOpen && (
                    <div className="absolute left-0 top-full mt-2 w-56 bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden">
                      {[
                        // Phase 12.5 F1 — each subsection gates on the
                        // ADMIN_NAV_SUBSECTION_PERMISSIONS mapping, not on
                        // role tier. A Member granted a single key sees
                        // only the matching subsection.
                        showSettings && { to: urlFor(parentSlugForLinks, 'admin-settings'), label: 'Org Settings' },
                        showPermissions && { to: urlFor(parentSlugForLinks, 'admin-permissions'), label: 'Permissions' },
                        showMembers && { to: urlFor(parentSlugForLinks, 'admin-members'), label: 'Members' },
                        showProposals && { to: urlFor(parentSlugForLinks, 'admin-proposals'), label: 'Proposals' },
                        showTopics && { to: urlFor(parentSlugForLinks, 'admin-topics'), label: 'Topics' },
                        showPolises && { to: urlFor(parentSlugForLinks, 'admin-polises'), label: 'Polises' },
                        showDelegates && { to: urlFor(parentSlugForLinks, 'delegate-applications-review'), label: 'Delegate Applications' },
                        showAnalytics && { to: urlFor(parentSlugForLinks, 'admin-analytics'), label: 'Analytics' },
                        showSubOrgs && { to: urlFor(parentSlugForLinks, 'admin-sub-orgs'), label: 'Sub-Organizations' },
                      ].filter(Boolean).map((item, i) => (
                        <Link
                          key={item.to}
                          to={item.to}
                          onClick={() => setAdminOpen(false)}
                          className={`block px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors ${
                            i > 0 ? 'border-t border-gray-100' : ''
                          }`}
                        >
                          {item.label}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Sub-org scope shortcut — link back to managing this sub-org if user has admin power */}
              {isSubOrgScope && parentSlugForLinks && subOrgUserIsAdmin && (
                <NavLink
                  to={urlFor(parentSlugForLinks, 'admin-sub-org-settings', currentOrg.slug)}
                  className={({ isActive }) =>
                    `text-sm transition-colors ${isActive ? 'text-white font-medium' : 'text-blue-200 hover:text-white'}`
                  }
                >
                  Manage Sub-Org
                </NavLink>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Phase 16 F3 — top-level Notifications link. Account-scoped
              (no permission gate; notifications are per-user) and visible
              to any authenticated user, including on non-org-scoped pages
              like /settings and /orgs. Sits between the org primary
              content and the bell so the relationship between "feed"
              and "bell quick-glance" reads visually. The bell
              (NotificationBadge below) stays unchanged. */}
          {user && (
            <NavLink
              to="/notifications"
              className={({ isActive }) =>
                `hidden md:inline text-sm transition-colors ${isActive ? 'text-white font-medium' : 'text-blue-200 hover:text-white'}`
              }
            >
              Notifications
            </NavLink>
          )}
          <NotificationBadge />

          {user && (
            <div ref={menuRef} className="relative hidden md:block">
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                className="text-blue-200 hover:text-white text-sm flex items-center gap-2 transition-colors"
              >
                <Avatar user={user} size="sm" />
                <span>{user.display_name}</span>
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {menuOpen && (
                <div className="absolute right-0 top-full mt-2 w-48 bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden">
                  {/* My Profile is org-scoped post-Phase 11. Hide when no
                      currentOrg (user is on /settings, /orgs, etc.) — they
                      can reach their profile from any org page. */}
                  {currentOrg && (
                    <Link
                      to={urlFor(currentOrg, 'user-profile', user.id)}
                      onClick={() => setMenuOpen(false)}
                      className="block px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                    >
                      My Profile
                    </Link>
                  )}
                  {/* Phase 19 — quick link to the user's own delegate-page
                      management surface (org-scoped). */}
                  {currentOrg && !currentOrg.parent_org_id && (
                    <Link
                      to={urlFor(currentOrg, 'delegate-profile')}
                      onClick={() => setMenuOpen(false)}
                      className="block px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors border-t border-gray-100"
                    >
                      My Delegate Page
                    </Link>
                  )}
                  <Link
                    to="/settings"
                    onClick={() => setMenuOpen(false)}
                    className={`block px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors ${currentOrg ? 'border-t border-gray-100' : ''}`}
                  >
                    Account Settings
                  </Link>
                  {userOrgs.length > 1 && (
                    <Link
                      to="/orgs"
                      onClick={() => setMenuOpen(false)}
                      className="block px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors border-t border-gray-100"
                    >
                      Switch Org
                    </Link>
                  )}
                  {/* Phase 9.5 — tertiary entry to org creation. */}
                  <Link
                    to="/orgs/create"
                    onClick={() => setMenuOpen(false)}
                    className="block px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors border-t border-gray-100"
                  >
                    Create Organization
                  </Link>
                  <button
                    onClick={() => { setMenuOpen(false); logout(); }}
                    className="block w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors border-t border-gray-100"
                  >
                    Sign out
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Mobile hamburger */}
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="md:hidden text-blue-200 hover:text-white p-1"
            aria-label="Toggle menu"
          >
            {mobileOpen ? (
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="md:hidden bg-[var(--brand-primary-dark)] border-t border-blue-900 px-4 py-3 space-y-1">
          {currentOrg && (
            <p className="text-xs text-blue-300 mb-2 pb-2 border-b border-blue-900">
              {currentOrg.parent_org_id
                ? `${userOrgs.find(o => o.id === currentOrg.parent_org_id)?.name || 'Org'} / ${currentOrg.name}`
                : currentOrg.name}
            </p>
          )}
          {/* Phase 16 F5 — mobile mirror uses navOrg (currentOrg or
              localStorage.lastOrgSlug fallback) so /settings preserves
              navigation back to the last-visited org. */}
          {navOrg && (
            <>
              <Link
                to={urlFor(navOrg, 'proposals')}
                onClick={() => setMobileOpen(false)}
                className="block py-2 text-sm text-blue-200 hover:text-white"
              >
                Proposals
              </Link>
              <Link
                to={urlFor(navOrg, 'delegations')}
                onClick={() => setMobileOpen(false)}
                className="block py-2 text-sm text-blue-200 hover:text-white"
              >
                My Delegations
              </Link>
              {/* Phase 19 — mobile delegate browse link. */}
              <Link
                to={urlFor(navOrg, 'delegates')}
                onClick={() => setMobileOpen(false)}
                className="block py-2 text-sm text-blue-200 hover:text-white"
              >
                Delegates
              </Link>
            </>
          )}
          {/* Phase 16 F3 — mobile mirror of the desktop Notifications link. */}
          {user && (
            <Link
              to="/notifications"
              onClick={() => setMobileOpen(false)}
              className="block py-2 text-sm text-blue-200 hover:text-white"
            >
              Notifications
            </Link>
          )}
          {showLegacyAdminDropdown && parentSlugForLinks && (
            <>
              <div className="pt-2 mt-2 border-t border-blue-900">
                <p className="text-xs text-blue-300 mb-1">Admin</p>
              </div>
              {[
                // Phase 12.5 F1 — mobile mirror of the desktop dropdown,
                // using the same per-subsection permission flags.
                showSettings && { to: urlFor(parentSlugForLinks, 'admin-settings'), label: 'Org Settings' },
                showPermissions && { to: urlFor(parentSlugForLinks, 'admin-permissions'), label: 'Permissions' },
                showMembers && { to: urlFor(parentSlugForLinks, 'admin-members'), label: 'Members' },
                showProposals && { to: urlFor(parentSlugForLinks, 'admin-proposals'), label: 'Proposals' },
                showTopics && { to: urlFor(parentSlugForLinks, 'admin-topics'), label: 'Topics' },
                showPolises && { to: urlFor(parentSlugForLinks, 'admin-polises'), label: 'Polises' },
                showDelegates && { to: urlFor(parentSlugForLinks, 'delegate-applications-review'), label: 'Delegate Apps' },
                showAnalytics && { to: urlFor(parentSlugForLinks, 'admin-analytics'), label: 'Analytics' },
                showSubOrgs && { to: urlFor(parentSlugForLinks, 'admin-sub-orgs'), label: 'Sub-Orgs' },
              ].filter(Boolean).map(item => (
                <Link
                  key={item.to}
                  to={item.to}
                  onClick={() => setMobileOpen(false)}
                  className="block py-2 text-sm text-blue-200 hover:text-white pl-3"
                >
                  {item.label}
                </Link>
              ))}
            </>
          )}
          {isSubOrgScope && parentSlugForLinks && subOrgUserIsAdmin && (
            <Link
              to={urlFor(parentSlugForLinks, 'admin-sub-org-settings', currentOrg.slug)}
              onClick={() => setMobileOpen(false)}
              className="block py-2 text-sm text-blue-200 hover:text-white"
            >
              Manage Sub-Org
            </Link>
          )}
          {user && (
            <>
              <div className="pt-2 mt-2 border-t border-blue-900 flex items-center gap-2">
                <Avatar user={user} size="sm" />
                <p className="text-xs text-blue-300">{user.display_name}</p>
              </div>
              {currentOrg && (
                <Link
                  to={urlFor(currentOrg, 'user-profile', user.id)}
                  onClick={() => setMobileOpen(false)}
                  className="block py-2 text-sm text-blue-200 hover:text-white"
                >
                  My Profile
                </Link>
              )}
              {/* Phase 19 — mobile entry to the user's delegate-page management. */}
              {currentOrg && !currentOrg.parent_org_id && (
                <Link
                  to={urlFor(currentOrg, 'delegate-profile')}
                  onClick={() => setMobileOpen(false)}
                  className="block py-2 text-sm text-blue-200 hover:text-white"
                >
                  My Delegate Page
                </Link>
              )}
              <Link
                to="/settings"
                onClick={() => setMobileOpen(false)}
                className="block py-2 text-sm text-blue-200 hover:text-white"
              >
                Account Settings
              </Link>
              {userOrgs.length > 1 && (
                <Link
                  to="/orgs"
                  onClick={() => setMobileOpen(false)}
                  className="block py-2 text-sm text-blue-200 hover:text-white"
                >
                  Switch Org
                </Link>
              )}
              <button
                onClick={() => { setMobileOpen(false); logout(); }}
                className="block w-full text-left py-2 text-sm text-blue-200 hover:text-white"
              >
                Sign out
              </button>
            </>
          )}
          <div className="pt-2 mt-2 border-t border-blue-900 flex gap-4">
            <Link to="/privacy" onClick={() => setMobileOpen(false)} className="text-xs text-blue-300 hover:text-white">Privacy</Link>
            <Link to="/terms" onClick={() => setMobileOpen(false)} className="text-xs text-blue-300 hover:text-white">Terms</Link>
          </div>
        </div>
      )}
    </nav>
  );
}
