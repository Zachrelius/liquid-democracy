/**
 * Phase 8.5 — friendly inline error for sub-org admin pages.
 * Backend 403/404 (lack of permission, missing sub-org) all funnel here.
 */
export default function SubOrgErrorState({ error }) {
  const status = error?.status;
  const heading = status === 404
    ? 'Sub-organization not found'
    : status === 403
      ? 'You do not have access'
      : 'Something went wrong';
  const detail = status === 404
    ? 'This sub-organization does not exist, or your account does not have visibility into it.'
    : status === 403
      ? 'You need to be a sub-org admin (or parent-org admin) to manage this sub-organization.'
      : (error?.message || 'Please try again.');
  return (
    <div className="max-w-2xl mx-auto px-4 py-16 text-center">
      <h1 className="text-xl font-semibold text-[var(--brand-primary)] mb-3">{heading}</h1>
      <p className="text-sm text-gray-600 mb-4">{detail}</p>
      <a href="/proposals" className="text-sm text-[var(--brand-accent)] hover:underline">Back to proposals</a>
    </div>
  );
}
