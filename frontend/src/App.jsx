import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './AuthContext';
import { OrgProvider } from './OrgContext';
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
import OrgSelector from './pages/OrgSelector';
import CreateOrg from './pages/CreateOrg';
import SetupWizard from './pages/SetupWizard';
import OrgSettings from './pages/admin/OrgSettings';
import Members from './pages/admin/Members';
import ProposalManagement from './pages/admin/ProposalManagement';
import Topics from './pages/admin/Topics';
import DelegateApplications from './pages/admin/DelegateApplications';
import Analytics from './pages/admin/Analytics';
import VotingMethodsHelp from './pages/VotingMethodsHelp';
import Privacy from './pages/Privacy';
import Terms from './pages/Terms';
import Landing from './pages/Landing';
import About from './pages/About';
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

        <Route
          path="/help/voting-methods"
          element={
            <ProtectedRoute>
              <OrgProvider>
                <Layout><VotingMethodsHelp /></Layout>
              </OrgProvider>
            </ProtectedRoute>
          }
        />

        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />

        {/* Public marketing routes — no auth required, no Nav/EmailVerificationBanner */}
        <Route path="/" element={<Landing />} />
        <Route path="/about" element={<About />} />
        <Route path="/demo" element={<Demo />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </ConfirmProvider>
      </ToastProvider>
    </AuthProvider>
  );
}
