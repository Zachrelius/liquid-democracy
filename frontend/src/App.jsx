import { Routes, Route, Navigate, Link } from 'react-router-dom';
import { AuthProvider, useAuth } from './AuthContext';
import { OrgProvider, useOrg } from './OrgContext';
import { PublicConfigProvider } from './PublicConfigContext';
import { ToastProvider } from './components/Toast';
import { ConfirmProvider } from './components/ConfirmDialog';
import BrandingThemeApplier from './components/BrandingThemeApplier';
// Phase 23 F1 — disclosure banner + reset-in-progress overlay shown on
// demo orgs only. Self-gates on org.is_demo; renders nothing for real orgs.
import DemoOrgBanner from './components/DemoOrgBanner';
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
// Phase 13 F2/F3 — account-scoped notifications surfaces.
import NotificationsPage from './pages/NotificationsPage';
import NotificationsPreferences from './pages/NotificationsPreferences';
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
// Phase 20 F3 — renamed from SustainedMajorityHelp; serves both
// /help/stable-result (canonical) and /help/sustained-majority (kept as
// an alias so existing in-app/external links don't 404).
import StableResultHelp from './pages/StableResultHelp';
import PolisHelp from './pages/PolisHelp';
import RolePermissionsHelp from './pages/RolePermissionsHelp';
import NotificationsHelp from './pages/NotificationsHelp';
import OrganizationsHelp from './pages/OrganizationsHelp';
// Phase 19 D1 — public help page for the public-delegate surface.
import PublicDelegatesHelp from './pages/PublicDelegatesHelp';
// Phase 43 Clusters H + C — help hub + three new "getting started" pages.
import HelpIndex from './pages/HelpIndex';
import GettingStartedMember from './pages/GettingStartedMember';
import GettingStartedSteward from './pages/GettingStartedSteward';
import GettingStartedDelegate from './pages/GettingStartedDelegate';
import Privacy from './pages/Privacy';
import Terms from './pages/Terms';
import Landing from './pages/Landing';
import About from './pages/About';
import Why from './pages/Why';
import Security from './pages/Security';
import Demo from './pages/Demo';
// Phase 14 F2 — public org landing page; lives at the bare /{slug} URL and
// renders the splash for non-members and members alike (no auto-redirect).
import OrgPublicLanding from './pages/OrgPublicLanding';
// Phase 19 — public delegate page surfaces (F1 management, F2 public,
// F4 browse, F5 approver dashboard).
import DelegateProfile from './pages/DelegateProfile';
import Delegates from './pages/Delegates';
import DelegatePublic from './pages/DelegatePublic';
import DelegateApplicationsReview from './pages/DelegateApplicationsReview';

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
 * Phase 12.7 F2 — apply the active org's branding to document.documentElement.
 *
 * Phase 14 F2 — the underlying CSS-var application logic was extracted to
 * `components/BrandingThemeApplier.jsx` so the public org landing page
 * (which doesn't go through OrgScopedLayout's auth gate) can reuse it.
 * This thin wrapper bridges OrgContext into the prop-shaped component so
 * org-scoped routes keep their existing "active org's branding" behavior
 * with no call-site changes downstream.
 */
function OrgScopedBrandingTheme() {
  const { currentOrg } = useOrg();
  return <BrandingThemeApplier branding={currentOrg?.branding} />;
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
  const { accessDenied, loading, currentOrg } = useOrg();
  if (loading) {
    return (
      <Layout>
        <OrgScopedBrandingTheme />
        <div className="flex items-center justify-center py-20">
          <div className="text-gray-500 text-sm">Loading…</div>
        </div>
      </Layout>
    );
  }
  if (accessDenied) {
    return (
      <Layout>
        <OrgScopedBrandingTheme />
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
      <OrgScopedBrandingTheme />
      {/* Phase 23 F1 — disclosure banner for demo orgs. Self-gates on
          currentOrg.is_demo; shows reset-in-progress overlay when the
          backend sets is_demo_resetting=true. Banner placement is here
          (the org-scoped shell) so it appears on all member-facing org
          pages (proposals, delegations, delegate-pages, admin, etc.). */}
      <DemoOrgBanner org={currentOrg} />
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
  // Phase 43 Cluster F: previously redirected authenticated users to /orgs.
  // The new "Start an organization" CTA needs to be reachable from / for
  // both logged-out (recruiting) and logged-in (existing user starting a
  // second org) audiences — QA scenarios 1 + 2. Render Landing for both.
  const { loading } = useAuth();
  if (loading) return null;
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
        {/* Phase 43 Cluster H — public help hub. */}
        <Route path="/help" element={<HelpIndex />} />
        {/* Phase 43 Cluster C — three new "getting started" audience pages. */}
        <Route path="/help/getting-started-member" element={<GettingStartedMember />} />
        <Route path="/help/getting-started-steward" element={<GettingStartedSteward />} />
        <Route path="/help/getting-started-delegate" element={<GettingStartedDelegate />} />
        <Route path="/help/voting-methods" element={<VotingMethodsHelp />} />
        <Route path="/help/stable-result" element={<StableResultHelp />} />
        {/* Phase 20 F3 — legacy route alias; same component, different URL. */}
        <Route path="/help/sustained-majority" element={<StableResultHelp />} />
        <Route path="/help/polis" element={<PolisHelp />} />
        <Route path="/help/role-permissions" element={<RolePermissionsHelp />} />
        <Route path="/help/notifications" element={<NotificationsHelp />} />
        <Route path="/help/organizations" element={<OrganizationsHelp />} />
        <Route path="/help/public-delegates" element={<PublicDelegatesHelp />} />

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
        {/* Phase 13 F3 — notification preferences page (account-scoped, NOT
            wrapped in OrgScopedLayout per spec). */}
        <Route
          path="/settings/notifications"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><NotificationsPreferences /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        {/* Phase 13 F2 — full notifications page (account-scoped). */}
        <Route
          path="/notifications"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><NotificationsPage /></Layout>
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
        {/* Phase 19 F1 — viewer's own delegate page management surface. */}
        <Route
          path="/:org_slug/delegate-profile"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><DelegateProfile /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        {/* Phase 19 F4 — org-scoped public delegate browse page. Visible to
            all org members; the backend endpoint also serves non-members
            for publicly-listed orgs (matching org public landing semantics). */}
        <Route
          path="/:org_slug/delegates"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><Delegates /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        {/* Phase 19 F2 — public-facing per-delegate page. Reads the browse
            endpoint and the user's profile to render the page; visibility
            gates are enforced server-side (404 when not allowed). */}
        <Route
          path="/:org_slug/delegates/:handle_or_username"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><DelegatePublic /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        {/* Phase 19 F5 — approver-only dashboard for delegate applications
            (the new public_accepting submission flow). Page-level gates on
            `delegate_application.approve` and renders an inline 403 to
            non-approvers (no AdminRoute wrapper because the link is also
            permission-gated in the nav, but we keep the page itself
            tolerant of direct URL navigation by non-approvers). */}
        <Route
          path="/:org_slug/delegate-applications"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><DelegateApplicationsReview /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        {/* Phase 34.2 E1 — non-admin sub-org routes. Mount the same Org-
            scoped components but at the /<parent>/sub-orgs/<sub>/<resource>
            URL pattern so OrgContext can resolve parent + sub from URL
            params (params.org_slug + params.sub_slug). This is the route
            shape Nav.jsx now emits when navigating inside a sub-org
            context. */}
        <Route
          path="/:org_slug/sub-orgs/:sub_slug/proposals"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><Proposals /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/sub-orgs/:sub_slug/proposals/:id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><ProposalDetail /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/sub-orgs/:sub_slug/delegations"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><Delegations /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/sub-orgs/:sub_slug/delegates"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><Delegates /></OrgScopedLayout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/:org_slug/sub-orgs/:sub_slug/delegates/:handle_or_username"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <OrgScopedLayout><DelegatePublic /></OrgScopedLayout>
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
        {/* Phase 30.1 B4 — /:org_slug/admin/delegates removed. The
            legacy admin Delegate Applications page was replaced by the
            canonical Phase 19 surface at /:org_slug/delegate-applications. */}
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

        {/* ------------------------------------------------------------- */}
        {/* Phase 14 F1 — public org landing page at bare /{slug}.        */}
        {/*                                                               */}
        {/* This route is intentionally NOT wrapped in ProtectedRoute or  */}
        {/* OrgScopedLayout: the public splash must render for logged-out */}
        {/* visitors, logged-in non-members, AND members (no auto-redirect*/}
        {/* to /{slug}/proposals — Z's Q1 ruling). The page reads auth    */}
        {/* state via useAuth and membership via OrgProvider's userOrgs   */}
        {/* (empty for logged-out users); branding is applied via the    */}
        {/* lifted BrandingThemeApplier hook against the public-endpoint  */}
        {/* response shape rather than via OrgScopedLayout.               */}
        {/*                                                               */}
        {/* The route must sit AFTER all the specific top-level routes    */}
        {/* (/login, /register, /orgs, /help/*, /invite/:token, etc.) so  */}
        {/* react-router's "more specific wins" still applies, and BEFORE */}
        {/* the catch-all so unknown slugs reach the splash (which itself */}
        {/* renders the "organization not found" UI on the endpoint's    */}
        {/* 404). Sub-paths like /{slug}/proposals stay member-gated via  */}
        {/* the existing /:org_slug/* routes above; this single-segment   */}
        {/* /:org_slug pattern only matches the bare slug case.           */}
        <Route
          path="/:org_slug"
          element={
            <OrgProvider>
              <OrgPublicLanding />
            </OrgProvider>
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
