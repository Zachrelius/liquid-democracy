import { useNavigate } from 'react-router-dom';
import { useOrg } from '../OrgContext';

export default function OrgSelector() {
  const { userOrgs, setCurrentOrg } = useOrg();
  const navigate = useNavigate();

  function selectOrg(org) {
    setCurrentOrg(org);
    navigate('/proposals');
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-12">
      <h1 className="text-2xl font-semibold text-[#1B3A5C] mb-2">Your Organizations</h1>
      <p className="text-sm text-gray-500 mb-8">Select an organization to continue, or create a new one.</p>

      <div className="grid gap-4 sm:grid-cols-2">
        {userOrgs.map(org => (
          <button
            key={org.id}
            onClick={() => selectOrg(org)}
            className="text-left bg-white border border-gray-200 rounded-xl p-5 hover:border-[#2E75B6] hover:shadow-sm transition-all"
          >
            <h3 className="text-lg font-semibold text-[#1B3A5C] mb-1">{org.name}</h3>
            {org.description && (
              <p className="text-sm text-gray-500 mb-3 line-clamp-2">{org.description}</p>
            )}
            <div className="flex items-center gap-4 text-xs text-gray-400">
              {org.member_count != null && <span>{org.member_count} members</span>}
              {org.user_role && (
                <span className={`px-2 py-0.5 rounded font-medium ${
                  org.user_role === 'owner' ? 'bg-purple-50 text-purple-700' :
                  org.user_role === 'admin' ? 'bg-blue-50 text-blue-700' :
                  'bg-gray-50 text-gray-600'
                }`}>
                  {org.user_role}
                </span>
              )}
            </div>
          </button>
        ))}

        {/* Create New */}
        <button
          onClick={() => navigate('/orgs/create')}
          className="flex items-center justify-center bg-white border-2 border-dashed border-gray-300 rounded-xl p-5 hover:border-[#2E75B6] hover:bg-blue-50/30 transition-all min-h-[120px]"
        >
          <div className="text-center">
            <div className="text-3xl text-gray-300 mb-2">+</div>
            <p className="text-sm font-medium text-gray-500">Create New Organization</p>
          </div>
        </button>
      </div>
    </div>
  );
}
