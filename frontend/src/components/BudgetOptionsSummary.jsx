import { optionDisplayLabel } from '../utils/optionDisplay';
import { formatBudget } from '../utils/budgetFormat';

/**
 * BudgetOptionsSummary — main-view catalog of a budget proposal's buckets /
 * projects (Phase 76a).
 *
 * Mirrors the Options section that approval / ranked-choice proposals show in
 * the main column, so a budget proposal's options aren't only visible (and
 * truncated) inside the sidebar ballot. Read-only: costs and ceilings come
 * straight off the option rows, formatted with the proposal's configured unit.
 *
 *  - allocation: flat buckets, each with an optional per-bucket ceiling.
 *  - project: ranked projects with a fixed cost; tier-parent items expand to
 *    their priced variants.
 */
export default function BudgetOptionsSummary({ proposal }) {
  const cfg = proposal.budget_config || {};
  const unit = cfg.currency;
  const options = proposal.options || [];
  if (options.length === 0) return null;

  const isProject = proposal.voting_method === 'budget_project';

  if (!isProject) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Budget Options</h3>
        <div className="space-y-2">
          {options.map((o, idx) => (
            <div key={o.id} className="flex items-start gap-3 p-2 bg-gray-50 rounded-lg">
              <span className="text-xs text-gray-400 mt-0.5">{idx + 1}.</span>
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium text-gray-800">{optionDisplayLabel(proposal, o)}</span>
                {o.description && <p className="text-xs text-gray-500 mt-0.5">{o.description}</p>}
              </div>
              {o.budget_max_amount != null && (
                <span className="text-xs text-gray-500 shrink-0 tabular-nums mt-0.5">
                  Ceiling: {formatBudget(o.budget_max_amount, unit)}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Project mode — fold tier children under their parents.
  const children = {};
  options.forEach((o) => {
    if (o.budget_tier_parent_id) {
      (children[o.budget_tier_parent_id] ||= []).push(o);
    }
  });
  const top = options.filter((o) => !o.budget_tier_parent_id);
  const costOf = (o) => (
    o.budget_kind === 'continuous-as-discrete' && o.budget_max_amount != null
      ? o.budget_max_amount
      : o.budget_floor_amount
  );

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Projects</h3>
      <div className="space-y-2">
        {top.map((o, idx) => {
          const isParent = o.budget_kind === 'tier_parent';
          const kids = (children[o.id] || []).slice()
            .sort((a, b) => (a.budget_floor_amount || 0) - (b.budget_floor_amount || 0));
          return (
            <div key={o.id} className="p-2 bg-gray-50 rounded-lg">
              <div className="flex items-start gap-3">
                <span className="text-xs text-gray-400 mt-0.5">{idx + 1}.</span>
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-gray-800">{optionDisplayLabel(proposal, o)}</span>
                  {o.description && <p className="text-xs text-gray-500 mt-0.5">{o.description}</p>}
                  {isParent && kids.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {kids.map((k) => (
                        <li key={k.id} className="text-xs text-gray-600 flex justify-between gap-2">
                          <span className="truncate">— {optionDisplayLabel(proposal, k)}</span>
                          <span className="tabular-nums shrink-0">{formatBudget(k.budget_floor_amount, unit)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                {!isParent && (
                  <span className="text-xs font-medium text-gray-700 shrink-0 tabular-nums mt-0.5">
                    {formatBudget(costOf(o), unit)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
