export const BULK_ADVANCE_CHUNK_SIZE = 500;

export function visibleDraftProposalIds(proposals) {
  return (proposals || [])
    .filter(proposal => proposal.status === 'draft')
    .map(proposal => proposal.id);
}

export function proposalEligibleForBulkOperation(proposal, operation) {
  if (!proposal || !operation) return false;
  if (operation === 'draft_to_deliberation') return proposal.status === 'draft';
  if (operation === 'deliberation_to_voting' || operation === 'schedule_start') {
    return proposal.status === 'deliberation' && !proposal.is_cosign_gated;
  }
  if (operation === 'set_end') {
    return ['deliberation', 'voting'].includes(proposal.status)
      && !proposal.is_cosign_gated;
  }
  return false;
}

export function visibleEligibleProposalIds(proposals, operation) {
  return (proposals || [])
    .filter(proposal => proposalEligibleForBulkOperation(proposal, operation))
    .map(proposal => proposal.id);
}

export function chunkProposalIds(ids, size = BULK_ADVANCE_CHUNK_SIZE) {
  const uniqueSorted = [...new Set(ids || [])].sort((left, right) => left.localeCompare(right));
  const chunks = [];
  for (let index = 0; index < uniqueSorted.length; index += size) {
    chunks.push(uniqueSorted.slice(index, index + size));
  }
  return chunks;
}

export function aggregateBulkAdvanceResponses(responses) {
  return (responses || []).reduce(
    (summary, response) => ({
      advanced: summary.advanced + (response.advanced || 0),
      alreadyInDeliberation:
        summary.alreadyInDeliberation + (response.already_in_deliberation || 0),
      couldNotAdvance:
        summary.couldNotAdvance
        + (response.ineligible_status || 0)
        + (response.not_found || 0),
      results: summary.results.concat(response.results || []),
    }),
    { advanced: 0, alreadyInDeliberation: 0, couldNotAdvance: 0, results: [] },
  );
}

export function bulkAdvanceSummaryMessage(summary) {
  return [
    `${summary.advanced} advanced`,
    `${summary.alreadyInDeliberation} ${summary.alreadyInDeliberation === 1 ? 'was' : 'were'} already in deliberation`,
    `${summary.couldNotAdvance} could not be advanced`,
  ].join('; ') + '.';
}
