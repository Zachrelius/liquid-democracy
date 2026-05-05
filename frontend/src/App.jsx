import { useEffect } from 'react';
import { Routes, Route, Navigate, Link } from 'react-router-dom';
import { AuthProvider, useAuth } from './AuthContext';
import { OrgProvider, useOrg } from './OrgContext';
import { PublicConfigProvider } from './PublicConfigContext';
import { ToastProvider } from './components/Toast';
import { ConfirmProvider } from './components/ConfirmDialog';
import { deriveDarker } from './utils/color_derive';
import ProtectedRoute from './ProtectedRoute';
import AdminRoute from './AdminRoute';
import AdminOnlyRoute from './AdminOnlyRoute';
import { ADMIN_NAV_SUBSECTION_PERMISSIONS } from './constants/admin_nav_permissions';
import Nav from './components/Nav';
import EmailVerificationBanner from './components/EmailVerificationBanner';
// Phase 10.1 W3 — gentle, mobile-only PWA install affordance. Mounted once
// at the App root so it renders regardless of auth state or current route.
import InstallPWABanner from './components/InstallPWABanner';
// Phase 10.1 W4 — listens for app:bundle-updated (dispatched in main.jsx
// from the SW controllerchange event) and shows a "new version available"
// toast with a Refresh action.
import BundleUpdateNotifier from './components/BundleUpdateNotifier';
import Login from './pages/Login';
import Proposals from './pages/Proposals';
import ProposalDetail from './pages/ProposalDetail';
import Delegations from './pages/Delegations';
import UserProfile from './pages/UserProfile';
import Settings from './pages/Settings';
import VerifyEmail from './pages/VerifyEmail';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import InviteAccept from './pages/InviteAccept';
import OrgSelector from './pages/OrgSelector';
import CreateOrg from './pages/CreateOrg';
import SetupWizard from './pages/SetupWizard';
import OrgSettings from './pages/admin/OrgSettings';
// Phase 12 Stage 2 — role-permissions matrix page (Cluster F).
import RolePermissionsPage from './pages/admin/RolePermissionsPage';
import Members from './pages/admin/Members';
import ProposalManagement from './pages/admin/ProposalManagement';
import Topics from './pages/admin/Topics';
import DelegateApplications from './pages/admin/DelegateApplications';
import Analytics from './pages/admin/Analytics';
// Phase 8.5 — sub-org admin route family
import SubOrgList from './pages/admin/SubOrgList';
import SubOrgSettings from './pages/admin/SubOrgSettings';
import SubOrgMembers from './pages/admin/SubOrgMembers';
import SubOrgProposals from './pages/admin/SubOrgProposals';
import SubOrgTopics from './pages/admin/SubOrgTopics';
// Phase 9 — Polis admin route family
import Polises from './pages/admin/Polises';
import PolisDetail from './pages/admin/PolisDetail';
import CreatePolis from './pages/admin/CreatePolis';
import SubOrgPolises from './pages/admin/SubOrgPolises';
import Polis from './pages/Polis';
import VotingMethodsHelp from './pages/VotingMethodsHelp';
import SustainedMajorityHelp from './pages/SustainedMajorityHelp';
import PolisHelp from './pages/PolisHelp';
import RolePermissionsHelp from './pages/RolePermissionsHelp';
import Privacy from './pages/Privacy';
import Terms from './pages/Terms';
import Landing from './pages/Landing';
import About from './pages/About';
import Why from './pages/Why';
import Security from './pages/Security';
import Demo from './pages/Demo';

function Layout({ children }) {
  return (
    <div className="min-h-screen bg-[#F8F9FA]">
      <Nav />
      <EmailVerificationBanner />
      <main>{children}</main>
    </div>
  );
}

/**
 * Phase 12.7 F2 — apply org branding to the document root via CSS variables.
 *
 * Runs whenever the active org's branding object changes (org switch, save
 * in the Branding settings section, etc.). When `currentOrg.branding` has
 * non-null primary / accent values, sets the corresponding CSS custom
 * properties on document.documentElement so the styles defined in
 * index.css's :root block are overridden globally. Cleanup on unmount
 * (org switch to a different OrgScopedLayout instance, or navigation away
 * from any org-scoped route) removes the overrides — platform defaults
 * reapply automatically because the :root rule remains in place.
 *
 * The -primary-dark variant is auto-derived from primary via deriveDarker
 * (HSL darken by ~10) so stewards configure only primary + accent.
 *
 * Renders no DOM. Mounted inside OrgScopedLayout so it's only active on
 * org-scoped routes; non-org-scoped pages (login, marketing, OrgSelector,
 * /settings, /orgs/create) inherit platform defaults from index.css.
 */
function BrandingThemeApplier() {
  const { currentOrg } = useOrg();
  const branding = currentOrg?.branding;
  const primary = branding?.primary_color || null;
  const accent = branding?.accent_color || null;

  useEffect(() => {
    const root = document.documentElement;
    if (primary) {
      root.style.setProperty('--brand-primary', primary);
      root.style.setProperty('--brand-primary-dark', deriveDarker(primary, 10));
    } else {
      root.style.removeProperty('--brand-primary');
      root.style.removeProperty('--brand-primary-dark');
    }
    if (accent) {
      root.style.setProperty('--brand-accent', accent);
    } else {
      root.style.removeProperty('--brand-accent');
    }
    // Cleanup: when the user navigates to a non-org-scoped route,
    // OrgScopedLayout unmounts and this effect's cleanup runs, restoring
    // platform defaults. The same cleanup also fires on org-switch within
    // OrgScopedLayout (via the deps re-run before applying new values),
    // but that's fine — the next effect run sets them right back.
    return () => {
      root.style.removeProperty('--brand-primary');
      root.style.removeProperty('--brand-primary-dark');
      root.style.removeProperty('--brand-accent');
    };
  }, [primary, accent]);

  return null;
}

/**
 * Phase 11 — wrapper for org-scoped route trees.
 *
 * Sits between ProtectedRoute and the page so it can read the URL-derived
 * currentOrg out of OrgContext. When the URL slug points at an org the
 * authenticated user isn't a member of, render an inline "no access" surface
 * with a link back to /orgs (per spec line 200 — NOT a silent redirect).
 *
 * The OrgContext sets `accessDenied=true` only after `loading=false`, so
 * the no-access pane never flashes during the initial /api/orgs fetch.
 *
 * Phase 12.7 F2 — also mounts BrandingThemeApplier so the active org's
 * primary / accent CSS variables are applied (and cleaned up on org
 * switch / route leave).
 */
function OrgScopedLayout({ children }) {
  const { accessDenied, loading } = useOrg();
  if (loading) {
    return (
      <Layout>
        <BrandingThemeApplier />
        <div className="flex items-center justify-center py-20">
          <div className="text-gray-500 text-sm">Loading…</div>
        </div>
      </Layout>
    );
  }
  if (accessDenied) {
    return (
      <Layout>
        <BrandingThemeApplier />
        <div className="max-w-xl mx-auto px-4 py-20 text-center space-y-3">
          <h1 className="text-xl font-semibold text-[var(--brand-primary)]">
            You don&apos;t have access to this organization
          </h1>
          <p className="text-sm text-gray-600">
            This organization either doesn&apos;t exist or you&apos;re not a
            member. Pick an organization you belong to from the list.
          </p>
          <Link
            to="/orgs"
            className="inline-block mt-2 px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
          >
            Back to your organizations
          </Link>
        </div>
      </Layout>
    );
  }
  return (
    <Layout>
      <BrandingThemeApplier />
      {children}
    </Layout>
  );
}

/**
 * Phase 11 — authenticated landing redirect for `/`.
 *
 * If the visitor is logged in, send them to /orgs (which then optionally
 * auto-redirects single-org users to /{slug}/proposals). If unauthenticated,
 * render the Landing page as before.
 */
function LandingOrRedirect() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/orgs" replace />;
  return <Landing />;
}

export default function App() {
  return (
    <AuthProvider>
      <PublicConfigProvider>
      <ToastProvider>
      <ConfirmProvider>
      {/* Phase 10.1 W3 — PWA install banner. Renders regardless of auth state
          or current route; component itself self-gates on viewport, install
          state, and prior dismissal. */}
      <InstallPWABanner />
      {/* Phase 10.1 W4 — stale-bundle update notifier. Renders nothing; just
          listens for the SW controllerchange-driven custom event and surfaces
          a toast with a Refresh action when a new bundle takes control. */}
      <BundleUpdateNotifier />
      <Routes>
        {/* ------------------------------------------------------------- */}
        {/* Public marketing — no auth, no Nav, top-level (Phase 11 D4)   */}
        {/* ------------------------------------------------------------- */}
        <Route path="/" element={<LandingOrRedirect />} />
        <Route path="/about" element={<About />} />
        <Route path="/why" element={<Why />} />
        <Route path="/security" element={<Security />} />
        <Route path="/demo" element={<Demo />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/help/voting-methods" element={<VotingMethodsHelp />} />
        <Route path="/help/sustained-majority" element={<SustainedMajorityHelp />} />
        <Route path="/help/polis" element={<PolisHelp />} />
        <Route path="/help/role-permissions" element={<RolePermissionsHelp />} />

        {/* ------------------------------------------------------------- */}
        {/* Auth flows — no auth required, no org context                 */}
        {/* ------------------------------------------------------------- */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Login />} />
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        {/* Phase 9.7 W3 — public invitation acceptance. Page self-dispatches
            on auth state, so it must NOT be wrapped in ProtectedRoute. */}
        <Route path="/invite/:token" element={<InviteAccept />} />

        {/* ------------------------------------------------------------- */}
        {/* Onboarding — auth required, no org slug yet                   */}
        {/* ------------------------------------------------------------- */}
        <Route
          path="/orgs"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><OrgSelector /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/orgs/create"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><CreateOrg /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/setup"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><SetupWizard /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />

        {/* ------------------------------------------------------------- */}
        {/* User-scoped — /settings is account settings (not org settings) */}
        {/* ------------------------------------------------------------- */}
        <Route
          path="/settings"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><Settings /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />

        {/* ------------------------------------------------------------- */}
        {/* Org-scoped app routes (Phase 11 D1)                           */}
        {/* ------------------------------------------------------------- */}
        <Route
          path="/:org_slug/proposals"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><Proposals /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/proposals/:id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><ProposalDetail /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/delegations"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><Delegations /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/users/:id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><UserProfile /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        {/* Phase 11 D3 — voter-facing Polis page. Was /orgs/:slug/polises/...
            pre-refactor; drops the /orgs/ prefix to match D1. */}
        <Route
          path="/:org_slug/polises/:polis_id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><Polis /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />

        {/* ------------------------------------------------------------- */}
        {/* Org-scoped admin routes (parent-org admin/moderator gated)    */}
        {/* ------------------------------------------------------------- */}
        <Route
          path="/:org_slug/admin/settings"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminOnlyRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.settings}>
                  <OrgScopedLayout><OrgSettings /></OrgScopedLayout>
                </AdminOnlyRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        {/* Phase 12 Stage 2 F1 — role-permissions matrix page.
            NOT wrapped in AdminRoute: members get a read-only view via
            internal page-level gating (F6) rather than a 403. */}
        <Route
          path="/:org_slug/admin/settings/permissions"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><RolePermissionsPage /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/members"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.members}>
                  <OrgScopedLayout><Members /></OrgScopedLayout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/proposals"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.proposals}>
                  <OrgScopedLayout><ProposalManagement /></OrgScopedLayout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/topics"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.topics}>
                  <OrgScopedLayout><Topics /></OrgScopedLayout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/delegates"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminOnlyRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.delegates}>
                  <OrgScopedLayout><DelegateApplications /></OrgScopedLayout>
                </AdminOnlyRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/analytics"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminOnlyRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.analytics}>
                  <OrgScopedLayout><Analytics /></OrgScopedLayout>
                </AdminOnlyRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/polises"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.polises}>
                  <OrgScopedLayout><Polises /></OrgScopedLayout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/polises/create"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.polises}>
                  <OrgScopedLayout><CreatePolis /></OrgScopedLayout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/polises/:polis_id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.polises}>
                  <OrgScopedLayout><PolisDetail /></OrgScopedLayout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/sub-orgs"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminOnlyRoute permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.subOrgs}>
                  <OrgScopedLayout><SubOrgList /></OrgScopedLayout>
                </AdminOnlyRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />

        {/* ------------------------------------------------------------- */}
        {/* Sub-org admin routes — gated server-side via                  */}
        {/* `is_sub_org_admin` (Decision 6 implicit power).               */}
        {/* SubOrgErrorState surfaces 403/404 inline.                     */}
        {/* ------------------------------------------------------------- */}
        <Route
          path="/:org_slug/admin/sub-orgs/:sub_slug"
          element={<Navigate to="settings" replace />}
        />
        <Route
          path="/:org_slug/admin/sub-orgs/:sub_slug/settings"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><SubOrgSettings /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/sub-orgs/:sub_slug/members"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><SubOrgMembers /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/sub-orgs/:sub_slug/proposals"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><SubOrgProposals /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/sub-orgs/:sub_slug/topics"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><SubOrgTopics /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/sub-orgs/:sub_slug/polises"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><SubOrgPolises /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/sub-orgs/:sub_slug/polises/create"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><CreatePolis /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/admin/sub-orgs/:sub_slug/polises/:polis_id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><PolisDetail /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />

        {/* Catch-all (Phase 11 D5: no redirect grace period for old URLs) */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </ConfirmProvider>
      </ToastProvider>
      </PublicConfigProvider>
    </AuthProvider>
  );
}
