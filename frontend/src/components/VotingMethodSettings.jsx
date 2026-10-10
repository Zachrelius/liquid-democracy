import { useId } from 'react';
import { VOTING_METHODS, changedMethodSettings } from '../utils/votingMethods';
import { VOTING_METHOD_DESCRIPTIONS, METHOD_AVAILABILITY_FOOTER, SINGLE_WINNER_ELIGIBILITY } from '../utils/votingMethodDescriptions';

export function MajorityJudgmentExplanation() {
  return <details className="text-sm text-gray-700 leading-relaxed">
    <summary className="cursor-pointer font-medium rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-accent)]">How are grades counted?</summary>
    <div className="mt-2 space-y-3">
      <p>Imagine an option receives these five grades: Reject, Acceptable, <strong>Good</strong>, Very good, Excellent. Its middle grade is <strong>Good</strong>. With an even number of grades, the lower of the two middle grades is used.</p>
      <p>When options tie, the system temporarily removes one middle grade from each tied option and compares their new middle grades, repeating as needed. The original ballots remain unchanged. If the grades still cannot distinguish the options, the recorded tie-breaking order decides the result.</p>
      <p><strong>Why words instead of numbers?</strong> These labels express how you judge each option. Their order matters, but they aren’t points to add or average. Majority Judgment compares middle grades; Score and STAR add numerical ratings.</p>
    </div>
  </details>;
}

export default function VotingMethodSettings({ allowed, editable = true, onChange }) {
  const prefix = useId();
  return <div className="space-y-4">
    {Object.entries(VOTING_METHOD_DESCRIPTIONS).filter(([method]) => VOTING_METHODS[method].available).map(([method, text]) => {
      const inputId = `${prefix}-${method}`;
      const descriptionId = `${inputId}-description`;
      const locked = !editable || method === 'binary';
      return <div key={method} className="flex items-start gap-3">
        <input id={inputId} type="checkbox" checked={method === 'binary' || (allowed || ['binary']).includes(method)}
          disabled={locked} aria-describedby={descriptionId}
          onChange={e => { if (!locked) onChange(changedMethodSettings(allowed, method, e.target.checked, editable)); }}
          className="mt-1 shrink-0 accent-[var(--brand-accent)]" />
        <div className="min-w-0 space-y-1">
          <label htmlFor={inputId} className={`text-sm font-medium text-gray-800 ${locked ? '' : 'cursor-pointer'}`}>{text.name}</label>
          <p id={descriptionId} className="text-sm text-gray-700 leading-relaxed">{text.description}</p>
          {method === 'majority_judgment' && <MajorityJudgmentExplanation />}
        </div>
      </div>;
    })}
    <p className="text-sm text-gray-700">{METHOD_AVAILABILITY_FOOTER}</p>
    <p className="text-sm text-gray-700">{SINGLE_WINNER_ELIGIBILITY}</p>
    <a href="/help/voting-methods" target="_blank" rel="noreferrer" className="inline-block text-sm text-[var(--brand-accent)] underline">Learn about voting methods</a>
  </div>;
}
