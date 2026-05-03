import { Navigate } from 'react-router-dom';
import { useOrg } from './OrgContext';
import { urlFor } from './utils/urls';

export default function AdminOnlyRoute({ children }) {
  const { isAdmin, loading, currentOrg, accessDenied } = useOrg();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  // Phase 11 — accessDenied is handled by OrgScopedLayout's inline message;
  // let the wrapper render so the user sees the explanation rather than a
  // silent /orgs redirect.
  if (accessDenied) {
    return children;
  }

  if (!currentOrg) {
    return <Navigate to="/orgs" replace />;
  }

  if (!isAdmin) {
    return <Navigate to={urlFor(currentOrg, 'proposals')} replace />;
  }

  return children;
}
