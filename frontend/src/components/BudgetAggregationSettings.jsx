import { useId } from 'react';
import { BUDGET_AGGREGATIONS, toggleBudgetAggregation } from '../utils/budgetAggregations';

export function BudgetAggregationHelp() {
  return <details className="text-sm text-gray-700">
    <summary className="cursor-pointer rounded focus-visible:outline-2">How does trimming work?</summary>
    <p className="mt-2">With one vote per member, trim 10% from each end, rounding the number of ballots half up. Fewer than five ballots trim none and use their mean. With share weighting, trim exactly 10% of the positive voting weight at each end, including a fraction of a boundary ballot. Zero-weight ballots do not affect the calculation.</p>
    <p className="mt-2">Category amounts are then adjusted for the envelope and limits. This combined budget procedure does not carry a guarantee that honest suggestions are always the best strategy.</p>
  </details>;
}
export default function BudgetAggregationSettings({ choices, onChange, editable = true, permitted }) {
  const prefix = useId();
  return <fieldset className="space-y-3">
    <legend className="text-sm font-medium">Budget allocation aggregation choices</legend>
    <p className="text-sm text-gray-700">Choose at least one rule proposal creators may use.</p>
    {Object.entries(BUDGET_AGGREGATIONS).map(([key, text]) => {
      const locked = !editable || (permitted && !permitted.includes(key));
      return <div key={key} className="flex items-start gap-3">
        <input id={`${prefix}-${key}`} type="checkbox" checked={choices.includes(key)} disabled={!!locked}
          aria-describedby={`${prefix}-${key}-description`} className="mt-1 shrink-0"
          onChange={e => onChange(toggleBudgetAggregation(choices, key, e.target.checked))} />
        <div><label htmlFor={`${prefix}-${key}`} className="text-sm font-medium">{text.label}</label>
          <p id={`${prefix}-${key}-description`} className="text-sm text-gray-700">{text.description}</p>
          {permitted && !permitted.includes(key) && <p className="text-xs text-gray-600">Restricted by parent organization</p>}
        </div>
      </div>;
    })}
    {!choices.length && <p role="alert" className="text-sm text-red-700">Select at least one aggregation before saving.</p>}
    <BudgetAggregationHelp />
  </fieldset>;
}

export function BudgetAggregationSelector({ choices, value, onChange, grandfathered = false }) {
  const id = useId();
  const unavailable = !choices.includes(value);
  return <div className="space-y-1">
    <label htmlFor={id} className="block text-xs text-gray-600">Aggregation</label>
    {choices.length === 1 && !unavailable ? <p id={id} className="text-sm font-medium">{BUDGET_AGGREGATIONS[value].label}</p> :
      <select id={id} value={value} onChange={e => onChange(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm">
        {unavailable && <option value={value} disabled>{BUDGET_AGGREGATIONS[value]?.label || value}{grandfathered ? ' (existing rule retained)' : ' (choose a permitted rule)'}</option>}
        {choices.map(key => <option key={key} value={key}>{BUDGET_AGGREGATIONS[key].label}</option>)}
      </select>}
    <p className="text-sm text-gray-700">{BUDGET_AGGREGATIONS[value]?.description}</p>
    {unavailable && grandfathered && <p className="text-xs text-gray-600">This existing draft may retain its aggregation. A different choice must follow the current organization rules.</p>}
    <BudgetAggregationHelp />
  </div>;
}
