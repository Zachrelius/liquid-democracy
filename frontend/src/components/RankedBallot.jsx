import { useState, useMemo } from 'react';
import { DragDropContext, Droppable, Draggable } from '@hello-pangea/dnd';
import api from '../api';
import { useToast } from './Toast';
import { useConfirm } from './ConfirmDialog';
import UserLink from './UserLink';

function ordinal(n) {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

/**
 * RankedBallot — drag-to-rank UI for ranked-choice proposals.
 *
 * Pattern matches the topic-precedence reordering in `pages/Delegations.jsx`
 * (uses @hello-pangea/dnd with DragDropContext / Droppable / Draggable).
 * Two zones: "Your ranking" (ordered) and "Not ranked" (unordered remainder).
 *
 * Props:
 *   proposal     — proposal object including .options
 *   myVote       — current /my-vote response (may have .ranking, .is_direct, .cast_by, etc.)
 *   proposalId   — string id (used in POST /api/proposals/{id}/vote)
 *   onVoteChange — callback fired after a successful submit/retract
 *   emailVerified— boolean, disables UI when false
 */
export default function RankedBallot({ proposal, myVote, proposalId, onVoteChange, emailVerified }) {
  const confirm = useConfirm();
  const toast = useToast();
  const [showBallot, setShowBallot] = useState(false);
  const [ranking, setRanking] = useState([]);
  const [unranked, setUnranked] = useState([]);
  const [casting, setCasting] = useState(false);
  const [err, setErr] = useState('');

  const options = useMemo(() => proposal.options || [], [proposal.options]);
  const optionMap = useMemo(() => {
    const m = {};
    options.forEach(o => { m[o.id] = o; });
    return m;
  }, [options]);

  const hasVote = myVote?.ranking != null;
  const isDirect = myVote?.is_direct;
  const unverified = !emailVerified;
  // Spec Decision 3 — non-strict-precedence falls back; surfaced if backend signals.
  const strategyFallback = myVote?.delegation_strategy_fallback;

  function startBallot() {
    const initial = isDirect && Array.isArray(myVote?.ranking) ? [...myVote.ranking] : [];
    const remaining = options.map(o => o.id).filter(id => !initial.includes(id));
    setRanking(initial);
    setUnranked(remaining);
    setShowBallot(true);
    setErr('');
  }

  function cancelBallot() {
    setShowBallot(false);
    setErr('');
  }

  function handleDragEnd(result) {
    const { source, destination } = result;
    if (!destination) return;
    if (source.droppableId === destination.droppableId && source.index === destination.index) return;

    if (source.droppableId === 'ranking' && destination.droppableId === 'ranking') {
      const next = Array.from(ranking);
      const [moved] = next.splice(source.index, 1);
      next.splice(destination.index, 0, moved);
      setRanking(next);
    } else if (source.droppableId === 'unranked' && destination.droppableId === 'unranked') {
      const next = Array.from(unranked);
      const [moved] = next.splice(source.index, 1);
      next.splice(destination.index, 0, moved);
      setUnranked(next);
    } else if (source.droppableId === 'unranked' && destination.droppableId === 'ranking') {
      const nextUnranked = Array.from(unranked);
      const [moved] = nextUnranked.splice(source.index, 1);
      const nextRanking = Array.from(ranking);
      nextRanking.splice(destination.index, 0, moved);
      setUnranked(nextUnranked);
      setRanking(nextRanking);
    } else if (source.droppableId === 'ranking' && destination.droppableId === 'unranked') {
      const nextRanking = Array.from(ranking);
      const [moved] = nextRanking.splice(source.index, 1);
      const nextUnranked = Array.from(unranked);
      nextUnranked.splice(destination.index, 0, moved);
      setRanking(nextRanking);
      setUnranked(nextUnranked);
    }
  }

  function moveToRanking(optionId) {
    setUnranked(prev => prev.filter(id => id !== optionId));
    setRanking(prev => [...prev, optionId]);
  }

  function removeFromRanking(optionId) {
    setRanking(prev => prev.filter(id => id !== optionId));
    setUnranked(prev => [...prev, optionId]);
  }

  async function submitBallot() {
    if (ranking.length === 0) {
      const ok = await confirm({
        title: 'Submit Empty Ballot?',
        message: "You haven't ranked any options. Submitting now counts as an abstention — you're saying you don't support any of them. This is different from not voting at all. Continue?",
        destructive: false,
      });
      if (!ok) return;
    }
    setCasting(true);
    setErr('');
    try {
      await api.post(`/api/proposals/${proposalId}/vote`, { ranking });
      toast.success(ranking.length > 0 ? 'Ballot submitted' : 'Abstention recorded');
      setShowBallot(false);
      onVoteChange();
    } catch (e) {
      setErr(e.message || 'Failed to submit ballot');
    } finally {
      setCasting(false);
    }
  }

  async function retractVote() {
    setCasting(true);
    setErr('');
    try {
      await api.delete(`/api/proposals/${proposalId}/vote`);
      toast.success('Vote retracted');
      setShowBallot(false);
      onVoteChange();
    } catch (e) {
      setErr(e.message || 'Failed to retract');
    } finally {
      setCasting(false);
    }
  }

  function renderRankingSummary(rank, label = 'Your ranking') {
    if (!rank || rank.length === 0) {
      return <p className="text-sm text-gray-500">{label === 'Your ranking' ? 'You abstained — no options ranked' : `${label}: abstained (no options ranked)`}</p>;
    }
    return (
      <div>
        <p className="text-sm font-medium text-[#2D8A56] mb-1">{label}:</p>
        <ol className="text-sm text-gray-700 space-y-0.5">
          {rank.map((oid, idx) => (
            <li key={oid}>
              <span className="text-gray-400 mr-2">{idx + 1}.</span>
              {optionMap[oid]?.label || oid}
            </li>
          ))}
        </ol>
      </div>
    );
  }

  // Already-cast ballot summary
  if (hasVote && !showBallot) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Ballot</h3>

        {unverified && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            Verify your email to vote.
          </p>
        )}

        {isDirect ? (
          renderRankingSummary(myVote.ranking)
        ) : (
          <div>
            <p className="text-sm text-gray-500 mb-1">
              Your vote: via {myVote.cast_by ? <UserLink user={myVote.cast_by} className="text-sm" /> : 'delegate'}
              {myVote.delegate_chain?.length > 1 ? ' (chain)' : ''}
            </p>
            {strategyFallback && (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 my-2">
                This proposal uses ranked-choice voting, which currently supports only strict-precedence delegation.
                Your delegate was selected based on your highest-priority matching topic.
              </p>
            )}
            {myVote.ranking && myVote.ranking.length > 0 ? (
              <div className="mt-1">
                <p className="text-xs text-gray-400 mb-1">
                  {myVote.cast_by?.display_name ? `${myVote.cast_by.display_name}'s ranking:` : "Delegate's ranking:"}
                </p>
                <ol className="text-sm text-gray-700 space-y-0.5">
                  {myVote.ranking.map((oid, idx) => (
                    <li key={oid}>
                      <span className="text-gray-400 mr-2">{idx + 1}.</span>
                      {optionMap[oid]?.label || oid}
                    </li>
                  ))}
                </ol>
              </div>
            ) : (
              <p className="text-xs text-gray-400 mt-1">
                {myVote.cast_by?.display_name
                  ? `${myVote.cast_by.display_name} abstained (no options ranked)`
                  : 'Delegate abstained (no options ranked)'}
              </p>
            )}
          </div>
        )}

        <div className="flex gap-2 mt-3">
          <button
            onClick={startBallot}
            disabled={unverified}
            className="text-xs px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors disabled:opacity-50"
          >
            {isDirect ? 'Change Ballot' : 'Override — Vote Directly'}
          </button>
          {isDirect && (
            <button
              onClick={retractVote}
              disabled={casting || unverified}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-500 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-50"
            >
              Retract
            </button>
          )}
        </div>

        {err && <p className="text-xs text-red-600">{err}</p>}
      </div>
    );
  }

  // No vote yet, ballot not started
  if (!hasVote && !showBallot) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Ballot</h3>

        {unverified && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            Verify your email to vote.
          </p>
        )}

        {strategyFallback && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            This proposal uses ranked-choice voting, which currently supports only strict-precedence delegation.
            Your delegate was selected based on your highest-priority matching topic.
          </p>
        )}

        <p className="text-gray-500 text-sm">
          {myVote?.message || 'No ballot cast'}
        </p>
        <button
          onClick={startBallot}
          disabled={unverified}
          className="text-sm px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
        >
          Cast Ballot
        </button>
      </div>
    );
  }

  // Active ballot — drag-to-rank UI
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Ballot</h3>

      {unverified && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Verify your email to vote.
        </p>
      )}

      <p className="text-xs text-gray-500">
        Drag options into your ranking. First place is your top choice. You can rank some, all, or none.
      </p>

      <DragDropContext onDragEnd={handleDragEnd}>
        {/* Your ranking zone */}
        <div>
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Your ranking</p>
          <Droppable droppableId="ranking">
            {(provided, snapshot) => (
              <ol
                {...provided.droppableProps}
                ref={provided.innerRef}
                className={`space-y-2 min-h-[3rem] p-2 rounded-lg border-2 border-dashed transition-colors ${
                  snapshot.isDraggingOver ? 'border-[#2E75B6] bg-blue-50' : 'border-gray-300 bg-white'
                }`}
              >
                {ranking.length === 0 && !snapshot.isDraggingOver && (
                  <li className="text-xs text-gray-400 text-center py-2 italic">
                    Drag options here to rank them
                  </li>
                )}
                {ranking.map((oid, index) => {
                  const opt = optionMap[oid];
                  if (!opt) return null;
                  return (
                    <Draggable key={oid} draggableId={oid} index={index}>
                      {(prov, snap) => (
                        <li
                          ref={prov.innerRef}
                          {...prov.draggableProps}
                          {...prov.dragHandleProps}
                          className={`flex items-start gap-3 bg-white border rounded-lg px-3 py-2 cursor-grab transition-shadow ${
                            snap.isDragging ? 'shadow-lg border-[#2E75B6]' : 'border-gray-200'
                          }`}
                        >
                          <span className="text-gray-300 text-sm select-none mt-0.5">⠿</span>
                          <span className="text-sm font-bold text-[#1B3A5C] w-10 shrink-0">{ordinal(index + 1)}</span>
                          <div className="flex-1 min-w-0">
                            <span className="text-sm font-medium text-gray-800">{opt.label}</span>
                            {opt.description && <p className="text-xs text-gray-500 mt-0.5">{opt.description}</p>}
                          </div>
                          <button
                            type="button"
                            onClick={() => removeFromRanking(oid)}
                            className="text-gray-300 hover:text-red-500 text-xs px-1"
                            title="Remove from ranking"
                          >
                            &#x2715;
                          </button>
                        </li>
                      )}
                    </Draggable>
                  );
                })}
                {provided.placeholder}
              </ol>
            )}
          </Droppable>
        </div>

        {/* Not ranked zone */}
        <div className="mt-4">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Not ranked</p>
          <p className="text-xs text-gray-400 mb-2">Options here won't be counted as preferences.</p>
          <Droppable droppableId="unranked">
            {(provided, snapshot) => (
              <ul
                {...provided.droppableProps}
                ref={provided.innerRef}
                className={`space-y-2 min-h-[3rem] p-2 rounded-lg border-2 border-dashed transition-colors ${
                  snapshot.isDraggingOver ? 'border-[#2E75B6] bg-blue-50' : 'border-gray-200 bg-gray-50'
                }`}
              >
                {unranked.length === 0 && (
                  <li className="text-xs text-gray-400 text-center py-2 italic">
                    All options ranked
                  </li>
                )}
                {unranked.map((oid, index) => {
                  const opt = optionMap[oid];
                  if (!opt) return null;
                  return (
                    <Draggable key={oid} draggableId={oid} index={index}>
                      {(prov, snap) => (
                        <li
                          ref={prov.innerRef}
                          {...prov.draggableProps}
                          {...prov.dragHandleProps}
                          className={`flex items-start gap-3 bg-white border rounded-lg px-3 py-2 cursor-grab transition-shadow ${
                            snap.isDragging ? 'shadow-lg border-[#2E75B6]' : 'border-gray-200'
                          }`}
                        >
                          <span className="text-gray-300 text-sm select-none mt-0.5">⠿</span>
                          <div className="flex-1 min-w-0">
                            <span className="text-sm font-medium text-gray-800">{opt.label}</span>
                            {opt.description && <p className="text-xs text-gray-500 mt-0.5">{opt.description}</p>}
                          </div>
                          <button
                            type="button"
                            onClick={() => moveToRanking(oid)}
                            className="text-xs text-[#2E75B6] hover:underline"
                            title="Add to ranking"
                          >
                            Rank
                          </button>
                        </li>
                      )}
                    </Draggable>
                  );
                })}
                {provided.placeholder}
              </ul>
            )}
          </Droppable>
        </div>
      </DragDropContext>

      <div className="flex gap-2 pt-2">
        <button
          onClick={submitBallot}
          disabled={casting || unverified}
          className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
        >
          {casting
            ? 'Submitting...'
            : `Submit Ballot${ranking.length > 0 ? ` (${ranking.length} ranked)` : ''}`}
        </button>
        <button
          onClick={cancelBallot}
          className="text-xs text-gray-400 hover:text-gray-600 px-2"
        >
          Cancel
        </button>
      </div>

      {err && <p className="text-xs text-red-600">{err}</p>}
    </div>
  );
}
