import { useState, useRef, useLayoutEffect } from 'react';

/**
 * OptionCardDescription — Phase 72b shared ballot-option description block.
 *
 * In the narrow ProposalDetail "Your Ballot" sidebar (~250px), a full
 * multi-paragraph option description blows a single ballot card up to a dozen
 * wrapped lines, pushing the next option far down the page. This clamps the
 * description to 3 lines by default with a touch-friendly "Show more" / "Show
 * less" toggle.
 *
 * Deliberately NOT a hover tooltip — this is a civic app with mobile voters, so
 * the affordance must work on tap. The full text is always reachable in place;
 * it just collapses by default so the option list stays scannable. The toggle
 * only renders when the text actually overflows the clamp (short descriptions
 * show no affordance).
 *
 * Shared by RankedBallot.jsx (RCV) and the approval ballot list in
 * ProposalDetail.jsx so the two presentations don't drift. Presentation only —
 * no tally/vote/drag behavior here.
 */
export default function OptionCardDescription({ text, className = '' }) {
  const [expanded, setExpanded] = useState(false);
  const [clampable, setClampable] = useState(false);
  const ref = useRef(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Measured while clamped: overflow means there is more text to reveal.
    setClampable(el.scrollHeight > el.clientHeight + 1);
  }, [text]);

  if (!text) return null;

  return (
    <div className={className}>
      <p
        ref={ref}
        className={`text-xs text-gray-500 leading-snug ${expanded ? '' : 'line-clamp-3'}`}
      >
        {text}
      </p>
      {(clampable || expanded) && (
        <button
          type="button"
          onClick={(e) => {
            // Stop the click from toggling a parent checkbox / starting a drag.
            e.stopPropagation();
            e.preventDefault();
            setExpanded((v) => !v);
          }}
          className="text-[11px] font-medium text-[var(--brand-accent)] hover:underline mt-0.5"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
}
