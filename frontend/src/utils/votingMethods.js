// Availability is a release gate, not an organization preference. Complete and
// verify each method's ballot/result/lifecycle slice before changing it to true.
const legacy = (label, ballotField, options = true) => Object.freeze({
  label, ballotField, options, experimental: false, available: true,
});
const experimental = (label, ballotField, ruleId, omission) => Object.freeze({
  label, ballotField, ruleId, omission, options: true,
  experimental: true, available: false, singleWinner: true,
});

export const VOTING_METHODS = Object.freeze({
  binary: legacy('Yes / No', 'vote_value', false),
  approval: legacy('Approval', 'approvals'),
  ranked_choice: legacy('Ranked choice', 'ranking'),
  budget_allocation: legacy('Budget allocation', 'allocations'),
  budget_project: legacy('Ranked projects', 'ranked'),
  allocated_score: Object.freeze({ ...experimental('Allocated Score', 'scores', 'allocated_score_0_5_hare_v1', 'Unrated options receive 0 points.'), available: true, singleWinner: false, minimumWinners: 2 }),
  star: Object.freeze({ ...experimental('STAR', 'scores', 'star_0_5_v1', 'Unrated options receive 0 stars.'), available: true }),
  score: Object.freeze({ ...experimental('Score', 'scores', 'score_0_5_sum_v1', 'Unrated options receive 0 points.'), available: true }),
  ranked_pairs: Object.freeze({ ...experimental('Ranked Pairs', 'rank_groups', 'ranked_pairs_margins_v1',
    'Unranked options tie below every ranked option.'), available: true }),
  majority_judgment: Object.freeze({ ...experimental('Majority Judgment', 'grades', 'majority_judgment_lower_median_v1',
    'Ungraded options receive Reject.'), available: true }),
});

// Existing UI fallback is binary only. Never derive defaults from this registry.
export const FALLBACK_ENABLED_METHODS = Object.freeze(['binary']);
export const MAJORITY_JUDGMENT_GRADES = Object.freeze([
  'Reject', 'Poor', 'Acceptable', 'Good', 'Very good', 'Excellent',
]);

export function votingMethodLabel(method) {
  return VOTING_METHODS[method]?.label || method?.replaceAll('_', ' ') || 'Vote';
}

/** orgSettings must already be the server's effective (inherited) settings. */
export function selectableVotingMethods(orgSettings, { hasOrg = false, election = false, numWinners = 1 } = {}) {
  const allowed = Array.isArray(orgSettings?.allowed_voting_methods)
    ? orgSettings.allowed_voting_methods : FALLBACK_ENABLED_METHODS;
  return Object.entries(VOTING_METHODS)
    .filter(([id, method]) => method.available && allowed.includes(id) && numWinners >= (method.minimumWinners || 1)
      && (!method.experimental || (hasOrg && (id === 'allocated_score' || numWinners === 1 || (orgSettings?.allowed_multiwinner_methods || []).includes(id))))
      && (!election || !['budget_allocation', 'budget_project'].includes(id)))
    .map(([id]) => id);
}

/** Only modify the chosen method; preserve unrelated/unknown stored choices. */
export function toggleAllowedVotingMethod(allowed, method, enabled) {
  const current = Array.isArray(allowed) ? allowed : FALLBACK_ENABLED_METHODS;
  const capability = VOTING_METHODS[method];
  if (!capability?.available || method === 'binary') return [...current];
  return enabled ? [...new Set([...current, method])] : current.filter(id => id !== method);
}

export function draftMethodResetFields(previous, next, confirmed) {
  if (!previous || previous === next
    || !(VOTING_METHODS[previous]?.experimental || VOTING_METHODS[next]?.experimental)) return {};
  if (!confirmed) throw new Error('Confirm the voting-method change before discarding preliminary ballots.');
  return { confirm_ballot_reset: true };
}

export function unchangedOptionText(existing = [], edited = []) {
  return existing.length === edited.length && existing.every((option, index) =>
    (option.label || '').trim() === (edited[index].label || '').trim()
    && (option.description || '').trim() === (edited[index].description || '').trim());
}

export function experimentalOptionsLocked(proposal, methodResult) {
  return !!VOTING_METHODS[proposal.voting_method]?.experimental
    && (proposal.is_election || methodResult?.finalized === true
      || ['passed', 'failed', 'closed', 'withdrawn', 'unresolved'].includes(proposal.status));
}

// Inherited/locked views cannot mutate even if called outside the native input.
export function changedMethodSettings(allowed, method, enabled, editable) {
  return toggleAllowedVotingMethod(allowed, editable ? method : 'binary', enabled);
}

export const MULTIWINNER_COPY = Object.freeze({
  ranked_pairs: "Compare options head to head and build a collective ranking, honoring the strongest victories without creating a cycle. Select the highest-ranked options. Votes are not redistributed between winners; this does not provide proportional representation.",
  majority_judgment: "Grade each option from Reject to Excellent. Select the options highest in the majority-grade ranking, using the same grade-based tie rules. Each option is judged by the full electorate; this does not provide proportional representation.",
  star: "Select each winner using STAR's scoring and automatic runoff. Remove that winner and repeat for the remaining places. Every ballot retains its full weight in every round; this does not provide proportional representation.",
  score: 'Rate each option from 0 to 5. The options with the highest total scores win. Every ballot counts at full weight toward every selection; this does not provide proportional representation.',
});

export const ALLOCATED_SCORE_COPY = 'Rate options from 0 to 5. Winners are selected in rounds by score. After each selection, a share of voting influence is allocated to that winner, giving voters who are not yet represented more influence over the remaining places. No automatic runoff.';

export function countingDescription(method) {
  return method === 'allocated_score' ? ALLOCATED_SCORE_COPY : MULTIWINNER_COPY[method];
}

export function multiwinnerEnabled(capabilities, method) {
  if (method === 'allocated_score') return VOTING_METHODS.allocated_score.available && (capabilities?.allowed_voting_methods || []).includes(method);
  return Object.hasOwn(MULTIWINNER_COPY, method) && (capabilities?.allowed_multiwinner_methods || []).includes(method);
}

export function draftWinnerCountResetFields(previous, next, experimental, confirmed) {
  if (!experimental || previous == null || Number(previous) === Number(next)) return {};
  if (!confirmed) throw new Error('Confirm the winner-count change before discarding preliminary ballots.');
  return { confirm_ballot_reset: true };
}
