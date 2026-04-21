import { Navigate } from 'react-router-dom';
import { useOrg } from './OrgContext';

export default function AdminRoute({ children }) {
  const { isModeratorOrAdmin, loading, currentOrg } = useOrg();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  if (!currentOrg) {
    return <Navigate to="/orgs" replace />;
  }

  if (!isModeratorOrAdmin) {
    return <Navigate to="/proposals" replace />;
  }

  return children;
}
