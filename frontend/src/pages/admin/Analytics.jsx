import { useState, useEffect } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';

const COLORS = ['#2E75B6', '#1B3A5C', '#64748b', '#94a3b8'];

function MetricCard({ label, value, sub }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 text-center">
      <p className="text-3xl font-bold text-[#1B3A5C]">{value}</p>
      <p className="text-sm text-gray-500 mt-1">{label}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function Analytics() {
  const { currentOrg } = useOrg();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const slug = currentOrg?.slug;

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    api.get(`/api/orgs/${slug}/analytics`)
      .then(setData)
      .catch(e => setError(e.message || 'Failed to load analytics'))
      .finally(() => setLoading(false));
  }, [slug]);

  if (!currentOrg) return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );
  if (error) return <div className="max-w-3xl mx-auto px-4 py-8"><div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg">{error}</div></div>;
  if (!data) return null;

  const { participation_rates, delegation_patterns, proposal_outcomes, active_members } = data;

  // Prepare participation chart data
  const participationData = participation_rates.map(p => ({
    name: p.title.length > 20 ? p.title.slice(0, 20) + '...' : p.title,
    rate: Math.round(p.participation_rate * 100),
    votes: p.vote_count,
  }));

  // Prepare delegation pie data
  const delegating = delegation_patterns.members_delegating || 0;
  const directOnly = (delegation_patterns.total_members || 0) - delegating;
  const delegationData = [
    { name: 'Direct voters', value: Math.max(0, directOnly) },
    { name: 'Delegating', value: delegating },
  ].filter(d => d.value > 0);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      <h1 className="text-2xl font-semibold text-[#1B3A5C]">Analytics</h1>

      {/* Proposal Outcomes Summary */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Proposal Outcomes</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <MetricCard label="Total Proposals" value={proposal_outcomes.total || 0} />
          <MetricCard
            label="Pass Rate"
            value={proposal_outcomes.pass_rate != null ? `${Math.round(proposal_outcomes.pass_rate * 100)}%` : 'N/A'}
          />
          <MetricCard label="Passed" value={proposal_outcomes.passed || 0} />
          <MetricCard label="Failed" value={proposal_outcomes.failed || 0} />
        </div>
      </section>

      {/* Active Members */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Members</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <MetricCard label="Total Members" value={active_members.total || 0} />
          <MetricCard
            label="Delegation Rate"
            value={delegation_patterns.delegation_rate != null ? `${Math.round(delegation_patterns.delegation_rate * 100)}%` : 'N/A'}
            sub={`${delegating} members delegating`}
          />
          <MetricCard
            label="Currently Voting"
            value={proposal_outcomes.voting || 0}
            sub="Active proposals"
          />
        </div>
      </section>

      {/* Participation Rate Chart */}
      {participationData.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Participation Rate by Proposal</h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={participationData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="%" domain={[0, 100]} />
                <Tooltip
                  formatter={(value) => [`${value}%`, 'Participation']}
                  contentStyle={{ fontSize: 12 }}
                />
                <Bar dataKey="rate" fill="#2E75B6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* Delegation Patterns Pie */}
      {delegationData.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Delegation Patterns</h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 flex justify-center">
            <ResponsiveContainer width={350} height={250}>
              <PieChart>
                <Pie
                  data={delegationData}
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  dataKey="value"
                  label={({ name, value }) => `${name}: ${value}`}
                  labelLine={false}
                >
                  {delegationData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Legend />
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
    </div>
  );
}
