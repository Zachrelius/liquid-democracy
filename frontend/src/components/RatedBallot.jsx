import { useId, useRef, useState } from 'react';
import api from '../api';
import { useToast } from './Toast';
import VerifyEmailInlineNote from './VerifyEmailInlineNote';
import UserLink from './UserLink';
import OptionCardDescription from './OptionCardDescription';
import { hasRatedBallot, ratedPayload } from '../utils/ratedBallot';

export default function RatedBallot({ proposal, proposalId, myVote, onVoteChange, emailVerified }) {
  const [scores, setScores] = useState({});
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const id = useId();
  const formRef = useRef(null);
  const changeRef = useRef(null);
  const toast = useToast();
  const options = proposal.options || [];
  const hasVote = hasRatedBallot(myVote);
  const disabled = busy || !emailVerified;

  function open() {
    setScores(myVote?.is_direct ? { ...(myVote.scores || {}) } : {});
    setError('');
    setEditing(true);
    requestAnimationFrame(() => formRef.current?.querySelector('input')?.focus());
  }
  function cancel() {
    setEditing(false);
    changeRef.current?.focus();
  }
  async function submit(abstain = false) {
    setBusy(true);
    setError('');
    try {
      await api.post(`/api/proposals/${proposalId}/vote`, ratedPayload(scores, options.map(o => o.id), abstain));
      setEditing(false);
      toast.success(abstain ? 'Abstention recorded' : 'Ballot submitted');
      await onVoteChange();
      changeRef.current?.focus();
    } catch (e) { setError(e.message || 'Unable to submit ballot'); }
    finally { setBusy(false); }
  }
  async function retract() {
    setBusy(true);
    setError('');
    try {
      await api.delete(`/api/proposals/${proposalId}/vote`);
      toast.success('Ballot retracted; your delegation can apply again');
      await onVoteChange();
    } catch (e) { setError(e.message || 'Unable to retract ballot'); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3" aria-label="Your STAR ballot">
    <h3 className="text-sm font-semibold">Your STAR ballot</h3>
    <p id={`${id}-instructions`} className="text-sm text-gray-600">Rate each option from 0 to 5 stars. Equal ratings are allowed. The two highest total scores reach a runoff; your ballot supports whichever finalist you rated higher.</p>
    <p className="text-xs text-gray-600">Unrated options receive 0 stars, including write-ins added after you vote. You may change your ballot while voting is permitted. Selecting stars does not submit your vote.</p>
    {!emailVerified && <VerifyEmailInlineNote action="vote" />}
    {!editing && <>
      {hasVote ? <div className="text-sm">
        <p>{myVote.is_direct ? 'Your submitted ballot' : <>Via {myVote.cast_by ? <UserLink user={myVote.cast_by} /> : 'delegate'}</>}</p>
        {myVote.abstain ? <p>You abstained. This overrides delegation and contributes no ratings.</p> : <>
          <ul className="space-y-1 mt-2">{options.map(o => <li key={o.id}>{o.label}: <strong>{myVote.scores?.[o.id] ?? 0}/5</strong>{!Object.hasOwn(myVote.scores || {}, o.id) && ' (unrated)'}</li>)}</ul>
          {options.some(o => !Object.hasOwn(myVote.scores || {}, o.id)) && <p className="mt-2 text-xs text-amber-800">Options absent from this ballot—including any added later—receive zero until you change your ballot.</p>}
        </>}
      </div> : <p className="text-sm text-gray-500">{myVote?.message || 'No ballot cast.'}</p>}
      <div className="flex flex-wrap gap-2">
        <button ref={changeRef} type="button" onClick={open} disabled={disabled} className="px-3 py-2 border rounded-lg text-sm disabled:opacity-50">{hasVote ? myVote.is_direct ? 'Change ballot' : 'Override — vote directly' : 'Cast ballot'}</button>
        {hasVote && myVote.is_direct && <button type="button" onClick={retract} disabled={disabled} className="px-3 py-2 border rounded-lg text-sm disabled:opacity-50">Retract</button>}
      </div>
    </>}
    {editing && <form ref={formRef} onSubmit={e => { e.preventDefault(); submit(); }} aria-describedby={`${id}-instructions ${id}-error`} className="space-y-4">
      {options.map(o => <fieldset key={o.id} disabled={disabled} className="min-w-0 border rounded-lg p-2">
        <legend className="px-1 text-sm font-medium break-words">{o.label}</legend>
        {o.description && <OptionCardDescription text={o.description} />}
        <div className="grid grid-cols-6 gap-1 mt-2">{[0, 1, 2, 3, 4, 5].map(value => <label key={value} className={`flex flex-col items-center p-2 rounded cursor-pointer ${scores[o.id] === value ? 'bg-blue-100 border border-blue-600' : 'bg-gray-50 border border-gray-200'}`}>
          <input type="radio" name={`${id}-${o.id}`} value={value} checked={scores[o.id] === value} onChange={() => setScores(old => ({ ...old, [o.id]: value }))} aria-label={`${o.label}: ${value} stars`} className="accent-blue-700" />
          <span className="text-sm mt-1">{value}</span>
        </label>)}</div>
      </fieldset>)}
      <p className="text-xs text-gray-600">An all-zero ballot counts as participation and overrides delegation. Abstaining also overrides delegation but is excluded from rating totals.</p>
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={disabled} className="px-3 py-2 bg-[var(--brand-primary)] text-white rounded-lg disabled:opacity-50">{busy ? 'Submitting…' : 'Submit ballot'}</button>
        <button type="button" disabled={disabled} onClick={() => submit(true)} className="px-3 py-2 border rounded-lg">Abstain</button>
        <button type="button" disabled={busy} onClick={cancel} className="px-3 py-2 border rounded-lg">Cancel</button>
      </div>
    </form>}
    <p id={`${id}-error`} role={error ? 'alert' : undefined} className="text-sm text-red-700">{error}</p>
  </section>;
}
