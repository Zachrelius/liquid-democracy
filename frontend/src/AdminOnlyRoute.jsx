import { Navigate } from 'react-router-dom';
import { useOrg } from './OrgContext';

export default function AdminOnlyRoute({ children }) {
  const { isAdmin, loading, currentOrg } = useOrg();

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

  if (!isAdmin) {
    return <Navigate to="/proposals" replace />;
  }

  return children;
}
