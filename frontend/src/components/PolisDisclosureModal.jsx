import { Link } from 'react-router-dom';

/**
 * Phase 9 Session 4 — privacy disclosure modal (Decision 4 — load-bearing).
 *
 * Verbatim copy from `phase9_spec.md`:
 *
 *   About this conversation
 *   Your votes and statements here are visible to other participants. They're
 *   tied to a per-org pseudonym, not your name. The platform can identify who
 *   said what if needed for moderation, and your participation is recorded
 *   for cross-session continuity. This is different from voting on proposals,
 *   which stays private by default.
 *   [Got it] [Learn more →]
 *
 * Triggered the first time a viewer opens any given Polis (per-Polis state
 * tracked in `useShouldShowDisclosure`).  "Got it" calls `onDismiss` (which
 * the hook wires to localStorage). "Learn more" routes to /help/polis.
 *
 * Renders nothing when `open` is false.
 */
export default function PolisDisclosureModal({ open, onDismiss }) {
  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="polis-disclosure-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
    >
      <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-6 space-y-4">
        <h2
          id="polis-disclosure-title"
          className="text-lg font-semibold text-[var(--brand-primary)]"
        >
          About this conversation
        </h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Your votes and statements here are visible to other participants.
          They&apos;re tied to a per-org pseudonym, not your name. The platform
          can identify who said what if needed for moderation, and your
          participation is recorded for cross-session continuity. This is
          different from voting on proposals, which stays private by default.
        </p>
        <div className="flex items-center gap-3 pt-2">
          <button
            type="button"
            onClick={onDismiss}
            className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
          >
            Got it
          </button>
          <Link
            to="/help/polis"
            className="text-sm text-[var(--brand-accent)] hover:underline"
          >
            Learn more →
          </Link>
        </div>
      </div>
    </div>
  );
}
