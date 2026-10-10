import { useId, useRef, useState } from 'react';
import api from '../api';
import { optionDisplayLabel } from '../utils/optionDisplay';
import { useToast } from './Toast';
import VerifyEmailInlineNote from './VerifyEmailInlineNote';
import UserLink from './UserLink';
import OptionCardDescription from './OptionCardDescription';
import { assignmentsFromGroups, hasRankGroupsBallot, rankGroupsPayload } from '../utils/rankGroups';

export function RankGroupControls({ options, assignments, onChange, disabled, idPrefix }) {
  return <div className="space-y-3">{options.map(option => {
    const rank = assignments[option.id] ?? null;
    return <fieldset key={option.id} disabled={disabled} className="min-w-0 border rounded-lg p-3 space-y-2">
      <legend className="text-sm font-medium break-words px-1">{option.label}</legend>
      {option.description && <OptionCardDescription text={option.description} />}
      <label htmlFor={`${idPrefix}-${option.id}`} className="block text-xs">Rank group for {option.label}</label>
      <select id={`${idPrefix}-${option.id}`} value={rank ?? ''} onChange={event => onChange(option.id, event.target.value === '' ? null : Number(event.target.value))} className="w-full min-w-0 border rounded p-2 text-sm">
        <option value="">Unranked — tied last</option>
        {options.map((_, index) => <option key={index + 1} value={index + 1}>Group {index + 1}{index === 0 ? ' — most preferred' : ''}</option>)}
      </select>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={disabled || rank == null || rank === 1} aria-label={`Move ${option.label} up one rank group`} onClick={() => onChange(option.id, rank - 1)} className="border rounded px-2 py-1 text-xs disabled:opacity-40">Move up</button>
        <button type="button" disabled={disabled || rank == null || rank === options.length} aria-label={`Move ${option.label} down one rank group`} onClick={() => onChange(option.id, rank + 1)} className="border rounded px-2 py-1 text-xs disabled:opacity-40">Move down</button>
      </div>
    </fieldset>;
  })}</div>;
}

export default function RankGroupsBallot({ proposal, proposalId, myVote, onVoteChange, emailVerified }) {
  const [assignments, setAssignments] = useState({});
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const id = useId();
  const formRef = useRef(null);
  const changeRef = useRef(null);
  const toast = useToast();
  const options = (proposal.options || []).map(option => proposal.is_election
    ? { ...option, label: optionDisplayLabel(proposal, option), description: null } : option);
  const hasVote = hasRankGroupsBallot(myVote);
  const disabled = busy || !emailVerified;
  const optionLabel = optionId => options.find(option => option.id === optionId)?.label || optionId;
  function open() {
    setAssignments(myVote?.is_direct ? assignmentsFromGroups(myVote.rank_groups || []) : {});
    setError('');
    setEditing(true);
    requestAnimationFrame(() => formRef.current?.querySelector('select')?.focus());
  }
  function cancel() { setEditing(false); changeRef.current?.focus(); }
  async function submit(abstain = false) {
    setBusy(true); setError('');
    try {
      await api.post(`/api/proposals/${proposalId}/vote`, rankGroupsPayload(assignments, options.map(option => option.id), abstain));
      setEditing(false);
      toast.success(abstain ? 'Abstention recorded' : 'Ballot submitted');
      await onVoteChange();
      changeRef.current?.focus();
    } catch (failure) { setError(failure.message || 'Unable to submit ballot'); }
    finally { setBusy(false); }
  }
  async function retract() {
    setBusy(true); setError('');
    try {
      await api.delete(`/api/proposals/${proposalId}/vote`);
      toast.success('Ballot retracted; your delegation can apply again');
      await onVoteChange();
    } catch (failure) { setError(failure.message || 'Unable to retract ballot'); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3" aria-label="Your Ranked Pairs ballot">
    <h3 className="text-sm font-semibold">Your Ranked Pairs ballot</h3>
    <p id={`${id}-instructions`} className="text-sm text-gray-600">Assign preferred options to rank groups, with group 1 best. Put equally preferred options in the same group. Unranked options tie below every ranked option and with one another.</p>
    <p className="text-xs text-gray-600">{proposal.is_election ? 'Unranked candidates tie below every ranked candidate.' : 'Later write-ins remain unranked on your saved ballot until you change it.'} You can use the group menus or Move up and Move down buttons; dragging is not required. Changing a group does not submit your vote.</p>
    {!emailVerified && <VerifyEmailInlineNote action="vote" />}
    {!editing && <>
      {hasVote ? <div className="text-sm">
        <p>{myVote.is_direct ? 'Your submitted ballot' : <>Via {myVote.cast_by ? <UserLink user={myVote.cast_by} /> : 'delegate'}</>}</p>
        {myVote.abstain ? <p>You abstained. This overrides delegation and contributes no preferences.</p> : <>
          <ol className="mt-2 space-y-1">{(myVote.rank_groups || []).map((group, index) => <li key={index}>Group {index + 1}: {group.map(optionLabel).join(' = ')}</li>)}</ol>
          <p className="mt-2">Unranked (tied last): {options.filter(option => !(myVote.rank_groups || []).flat().includes(option.id)).map(option => option.label).join(', ') || 'None'}</p>
          {myVote.rank_groups?.length === 0 && <p className="text-xs">Your neutral ballot counts as participation and overrides delegation.</p>}
        </>}
      </div> : <p className="text-sm text-gray-500">{myVote?.message || 'No ballot cast.'}</p>}
      <div className="flex flex-wrap gap-2">
        <button ref={changeRef} type="button" onClick={open} disabled={disabled} className="px-3 py-2 border rounded-lg text-sm disabled:opacity-50">{hasVote ? myVote.is_direct ? 'Change ballot' : 'Override — vote directly' : 'Cast ballot'}</button>
        {hasVote && myVote.is_direct && <button type="button" onClick={retract} disabled={disabled} className="px-3 py-2 border rounded-lg text-sm disabled:opacity-50">Retract</button>}
      </div>
    </>}
    {editing && <form ref={formRef} onSubmit={event => { event.preventDefault(); submit(); }} aria-describedby={`${id}-instructions ${id}-error`} className="space-y-4">
      <RankGroupControls options={options} assignments={assignments} onChange={(optionId, rank) => setAssignments(old => ({ ...old, [optionId]: rank }))} disabled={disabled} idPrefix={id} />
      <p className="text-xs text-gray-600">Options in the same group are tied; unused group numbers are skipped when submitted. Leaving everything unranked submits a neutral ballot that counts as participation and overrides delegation. Abstaining also overrides delegation but contributes no preferences.</p>
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={disabled} className="px-3 py-2 bg-[var(--brand-primary)] text-white rounded-lg disabled:opacity-50">{busy ? 'Submitting…' : 'Submit ballot'}</button>
        <button type="button" disabled={disabled} onClick={() => submit(true)} className="px-3 py-2 border rounded-lg">Abstain</button>
        <button type="button" disabled={busy} onClick={cancel} className="px-3 py-2 border rounded-lg">Cancel</button>
      </div>
    </form>}
    <p id={`${id}-error`} role={error ? 'alert' : undefined} className="text-sm text-red-700">{error}</p>
  </section>;
}
