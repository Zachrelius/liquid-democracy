export const STANDARD_PROPOSAL_IMPORT_MAX = 10;
export const HIGH_VOLUME_PROPOSAL_IMPORT_MAX = 10000;

export function proposalImportSelectionState(selectedCount, highVolumeEnabled) {
  const blocked = !highVolumeEnabled && selectedCount > STANDARD_PROPOSAL_IMPORT_MAX;
  return {
    blocked,
    note: highVolumeEnabled
      ? 'High-volume proposal creation is enabled for your role.'
      : '',
    guidance: blocked
      ? 'Standard accounts can create at most 10 proposals in a 24-hour window. Select no more than ten, or ask an organization administrator to enable High-volume proposal creation for your role.'
      : '',
  };
}

export function proposalImportRateLimitMessage(
  highVolumeEnabled,
  created,
  remaining,
) {
  const safeCreated = Math.max(0, Number(created) || 0);
  const safeRemaining = Math.max(0, Number(remaining) || 0);
  const tier = highVolumeEnabled
    ? 'The high-volume safety limit is 10,000 proposals per 24-hour window.'
    : 'The standard limit is 10 proposals per 24-hour window.';
  return `${tier} ${safeCreated} ${safeCreated === 1 ? 'draft is' : 'drafts are'} safely created. ${safeRemaining} checked ${safeRemaining === 1 ? 'row remains' : 'rows remain'} available to retry later.`;
}

/**
 * Run the existing single-create request one row at a time. A failure stops
 * immediately; callers retain already-created rows and can retry the rest.
 */
export async function createProposalRowsSequentially(
  rows,
  createProposal,
  {
    highVolumeEnabled = false,
    onProgress = () => {},
    onCreated = () => {},
    onFailed = () => {},
  } = {},
) {
  if (!highVolumeEnabled && rows.length > STANDARD_PROPOSAL_IMPORT_MAX) {
    return {
      blocked: true, created: 0, remaining: rows.length, error: null,
      failedRow: null,
    };
  }

  let created = 0;
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    onProgress(index + 1, rows.length);
    try {
      await createProposal(row);
      created += 1;
      onCreated(row);
    } catch (error) {
      onFailed(row, error);
      return {
        blocked: false,
        created,
        remaining: rows.length - created,
        error,
        failedRow: row,
      };
    }
  }
  return {
    blocked: false, created, remaining: 0, error: null, failedRow: null,
  };
}
