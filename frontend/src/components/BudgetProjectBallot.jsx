import { useState, useMemo } from 'react';
import api from '../api';
import { useToast } from './Toast';
import { optionDisplayLabel } from '../utils/optionDisplay';
import { formatBudget as fmt } from '../utils/budgetFormat';

/**
 * BudgetProjectBallot — Phase 74 project-budget ballot.
 *
 * Voters build an ordered priority list of items (rank from "Not funding" into
 * "Your ranking", reorder with up/down). For a tier-parent item, an inline tier
 * selector picks the variant. A live "implied total" shows the spend the
 * voter's ranking commits. Omitted items sit in a visible "Not funding" tray so
 * the omission-deprioritizes semantics are legible. Direct-vote only.
 */

export default function BudgetProjectBallot({ proposal, myVote, proposalId, onVoteChange, emailVerified }) {
  const toast = useToast();
  const cfg = proposal.budget_config || {};
  const currency = cfg.currency || 'USD';
  const allOptions = useMemo(() => proposal.options || [], [proposal.options]);

  // Rankable items = everything except tier children (children fold under a
  // tier parent). Build parent -> [children] for the tier selectors.
  const { rankable, childrenOf, optById } = useMemo(() => {
    const byId = {};
    allOptions.forEach((o) => { byId[o.id] = o; });
    const kids = {};
    allOptions.forEach((o) => {
      if (o.budget_tier_parent_id) {
        (kids[o.budget_tier_parent_id] ||= []).push(o);
      }
    });
    const top = allOptions.filter((o) => !o.budget_tier_parent_id);
    return { rankable: top, childrenOf: kids, optById: byId };
  }, [allOptions]);

  const isParent = (o) => o.budget_kind === 'tier_parent';

  const [showBallot, setShowBallot] = useState(false);
  const [ranking, setRanking] = useState([]);      // ordered option_ids
  const [tierSel, setTierSel] = useState({});       // {parentId: childId}
  const [casting, setCasting] = useState(false);
  const [err, setErr] = useState('');

  const unverified = !emailVerified;
  const hasVote = myVote?.ranked != null;

  function itemCost(oid) {
    const o = optById[oid];
    if (!o) return 0;
    if (isParent(o)) {
      const kids = childrenOf[oid] || [];
      const sel = tierSel[oid];
      const child = kids.find((k) => k.id === sel) || kids.slice().sort(
        (a, b) => (a.budget_floor_amount || 0) - (b.budget_floor_amount || 0))[0];
      return child ? (child.budget_floor_amount || 0) : 0;
    }
    if (o.budget_kind === 'continuous-as-discrete') {
      return o.budget_max_amount != null ? o.budget_max_amount : (o.budget_floor_amount || 0);
    }
    return o.budget_floor_amount || 0;
  }

  function startBallot() {
    const initialRanking = [];
    const initialTier = {};
    if (Array.isArray(myVote?.ranked)) {
      myVote.ranked.forEach((e) => {
        if (optById[e.option_id]) {
          initialRanking.push(e.option_id);
          if (e.tier_id) initialTier[e.option_id] = e.tier_id;
        }
      });
    }
    // default tier selection = cheapest child for any unset parent
    rankable.forEach((o) => {
      if (isParent(o) && !initialTier[o.id]) {
        const kids = (childrenOf[o.id] || []).slice().sort(
          (a, b) => (a.budget_floor_amount || 0) - (b.budget_floor_amount || 0));
        if (kids[0]) initialTier[o.id] = kids[0].id;
      }
    });
    setRanking(initialRanking);
    setTierSel(initialTier);
    setShowBallot(true);
    setErr('');
  }

  const unranked = rankable.filter((o) => !ranking.includes(o.id));
  const impliedTotal = ranking.reduce((s, oid) => s + itemCost(oid), 0);

  function move(oid, dir) {
    setRanking((prev) => {
      const i = prev.indexOf(oid);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }
  const addToRanking = (oid) => setRanking((p) => [...p, oid]);
  const removeFromRanking = (oid) => setRanking((p) => p.filter((x) => x !== oid));

  async function submitBallot() {
    setCasting(true);
    setErr('');
    const ranked = ranking.map((oid) => ({
      option_id: oid,
      tier_id: isParent(optById[oid]) ? (tierSel[oid] || null) : null,
    }));
    try {
      await api.post(`/api/proposals/${proposalId}/vote`, { ranked });
      toast.success('Ranking submitted');
      setShowBallot(false);
      onVoteChange();
    } catch (e) {
      setErr(e.message || 'Failed to submit ranking');
    } finally {
      setCasting(false);
    }
  }

  function tierSelector(o) {
    const kids = childrenOf[o.id] || [];
    if (!kids.length) return null;
    return (
      <select
        value={tierSel[o.id] || ''}
        onChange={(e) => setTierSel((p) => ({ ...p, [o.id]: e.target.value }))}
        className="text-xs border border-gray-300 rounded px-1.5 py-0.5 ml-2"
      >
        {kids.map((k) => (
          <option key={k.id} value={k.id}>
            {optionDisplayLabel(proposal, k)} ({fmt(k.budget_floor_amount, currency)})
          </option>
        ))}
      </select>
    );
  }

  // Already-cast summary
  if (hasVote && !showBallot) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Ranking</h3>
        {unverified && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">Verify your email to vote.</p>
        )}
        <ol className="text-sm text-gray-700 space-y-0.5">
          {myVote.ranked.map((e, i) => (
            <li key={e.option_id}>
              <span className="text-gray-400 mr-1">{i + 1}.</span>
              {optionDisplayLabel(proposal, optById[e.option_id]) || e.option_id}
              {e.tier_id && optById[e.tier_id] && (
                <span className="text-xs text-[var(--brand-accent)] ml-1">— {optionDisplayLabel(proposal, optById[e.tier_id])}</span>
              )}
            </li>
          ))}
        </ol>
        <p className="text-xs text-gray-500">Budget proposals are direct-vote only.</p>
        <button onClick={startBallot} disabled={unverified}
          className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors disabled:opacity-50">
          Change Ranking
        </button>
        {err && <p className="text-xs text-red-600">{err}</p>}
      </div>
    );
  }

  if (!hasVote && !showBallot) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Ranking</h3>
        {unverified && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">Verify your email to vote.</p>
        )}
        <p className="text-sm text-gray-500">
          Rank the projects you want funded, highest priority first. The group
          funds in priority order up to its chosen spend level. Items you don’t
          rank are treated as lowest priority. Direct-vote only.
        </p>
        <button onClick={startBallot} disabled={unverified}
          className="text-sm px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50">
          Rank Projects
        </button>
      </div>
    );
  }

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Ranking</h3>
      {unverified && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">Verify your email to vote.</p>
      )}
      <p className="text-xs text-gray-500">
        Highest priority first. Reorder with the arrows. For tiered items, pick a
        variant. Unranked items go to the bottom of the group’s priority.
      </p>

      {/* Your ranking */}
      <div>
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Your priority order</p>
        <ol className="space-y-1">
          {ranking.length === 0 && (
            <li className="text-xs text-gray-400 italic py-1">Nothing ranked yet — add items below.</li>
          )}
          {ranking.map((oid, idx) => {
            const o = optById[oid];
            if (!o) return null;
            return (
              <li key={oid} className="bg-white border border-gray-200 rounded-lg px-2 py-1.5">
                <div className="flex items-center gap-1">
                  <span className="text-sm font-bold text-[var(--brand-primary)] w-5">{idx + 1}</span>
                  <span className="text-sm text-gray-800 flex-1 leading-snug">
                    {optionDisplayLabel(proposal, o)}
                    {isParent(o) ? tierSelector(o)
                      : <span className="text-xs text-gray-400 ml-1">({fmt(itemCost(oid), currency)})</span>}
                  </span>
                  <button type="button" onClick={() => move(oid, -1)} disabled={idx === 0}
                    className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-xs px-1">▲</button>
                  <button type="button" onClick={() => move(oid, 1)} disabled={idx === ranking.length - 1}
                    className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-xs px-1">▼</button>
                  <button type="button" onClick={() => removeFromRanking(oid)}
                    className="text-gray-300 hover:text-red-500 text-xs px-1" title="Remove">✕</button>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      {/* Not funding tray */}
      <div>
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Not funding (lowest priority)</p>
        {unranked.length === 0 ? (
          <p className="text-xs text-gray-400 italic">All items ranked.</p>
        ) : (
          <ul className="space-y-1">
            {unranked.map((o) => (
              <li key={o.id} className="flex items-center justify-between gap-2 bg-white border border-gray-200 rounded-lg px-2 py-1.5">
                <span className="text-sm text-gray-700 leading-snug">
                  {optionDisplayLabel(proposal, o)}
                  {!isParent(o) && <span className="text-xs text-gray-400 ml-1">({fmt(itemCost(o.id), currency)})</span>}
                </span>
                <button type="button" onClick={() => addToRanking(o.id)}
                  className="text-xs text-[var(--brand-accent)] hover:underline">Rank</button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="text-sm font-medium text-gray-700">
        Your implied total: {fmt(impliedTotal, currency)} of {fmt(cfg.envelope, currency)}
      </div>

      <div className="flex gap-2 pt-1">
        <button onClick={submitBallot} disabled={casting || unverified}
          className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50">
          {casting ? 'Submitting...' : 'Submit Ranking'}
        </button>
        <button onClick={() => setShowBallot(false)} className="text-xs text-gray-400 hover:text-gray-600 px-2">Cancel</button>
      </div>
      {err && <p className="text-xs text-red-600">{err}</p>}
    </div>
  );
}
