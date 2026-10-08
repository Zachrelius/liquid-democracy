export function assignmentsFromGroups(groups = []) {
  return Object.fromEntries(groups.flatMap((group, index) => group.map(id => [id, index + 1])));
}

export function rankGroupsPayload(assignments, optionIds, abstain = false) {
  if (abstain) return { abstain: true };
  const allowed = new Set(optionIds);
  const ranks = new Map();
  for (const [id, rank] of Object.entries(assignments)) {
    if (!allowed.has(id)) throw new Error('An option was removed. Cancel and reopen your ballot.');
    if (rank == null) continue;
    if (!Number.isInteger(rank) || rank < 1 || rank > optionIds.length) throw new Error('Choose a valid rank group or leave the option unranked.');
    if (!ranks.has(rank)) ranks.set(rank, []);
    ranks.get(rank).push(id);
  }
  return { rank_groups: [...ranks.keys()].sort((a, b) => a - b).map(rank => ranks.get(rank)) };
}

export function hasRankGroupsBallot(vote) {
  return Array.isArray(vote?.rank_groups) || vote?.abstain === true;
}
