import { useState, useRef, useEffect } from 'react';
import { NavLink, Link } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import NotificationBadge from './NotificationBadge';

export default function Nav() {
  const { user, logout } = useAuth();
  const { currentOrg, userOrgs, isAdmin } = useOrg();
  const [menuOpen, setMenuOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuRef = useRef(null);
  const adminRef = useRef(null);

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

          {/* Org name / switcher */}
          {currentOrg && (
            <span className="hidden sm:flex text-xs text-blue-200 items-center gap-1">
              {userOrgs.length > 1 ? (
                <Link to="/orgs" className="hover:text-white transition-colors flex items-center gap-1">
                  {currentOrg.name}
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
                  </svg>
                </Link>
              ) : (
                currentOrg.name
              )}
            </span>
          )}

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

            {/* Admin dropdown */}
            {isAdmin && (
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
                  <div className="absolute left-0 top-full mt-2 w-48 bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden">
                    {[
                      { to: '/admin/settings', label: 'Org Settings' },
                      { to: '/admin/members', label: 'Members' },
                      { to: '/admin/proposals', label: 'Proposals' },
                      { to: '/admin/topics', label: 'Topics' },
                      { to: '/admin/delegates', label: 'Delegate Applications' },
                      { to: '/admin/analytics', label: 'Analytics' },
                    ].map((item, i) => (
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
            <p className="text-xs text-blue-300 mb-2 pb-2 border-b border-blue-900">{currentOrg.name}</p>
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
          {isAdmin && (
            <>
              <div className="pt-2 mt-2 border-t border-blue-900">
                <p className="text-xs text-blue-300 mb-1">Admin</p>
              </div>
              {[
                { to: '/admin/settings', label: 'Org Settings' },
                { to: '/admin/members', label: 'Members' },
                { to: '/admin/proposals', label: 'Proposals' },
                { to: '/admin/topics', label: 'Topics' },
                { to: '/admin/delegates', label: 'Delegate Apps' },
                { to: '/admin/analytics', label: 'Analytics' },
              ].map(item => (
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
