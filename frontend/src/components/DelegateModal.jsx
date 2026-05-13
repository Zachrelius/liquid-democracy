import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import useScopeCoverage from '../hooks/useScopeCoverage';
import { urlFor } from '../utils/urls';
import Avatar from './Avatar';
import VerifyEmailInlineNote from './VerifyEmailInlineNote';
import { timeAgo } from '../utils/timeAgo';

// Decision 10 helper — map persisted chain_behavior values to the human-
// readable phrasing called out in the cross-scope disclosure copy.
const CHAIN_BEHAVIOR_PHRASES = {
  accept_sub: "accept sub-delegate's vote",
  revert_direct: 'revert to direct voting',
  abstain: 'abstain on those proposals',
};

function ResultCard({
  user,
  topicId,
  onDone,
  unverified,
  scopeCoverage,
  onCreateTopicScopedDelegations,
  scopeFilterMode,
  defaultChainBehavior,
  parentSlug,
}) {
  const [acting, setActing] = useState(false);
  const [feedback, setFeedback] = useState('');
  // Phase 11 — user-profile is org-scoped now. Resolve the parent slug for
  // the View Profile link.
  const { currentOrg, userOrgs } = useOrg();
  const profileLinkOrg = (() => {
    if (!currentOrg) return null;
    if (currentOrg.parent_org_id) {
      return userOrgs.find(o => o.id === currentOrg.parent_org_id) || null;
    }
    return currentOrg;
  })();

  const profiles = user.delegate_profiles || [];
  const isPublicForTopic = topicId && profiles.some(p => p.topic_id === topicId);
  const isPublic = profiles.length > 0;
  const isFollowing = user.follow_status === 'following';
  const isPending = user.follow_status === 'pending';
  const canDelegate = isPublicForTopic || (isFollowing && user.follow_permission === 'delegation_allowed');

  // Decision 10 — coverage list and missing scopes for this candidate.
  const candidateCoverage = scopeCoverage?.coverageFor?.(user.id);
  const coverage = candidateCoverage?.coverage || [];
  const missing = candidateCoverage?.missing || [];
  const hasFullCoverage = candidateCoverage?.hasFullCoverage !== false;

  // Build the coverage line. Examples:
  //   ["Demo Org"]                           -> "Demo Org only"  (when viewer
  //                                            is in any sub-org the candidate
  //                                            isn't, OR the viewer has any
  //                                            accessible sub-orgs at all and
  //                                            the candidate is in none).
  //   ["Demo Org", "Engineering Team"]       -> "Demo Org, Engineering Team"
  let coverageLine = null;
  if (coverage.length > 0) {
    if (!hasFullCoverage) {
      // Candidate is in parent only or partial coverage relative to viewer.
      coverageLine = coverage.length === 1
        ? `${coverage[0]} only`
        : coverage.join(', ');
    } else {
      coverageLine = coverage.join(', ');
    }
  }

  async function doDelegate() {
    setActing(true);
    setFeedback('');
    try {
      // Phase 18 F2 — branches depend on scopeFilterMode for the global
      // delegate flow (topicId === undefined). Backend now supports:
      //   - "All my scopes" (`scopeFilterMode === 'all'`) → single row
      //     with org_id only (no sub_org_id, no topic_id).
      //   - "Only [SubOrg]" (`scopeFilterMode === 'sub:<id>'`) → single
      //     row with sub_org_id set, replacing the pre-Phase-18 fan-out.
      //   - "Only parent-org topics" (`scopeFilterMode === 'parent'`) →
      //     KEEP fan-out (per-topic rows). Documented as known-suboptimal
      //     in audit; a clean single-row representation needs a new
      //     `scope_modifier` column and is out of scope for v1.
      const isGlobalFlow = topicId === undefined;
      const isSubOrgScope = isGlobalFlow && typeof scopeFilterMode === 'string' && scopeFilterMode.startsWith('sub:');
      const isParentOnlyScope = isGlobalFlow && scopeFilterMode === 'parent';

      if (isParentOnlyScope && onCreateTopicScopedDelegations) {
        // Fan-out: per-topic rows for each parent-only topic. Known-
        // suboptimal post-Phase-18; tracked in audit (F2 deferred item).
        await onCreateTopicScopedDelegations(user.id, defaultChainBehavior || 'accept_sub');
      } else {
        const body = {
          delegate_id: user.id,
          topic_id: topicId || null,
          chain_behavior: defaultChainBehavior || 'accept_sub',
        };
        if (isSubOrgScope) {
          body.sub_org_id = scopeFilterMode.slice(4);
        }
        await api.post(`/api/orgs/${parentSlug}/delegations/request`, body);
      }
      setFeedback('Delegation created');
      setTimeout(() => onDone?.(), 600);
    } catch (e) {
      setFeedback(e.message);
    } finally {
      setActing(false);
    }
  }

  async function doRequestDelegate() {
    setActing(true);
    setFeedback('');
    try {
      const res = await api.post(`/api/orgs/${parentSlug}/delegations/request`, {
        delegate_id: user.id,
        topic_id: topicId || null,
        chain_behavior: defaultChainBehavior || 'accept_sub',
      });
      setFeedback(res.message || 'Request sent');
    } catch (e) {
      setFeedback(e.message);
    } finally {
      setActing(false);
    }
  }

  async function doRequestFollow() {
    setActing(true);
    setFeedback('');
    try {
      // Phase 18 — follow surfaces are org-scoped. The parent slug is
      // already resolved by the parent <DelegateModal>, but ResultCard
      // doesn't receive it; resolve from currentOrg here.
      const followOrgSlug = currentOrg?.parent_org_id
        ? (userOrgs.find(o => o.id === currentOrg.parent_org_id)?.slug || currentOrg.slug)
        : currentOrg?.slug;
      await api.post(`/api/orgs/${followOrgSlug}/follows/request`, { target_id: user.id });
      setFeedback('Follow request sent');
    } catch (e) {
      setFeedback(e.message);
    } finally {
      setActing(false);
    }
  }

  // Cross-scope disclosure copy — only shown when the candidate is missing
  // one or more of the viewer's sub-org scopes AND the viewer can act on this
  // candidate (canDelegate). Informational, not a warning.
  const disclosureMissingNames =
    missing.length > 0
      ? missing.length === 1
        ? missing[0]
        : missing.length === 2
          ? `${missing[0]} and ${missing[1]}`
          : `${missing.slice(0, -1).join(', ')}, and ${missing[missing.length - 1]}`
      : null;
  const chainBehaviorPhrase =
    CHAIN_BEHAVIOR_PHRASES[defaultChainBehavior || 'accept_sub'];

  return (
    <div className="border border-gray-200 rounded-lg p-3 space-y-2">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <Avatar user={user} size="sm" />
            <span className="font-medium text-sm text-[var(--brand-primary)]">{user.display_name}</span>
            <span className="text-xs text-gray-400">@{user.username}</span>
            <Link
              to={profileLinkOrg ? urlFor(profileLinkOrg, 'user-profile', user.id) : '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--brand-accent)] hover:text-[var(--brand-primary)] ml-0.5"
              title="View Profile"
              onClick={e => e.stopPropagation()}
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </Link>
          </div>
          {/* Decision 10 — scope coverage indicator */}
          {coverageLine && (
            <p className="text-[11px] text-gray-500 mt-0.5">
              {coverageLine}
            </p>
          )}
        </div>
      </div>

      {/* Status line */}
      <div className="text-xs text-gray-500 space-x-2">
        {isPublicForTopic && (
          <span className="text-green-600 font-medium">Public Delegate</span>
        )}
        {isPublic && !isPublicForTopic && (
          <span className="text-blue-500">Public Delegate (other topics)</span>
        )}
        {isFollowing && (
          <span>Following · {user.follow_permission === 'delegation_allowed' ? 'Delegation allowed' : 'View only'}</span>
        )}
        {isPending && (
          <span className="text-amber-600">Follow request pending</span>
        )}
        {!isFollowing && !isPending && !isPublic && (
          <span className="text-gray-400">Not following</span>
        )}
      </div>

      {/* Bio for public delegates */}
      {isPublicForTopic && profiles.find(p => p.topic_id === topicId)?.bio && (
        <p className="text-xs text-gray-500 italic line-clamp-2">
          "{profiles.find(p => p.topic_id === topicId).bio}"
        </p>
      )}

      {/* Cross-scope disclosure (Decision 10 moment 1) */}
      {disclosureMissingNames && canDelegate && (
        <p className="text-xs text-gray-600 bg-blue-50 border border-blue-100 rounded px-2 py-1.5">
          {user.display_name} isn&apos;t in {disclosureMissingNames}, so your votes there
          will follow your chain-behavior preference (currently: {chainBehaviorPhrase}).
        </p>
      )}

      {/* Action buttons */}
      <div className="flex gap-2 flex-wrap items-center">
        {unverified && <VerifyEmailInlineNote action="delegate" />}
        {canDelegate && (
          <button
            onClick={doDelegate}
            disabled={acting || unverified}
            className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
          >
            Delegate
          </button>
        )}
        {isFollowing && user.follow_permission === 'view_only' && (
          <button
            onClick={doRequestDelegate}
            disabled={acting || unverified}
            className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors disabled:opacity-50"
          >
            Request Delegate
          </button>
        )}
        {!isFollowing && !isPending && !canDelegate && (
          <>
            <button
              onClick={doRequestFollow}
              disabled={acting || unverified}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              Request Follow
            </button>
            <button
              onClick={doRequestDelegate}
              disabled={acting || unverified}
              className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors disabled:opacity-50"
            >
              Request Delegate
            </button>
          </>
        )}
        {isPending && user.has_pending_intent && (
          <span className="text-xs text-amber-600">Pending approval</span>
        )}
      </div>

      {feedback && (
        <p className={`text-xs ${feedback.includes('error') || feedback.includes('Cannot') ? 'text-red-600' : 'text-green-600'}`}>
          {feedback}
        </p>
      )}
    </div>
  );
}

export default function DelegateModal({
  topicId,
  topicName,
  onClose,
  onDone,
  // Phase 26 D2 — when set, the modal opens with this user pre-selected
  // (no search). Shape: {user_id, display_name, username, avatar_url}.
  // Used from DelegatePublic.jsx so a viewer who clicked "Delegate to X
  // on Topic" lands on the confirm UI instead of being asked to search
  // for X again. A "Choose someone else" link below resets to the
  // search flow. Existing callers (Delegations.jsx) don't pass this
  // prop and see the original search-only behavior.
  preselectedUser = null,
}) {
  const { user } = useAuth();
  const { currentOrg, userOrgs } = useOrg();
  const unverified = !user?.email_verified;
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  // Phase 26 D2 — preselect mode state. Tracks the full enriched user
  // record (with delegate_profiles, follow_status, etc.) fetched via
  // the existing search endpoint using preselectedUser.username as the
  // query. cleared when the user clicks "Choose someone else."
  const [preselectMode, setPreselectMode] = useState(!!preselectedUser);
  const [preselectedFull, setPreselectedFull] = useState(null);
  const [preselectError, setPreselectError] = useState('');
  // Decision 4-bis — apply-to scope radio. Only shown for the global flow
  // (topicId === undefined) and only when the viewer is in at least one
  // sub-org. Default 'all' preserves the legacy single-row global delegation.
  const [scopeFilterMode, setScopeFilterMode] = useState('all');

  // Resolve the parent-org slug for scope-coverage lookup. If currentOrg is
  // a sub-org we walk up via userOrgs; if it's already the parent we use it
  // directly; if there is no currentOrg (multi-org user without selection)
  // we skip coverage entirely.
  const parentSlug = useMemo(() => {
    if (!currentOrg) return null;
    if (currentOrg.parent_org_id) {
      const parent = userOrgs.find(o => o.id === currentOrg.parent_org_id);
      return parent?.slug || null;
    }
    return currentOrg.slug;
  }, [currentOrg, userOrgs]);

  const scopeCoverage = useScopeCoverage(parentSlug, user?.id);

  // Decision 4-bis — sub-orgs the viewer can narrow into. Sourced from the
  // accessible sub-org list (viewer-membership-only) returned by the helper.
  const viewerSubOrgs = scopeCoverage.subOrgs || [];

  // For global-default flow, the chain_behavior used when creating the
  // delegation. Modal currently always sets accept_sub at create time; we
  // keep that default but pipe it through so the cross-scope disclosure
  // copy reflects the value that will actually be persisted.
  const defaultChainBehavior = 'accept_sub';

  // Phase 18 F2 — fan-out is retained ONLY for the "Only parent-org
  // topics" path. The "Only [SubOrg]" path now writes a single
  // (org_id=parent, sub_org_id=Y, topic_id=NULL) row inline in
  // ResultCard.doDelegate; the legacy per-topic fan-out for sub-org scope
  // has been removed in favor of the cleaner single-row representation.
  //
  // Known-suboptimal: "Only parent-org topics" remains as fan-out
  // (creates N per-topic rows). A clean single-row representation would
  // need a new `scope_modifier` column on Delegation; that's tracked in
  // the audit doc (Phase 18 §G) and out of scope for v1.
  //
  // The per-topic endpoint handles permission gating per-topic; we
  // suppress per-topic failures so a partial success still records what
  // it can.
  async function createTopicScopedDelegations(delegateId, chainBehavior) {
    let topicsForScope = [];
    try {
      // Pull topics scoped to the parent org (which already includes the
      // viewer-visible sub-org topics per Decision-7 visibility filtering).
      const all = await api.get(`/api/orgs/${parentSlug}/topics`);
      if (scopeFilterMode === 'parent') {
        topicsForScope = all.filter(t => !t.sub_org_id);
      }
      // 'sub:<id>' is no longer routed here — collapsed to single-row in
      // ResultCard. Other modes ('all', topic-specific) never call this.
    } catch {
      // If we can't fetch topics, fall back to the global-null delegation.
      await api.post(`/api/orgs/${parentSlug}/delegations/request`, {
        delegate_id: delegateId,
        topic_id: null,
        chain_behavior: chainBehavior,
      });
      return;
    }

    if (topicsForScope.length === 0) {
      // Nothing to delegate against for this scope — fall back to global.
      await api.post(`/api/orgs/${parentSlug}/delegations/request`, {
        delegate_id: delegateId,
        topic_id: null,
        chain_behavior: chainBehavior,
      });
      return;
    }

    // Create per-topic delegations. Tolerate per-topic failures (typically
    // permission gates) so a partial success still records what it can.
    await Promise.all(
      topicsForScope.map(t =>
        api.post(`/api/orgs/${parentSlug}/delegations/request`, {
          delegate_id: delegateId,
          topic_id: t.id,
          chain_behavior: chainBehavior,
        }).catch(() => null)
      )
    );
  }

  // Phase 26 D2 — when preselectMode is on, fetch the full enriched
  // record for preselectedUser via the existing search endpoint
  // (q=username filter, then exact-match on user_id). This pulls the
  // delegate_profiles / follow_status / follow_permission fields that
  // ResultCard needs to render the correct action button. Skipped when
  // preselectMode is off (user clicked "Choose someone else").
  useEffect(() => {
    if (!preselectMode || !preselectedUser?.username) return;
    let cancelled = false;
    (async () => {
      setSearching(true);
      setPreselectError('');
      try {
        let url = `/api/users/search?q=${encodeURIComponent(preselectedUser.username)}&limit=10`;
        if (currentOrg?.slug) {
          url += `&org_slug=${encodeURIComponent(currentOrg.slug)}`;
        }
        const res = await api.get(url);
        if (cancelled) return;
        const match = (res || []).find(u => u.id === preselectedUser.user_id);
        if (match) {
          setPreselectedFull(match);
        } else {
          // Search couldn't enrich the user (rare — maybe they left the
          // org between page load and click). Fall back to search flow.
          setPreselectError(
            "Couldn't find this delegate's profile. Use search instead."
          );
          setPreselectMode(false);
        }
      } catch (e) {
        if (cancelled) return;
        setPreselectError(e.message || 'Failed to load delegate');
        setPreselectMode(false);
      } finally {
        if (!cancelled) setSearching(false);
      }
    })();
    return () => { cancelled = true; };
  }, [preselectMode, preselectedUser, currentOrg]);

  useEffect(() => {
    if (preselectMode) return; // skip free-text search when preselect is active
    if (query.length < 2) { setResults([]); return; }
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        // Phase 9.9 W5 — scope delegate search to the active org so users
        // don't see members of other orgs in the result list. If there's
        // no current org (rare on this surface), omit the param and rely
        // on the backend's backward-compat path.
        let url = `/api/users/search?q=${encodeURIComponent(query)}&limit=10`;
        if (currentOrg?.slug) {
          url += `&org_slug=${encodeURIComponent(currentOrg.slug)}`;
        }
        const res = await api.get(url);
        setResults(res);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query, currentOrg, preselectMode]);

  const showApplyToRadio = topicId === undefined && viewerSubOrgs.length > 0;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md max-h-[80vh] flex flex-col">
        <div className="p-4 border-b border-gray-100">
          <h2 className="font-semibold text-[var(--brand-primary)]">
            {topicName ? `Set delegate for ${topicName}` : 'Set global default delegate'}
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Public delegates can be selected directly. Others require a follow request.
          </p>
        </div>
        <div className="p-4 space-y-3 flex-1 overflow-y-auto">
          {/* Decision 4-bis — apply-to scope selector. Only rendered for the
              global flow when the viewer has at least one sub-org. */}
          {showApplyToRadio && (
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-1">
              <p className="text-xs font-medium text-gray-600 mb-1">Apply to:</p>
              <label className="flex items-center gap-2 text-xs text-gray-700">
                <input
                  type="radio"
                  name="scope-filter"
                  value="all"
                  checked={scopeFilterMode === 'all'}
                  onChange={() => setScopeFilterMode('all')}
                />
                <span>All my scopes (default)</span>
              </label>
              <label className="flex items-center gap-2 text-xs text-gray-700">
                <input
                  type="radio"
                  name="scope-filter"
                  value="parent"
                  checked={scopeFilterMode === 'parent'}
                  onChange={() => setScopeFilterMode('parent')}
                />
                <span>Only parent-org topics</span>
              </label>
              {viewerSubOrgs.map(s => (
                <label key={s.id} className="flex items-center gap-2 text-xs text-gray-700">
                  <input
                    type="radio"
                    name="scope-filter"
                    value={`sub:${s.id}`}
                    checked={scopeFilterMode === `sub:${s.id}`}
                    onChange={() => setScopeFilterMode(`sub:${s.id}`)}
                  />
                  <span>Only {s.name} topics</span>
                </label>
              ))}
            </div>
          )}

          {/* Phase 26 D2 — preselect-mode UI. When the modal was
              opened with preselectedUser (e.g. from DelegatePublic.jsx),
              show the preselected ResultCard directly and offer a
              "Choose someone else" link that resets to the search flow.
              Free-text search input is hidden in this mode. */}
          {preselectMode ? (
            <>
              {searching && !preselectedFull && (
                <p className="text-xs text-gray-400 text-center">Loading delegate...</p>
              )}
              {preselectedFull && (
                <div className="space-y-2">
                  <ResultCard
                    key={preselectedFull.id}
                    user={preselectedFull}
                    topicId={topicId}
                    onDone={onDone || onClose}
                    unverified={unverified}
                    scopeCoverage={scopeCoverage}
                    onCreateTopicScopedDelegations={createTopicScopedDelegations}
                    scopeFilterMode={scopeFilterMode}
                    defaultChainBehavior={defaultChainBehavior}
                    parentSlug={parentSlug}
                  />
                  <button
                    onClick={() => {
                      setPreselectMode(false);
                      setPreselectedFull(null);
                    }}
                    className="text-xs text-[var(--brand-accent)] hover:underline"
                  >
                    Choose someone else
                  </button>
                </div>
              )}
              {preselectError && (
                <p className="text-xs text-red-500">{preselectError}</p>
              )}
            </>
          ) : (
            <>
              <input
                autoFocus
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search by name or username..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              />
              {searching && <p className="text-xs text-gray-400 text-center">Searching...</p>}
              {results.length > 0 && (
                <div className="space-y-2">
                  {results.map(u => (
                    <ResultCard
                      key={u.id}
                      user={u}
                      topicId={topicId}
                      onDone={onDone || onClose}
                      unverified={unverified}
                      scopeCoverage={scopeCoverage}
                      onCreateTopicScopedDelegations={createTopicScopedDelegations}
                      scopeFilterMode={scopeFilterMode}
                      defaultChainBehavior={defaultChainBehavior}
                      parentSlug={parentSlug}
                    />
                  ))}
                </div>
              )}
              {query.length >= 2 && !searching && results.length === 0 && (
                <p className="text-sm text-gray-400 text-center">No users found</p>
              )}
              {query.length < 2 && (
                <p className="text-xs text-gray-400">Type at least 2 characters to search</p>
              )}
            </>
          )}
        </div>
        <div className="p-4 border-t border-gray-100">
          <button
            onClick={onClose}
            className="w-full py-2 border border-gray-200 text-gray-500 rounded-lg text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
