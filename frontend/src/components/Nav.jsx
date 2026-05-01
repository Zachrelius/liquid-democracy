import { useState, useRef, useEffect } from 'react';
import { NavLink, Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
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
  const { currentOrg, userOrgs, setCurrentOrg, fetchSubOrgsFor, subOrgsByParent } = useOrg();
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
  if (currentOrg.parent_org_id) {
    const parent = userOrgs.find(o => o.id === currentOrg.parent_org_id);
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

  function pickOrg(org) {
    setCurrentOrg(org);
    setOpen(false);
    navigate('/proposals');
  }

  return (
    <div ref={ref} className="hidden sm:block relative">
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-blue-200 hover:text-white transition-colors flex items-center gap-1"
      >
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
            const isParentAdmin = parent.user_role === 'admin' || parent.user_role === 'owner';
            return (
              <div key={parent.id} className="border-b border-gray-100 last:border-0 pb-2 mb-1 last:mb-0">
                <button
                  onClick={() => pickOrg(parent)}
                  className={`w-full text-left px-4 py-1.5 text-sm hover:bg-gray-50 transition-colors flex items-center justify-between ${
                    isCurrentParent ? 'bg-blue-50 font-medium text-[#1B3A5C]' : 'text-gray-800'
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
                      const subAdmin = sub.user_role === 'admin' || sub.user_role === 'owner';
                      return (
                        <div key={sub.id} className="flex items-center justify-between gap-2 pr-2">
                          <button
                            onClick={() => pickOrg(sub)}
                            className={`flex-1 text-left px-4 py-1.5 text-xs hover:bg-gray-50 transition-colors flex items-center gap-2 ${
                              isCurrentSub ? 'bg-blue-50 font-medium text-[#1B3A5C]' : 'text-gray-700'
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
                              to={`/admin/sub-orgs/${sub.slug}/settings`}
                              onClick={() => setOpen(false)}
                              className="text-[10px] text-[#2E75B6] hover:underline shrink-0"
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
                    to="/admin/sub-orgs"
                    onClick={() => setOpen(false)}
                    className="block px-4 py-1.5 text-xs text-[#2E75B6] hover:underline pl-8"
                  >
                    + manage sub-organizations
                  </Link>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function Nav() {
  const { user, logout } = useAuth();
  const { currentOrg, userOrgs, isAdmin, isModeratorOrAdmin } = useOrg();
  const [menuOpen, setMenuOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuRef = useRef(null);
  const adminRef = useRef(null);

  // currentOrg is a sub-org when it has a parent_org_id; the legacy admin
  // dropdown (parent-org admin pages) is hidden in that mode because those
  // pages target the parent org's slug. Sub-org admin pages have their own
  // route family.
  const isSubOrgScope = !!currentOrg?.parent_org_id;
  const showLegacyAdminDropdown = isModeratorOrAdmin && !isSubOrgScope;

  useEffect(() => {
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
      if (adminRef.current && !adminRef.current.contains(e.target)) setAdminOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <nav className="bg-[#1B3A5C] text-white">
      <div className="max-w-6xl mx-auto px-4 flex items-center justify-between h-14">
        <div className="flex items-center gap-6">
          <Link to="/proposals" className="font-semibold text-sm tracking-wide hover:text-blue-100 transition-colors">
            Liquid Democracy
          </Link>

          {/* Org switcher tree (Phase 8.5) */}
          <OrgSwitcher />

          {/* Desktop nav links */}
          <div className="hidden md:flex items-center gap-6">
            <NavLink
              to="/proposals"
              className={({ isActive }) =>
                `text-sm transition-colors ${isActive ? 'text-white font-medium' : 'text-blue-200 hover:text-white'}`
              }
            >
              Proposals
            </NavLink>
            <NavLink
              to="/delegations"
              className={({ isActive }) =>
                `text-sm transition-colors ${isActive ? 'text-white font-medium' : 'text-blue-200 hover:text-white'}`
              }
            >
              My Delegations
            </NavLink>

            {/* Admin dropdown — visible to moderators, admins, owners on parent-org scope */}
            {showLegacyAdminDropdown && (
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
                      isAdmin && { to: '/admin/settings', label: 'Org Settings' },
                      { to: '/admin/members', label: 'Members' },
                      { to: '/admin/proposals', label: 'Proposals' },
                      { to: '/admin/topics', label: 'Topics' },
                      { to: '/admin/polises', label: 'Polises' },
                      isAdmin && { to: '/admin/delegates', label: 'Delegate Applications' },
                      isAdmin && { to: '/admin/analytics', label: 'Analytics' },
                      isAdmin && { to: '/admin/sub-orgs', label: 'Sub-Organizations' },
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
            {isSubOrgScope && (currentOrg.user_role === 'admin' || currentOrg.user_role === 'owner') && (
              <NavLink
                to={`/admin/sub-orgs/${currentOrg.slug}/settings`}
                className={({ isActive }) =>
                  `text-sm transition-colors ${isActive ? 'text-white font-medium' : 'text-blue-200 hover:text-white'}`
                }
              >
                Manage Sub-Org
              </NavLink>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <NotificationBadge />

          {user && (
            <div ref={menuRef} className="relative hidden md:block">
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                className="text-blue-200 hover:text-white text-sm flex items-center gap-1 transition-colors"
              >
                {user.display_name}
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {menuOpen && (
                <div className="absolute right-0 top-full mt-2 w-40 bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden">
                  <Link
                    to={`/users/${user.id}`}
                    onClick={() => setMenuOpen(false)}
                    className="block px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    My Profile
                  </Link>
                  <Link
                    to="/settings"
                    onClick={() => setMenuOpen(false)}
                    className="block px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors border-t border-gray-100"
                  >
                    Settings
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
        <div className="md:hidden bg-[#152d4a] border-t border-blue-900 px-4 py-3 space-y-1">
          {currentOrg && (
            <p className="text-xs text-blue-300 mb-2 pb-2 border-b border-blue-900">
              {currentOrg.parent_org_id
                ? `${userOrgs.find(o => o.id === currentOrg.parent_org_id)?.name || 'Org'} / ${currentOrg.name}`
                : currentOrg.name}
            </p>
          )}
          <Link
            to="/proposals"
            onClick={() => setMobileOpen(false)}
            className="block py-2 text-sm text-blue-200 hover:text-white"
          >
            Proposals
          </Link>
          <Link
            to="/delegations"
            onClick={() => setMobileOpen(false)}
            className="block py-2 text-sm text-blue-200 hover:text-white"
          >
            My Delegations
          </Link>
          {showLegacyAdminDropdown && (
            <>
              <div className="pt-2 mt-2 border-t border-blue-900">
                <p className="text-xs text-blue-300 mb-1">Admin</p>
              </div>
              {[
                isAdmin && { to: '/admin/settings', label: 'Org Settings' },
                { to: '/admin/members', label: 'Members' },
                { to: '/admin/proposals', label: 'Proposals' },
                { to: '/admin/topics', label: 'Topics' },
                { to: '/admin/polises', label: 'Polises' },
                isAdmin && { to: '/admin/delegates', label: 'Delegate Apps' },
                isAdmin && { to: '/admin/analytics', label: 'Analytics' },
                isAdmin && { to: '/admin/sub-orgs', label: 'Sub-Orgs' },
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
          {isSubOrgScope && (currentOrg.user_role === 'admin' || currentOrg.user_role === 'owner') && (
            <Link
              to={`/admin/sub-orgs/${currentOrg.slug}/settings`}
              onClick={() => setMobileOpen(false)}
              className="block py-2 text-sm text-blue-200 hover:text-white"
            >
              Manage Sub-Org
            </Link>
          )}
          {user && (
            <>
              <div className="pt-2 mt-2 border-t border-blue-900">
                <p className="text-xs text-blue-300 mb-1">{user.display_name}</p>
              </div>
              <Link
                to={`/users/${user.id}`}
                onClick={() => setMobileOpen(false)}
                className="block py-2 text-sm text-blue-200 hover:text-white"
              >
                My Profile
              </Link>
              <Link
                to="/settings"
                onClick={() => setMobileOpen(false)}
                className="block py-2 text-sm text-blue-200 hover:text-white"
              >
                Settings
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
