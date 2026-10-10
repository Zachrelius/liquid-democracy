export const BUDGET_AGGREGATIONS = Object.freeze({
  median: { label: 'Median (recommended)', description: 'Use the middle suggested amount for each category, then adjust the combined amounts to fit the budget and category limits.' },
  trimmed_mean: { label: 'Trimmed mean', description: 'Average suggested amounts after trimming the highest and lowest portions, then adjust the combined amounts to fit the budget and category limits.' },
});
export const LEGACY_BUDGET_AGGREGATIONS = Object.freeze(['median', 'trimmed_mean']);
export function budgetAggregationChoices(capabilities, settings) {
  return capabilities?.allowed_budget_aggregations ?? settings?.allowed_budget_aggregations ?? LEGACY_BUDGET_AGGREGATIONS;
}
export function chosenBudgetAggregation(value, choices) { return value || choices[0]; }
export function toggleBudgetAggregation(choices, key, checked) {
  if (!Object.hasOwn(BUDGET_AGGREGATIONS, key)) return [...choices];
  return checked ? [...new Set([...choices, key])] : choices.filter(v => v !== key);
}
