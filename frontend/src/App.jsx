import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './AuthContext';
import { OrgProvider } from './OrgContext';
import { PublicConfigProvider } from './PublicConfigContext';
import { ToastProvider } from './components/Toast';
import { ConfirmProvider } from './components/ConfirmDialog';
import ProtectedRoute from './ProtectedRoute';
import AdminRoute from './AdminRoute';
import AdminOnlyRoute from './AdminOnlyRoute';
import Nav from './components/Nav';
import EmailVerificationBanner from './components/EmailVerificationBanner';
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

export default function App() {
  return (
    <AuthProvider>
      <PublicConfigProvider>
      <ToastProvider>
      <ConfirmProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Login />} />
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route
          path="/proposals"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><Proposals /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/proposals/:id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><ProposalDetail /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/delegations"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><Delegations /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/users/:id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><UserProfile /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
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

        {/* Admin routes */}
        <Route
          path="/admin/settings"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminOnlyRoute>
                  <Layout><OrgSettings /></Layout>
                </AdminOnlyRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/members"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute>
                  <Layout><Members /></Layout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/proposals"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute>
                  <Layout><ProposalManagement /></Layout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/topics"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute>
                  <Layout><Topics /></Layout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/delegates"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminOnlyRoute>
                  <Layout><DelegateApplications /></Layout>
                </AdminOnlyRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        {/* Phase 9 — Polis admin routes (parent-org scope). Polis create
            is gated AdminRoute (moderator+ matches the topic-create tier);
            list/detail also AdminRoute so backend permission rules are the
            source of truth (admin controls hide on non-polis-admin viewers). */}
        <Route
          path="/admin/polises"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute>
                  <Layout><Polises /></Layout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/polises/create"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute>
                  <Layout><CreatePolis /></Layout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/polises/:polis_id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminRoute>
                  <Layout><PolisDetail /></Layout>
                </AdminRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/analytics"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminOnlyRoute>
                  <Layout><Analytics /></Layout>
                </AdminOnlyRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />

        {/* Phase 8.5 — Sub-Organization admin routes.
            Permission gating: server-side `is_sub_org_admin` (Decision 6
            implicit power) is the source of truth. Each page surfaces 403/404
            inline via SubOrgErrorState rather than redirecting from a wrapper. */}
        <Route
          path="/admin/sub-orgs"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <AdminOnlyRoute>
                  <Layout><SubOrgList /></Layout>
                </AdminOnlyRoute>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/sub-orgs/:sub_slug/settings"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><SubOrgSettings /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/sub-orgs/:sub_slug/members"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><SubOrgMembers /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/sub-orgs/:sub_slug/proposals"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><SubOrgProposals /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/sub-orgs/:sub_slug/topics"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><SubOrgTopics /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        {/* Phase 9 — sub-org Polis admin routes. Pattern mirrors topics/
            proposals: no AdminRoute wrapper because SubOrgErrorState
            surfaces 403/404 inline rather than redirecting (Decision-6
            implicit power makes a wrapper-time check awkward). */}
        <Route
          path="/admin/sub-orgs/:sub_slug/polises"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><SubOrgPolises /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/sub-orgs/:sub_slug/polises/create"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><CreatePolis /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/sub-orgs/:sub_slug/polises/:polis_id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><PolisDetail /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/sub-orgs/:sub_slug"
          element={<Navigate to="settings" replace />}
        />

        {/* Phase 9 — voter-facing Polis page (Decision 4 + 5 surface). Gated
            ProtectedRoute > OrgProvider > Layout. No AdminRoute — voters
            access this. Server-side `eligible_viewers_for_polis` returns
            403/404 if out-of-scope; the page surfaces those as friendly
            errors (read-only banner for sub-org non-members per Decision 7). */}
        <Route
          path="/orgs/:slug/polises/:polis_id"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><Polis /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />

        {/* Phase 9.7 W3 — public invitation acceptance page. The email link
            (Phase 9.7 W4) lands here. The page itself dispatches on auth
            state + email match, so it must NOT be wrapped in ProtectedRoute. */}
        <Route path="/invite/:token" element={<InviteAccept />} />

        {/* Public — help pages are purely informational and may be linked from
            external surfaces (Security & Trust, etc.) where the visitor is not
            logged in. Don't gate them on auth. */}
        <Route path="/help/voting-methods" element={<VotingMethodsHelp />} />
        <Route path="/help/sustained-majority" element={<SustainedMajorityHelp />} />
        <Route path="/help/polis" element={<PolisHelp />} />

        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />

        {/* Public marketing routes — no auth required, no Nav/EmailVerificationBanner */}
        <Route path="/" element={<Landing />} />
        <Route path="/about" element={<About />} />
        <Route path="/why" element={<Why />} />
        <Route path="/security" element={<Security />} />
        <Route path="/demo" element={<Demo />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </ConfirmProvider>
      </ToastProvider>
      </PublicConfigProvider>
    </AuthProvider>
  );
}
