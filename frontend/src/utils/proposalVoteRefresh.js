import { VOTING_METHODS } from './votingMethods.js';

// A hidden preliminary tally must not suppress the voter's own saved ballot.
export async function refreshProposalVote(api, proposalId) {
  const base = `/api/proposals/${proposalId}`;
  const [results, mine, graph] = await Promise.allSettled([
    api.get(`${base}/results`), api.get(`${base}/my-vote`), api.get(`${base}/vote-graph`),
  ]);
  return {
    tally: results.status === 'fulfilled' ? results.value : null,
    myVote: mine.status === 'fulfilled' ? mine.value : null,
    voteGraph: graph.status === 'fulfilled' ? graph.value : null,
    ballotError: mine.status === 'rejected' ? mine.reason : null,
    resultsError: results.status === 'rejected' && results.reason?.status !== 404 ? results.reason : null,
  };
}

export function proposalClosedAt(proposal, tally) {
  if (VOTING_METHODS[proposal.voting_method]?.experimental) {
    return tally?.method_result?.closed_at || null;
  }
  return proposal.voting_end;
}
