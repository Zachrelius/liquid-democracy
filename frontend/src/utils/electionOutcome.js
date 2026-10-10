export function experimentalElectionSummary(outcome) {
  if (Number(outcome.outcome_version) === 2) {
    const selected = new Set(outcome.winner_user_ids || []);
    const people = Object.values(outcome.candidate_snapshot || {}).filter(row => selected.has(row.user_id)).map(row => row.display_name).join(', ');
    if (outcome.installation === 'installed') return `${outcome.policy === 'uncontested' ? 'Uncontested election' : 'Elected'}: ${people}. ${outcome.selected_count} of ${outcome.requested_count} places filled. Office installation completed.`;
    if (outcome.installation === 'pending_verification') return `Selected: ${people}. The entire set awaits verification; no new office or bound-role access was granted.`;
    if (outcome.installation === 'rejected') return `Selected: ${people}. The entire set could not be installed (${outcome.reason}); existing seats and roles were preserved.`;
    return `No officeholders installed (${outcome.reason || 'pending'}); existing seats and roles were preserved.`;
  }
  const names = Object.values(outcome.candidate_snapshot || {});
  const name = names.find(candidate => candidate.user_id === outcome.winner_user_id)?.display_name || 'The recorded winner';
  if (outcome.installation === 'installed') return `${outcome.policy === 'uncontested' ? 'Uncontested election: ' : 'Elected: '}${name}. Office installation completed.`;
  if (outcome.installation === 'pending_verification') return `${name} won, but office installation is pending verification. No bound-role access was granted.`;
  if (outcome.installation === 'rejected') return `${name} won, but could not be installed (${outcome.reason}). Existing seats and roles were preserved.`;
  if (outcome.reason === 'quorum_not_met') return 'Quorum not met — no seats were changed.';
  if (outcome.reason === 'no_candidates') return 'This election closed with no candidates — no seats were changed.';
  const reasons = {
    no_positive_weight_preferences: 'No positive-weight, non-abstaining preferences were submitted.',
    all_bottom_ratings: 'Every candidate received only bottom ratings.',
    no_strict_preferences: 'No ballot expressed a strict preference between candidates.',
  };
  return reasons[outcome.reason] ? `${reasons[outcome.reason]} No officeholder was installed.`
    : `This election closed without installing an officeholder (${outcome.reason || 'installation pending'}).`;
}
