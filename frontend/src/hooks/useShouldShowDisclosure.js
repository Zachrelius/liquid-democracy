import { useCallback, useState } from 'react';

/**
 * Phase 9 Session 4 — per-Polis privacy disclosure hook (Decision 4).
 *
 * Tracks dismissal state in localStorage keyed by polis_id, NOT user_id.
 * Different Polises must independently surface the disclosure even if the
 * viewer has dismissed it on another conversation — each Polis's privacy
 * considerations are conceptually fresh.
 *
 * Returns `[shouldShow, dismiss]`:
 *   - `shouldShow` is `true` after the storage check completes if no
 *     `polis_disclosed_<polis_id>` key is set; `false` while we're still
 *     reading storage so the modal doesn't pop and immediately disappear
 *     for users who already dismissed it.
 *   - `dismiss()` writes `polis_disclosed_<polis_id> = "true"` and flips
 *     `shouldShow` to `false`.
 *
 * SSR/private-mode safety: any localStorage access is guarded so we don't
 * crash if storage throws (Safari's lockdown mode, embed contexts, etc.).
 */

const STORAGE_PREFIX = 'polis_disclosed_';

function readDismissed(polisId) {
  if (!polisId) return true;
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + polisId) === 'true';
  } catch {
    // localStorage unavailable — treat as "not dismissed" so the user
    // sees the disclosure at least once per session.
    return false;
  }
}

export default function useShouldShowDisclosure(polisId) {
  // Lazy-init from localStorage on first render and on every render where
  // polisId changes — using the "derive from props during render" pattern
  // recommended by react.dev's set-state-in-effect docs. We track the last
  // polisId we synced against in state; when it doesn't match, we recompute
  // dismissed-state from storage *during render* rather than in an effect.
  const [activePolisId, setActivePolisId] = useState(polisId);
  const [dismissedState, setDismissedState] = useState(() => readDismissed(polisId));

  if (polisId !== activePolisId) {
    setActivePolisId(polisId);
    setDismissedState(readDismissed(polisId));
  }

  const dismiss = useCallback(() => {
    if (!polisId) return;
    try {
      window.localStorage.setItem(STORAGE_PREFIX + polisId, 'true');
    } catch {
      // Best-effort.
    }
    setDismissedState(true);
  }, [polisId]);

  return [!dismissedState && !!polisId, dismiss];
}
