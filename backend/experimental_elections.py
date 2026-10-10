"""Single-winner experimental election capability and atomic installation.

Counting is frozen before installation. The caller owns the close transaction;
expected policy rejection rolls back a savepoint, unexpected failures propagate.
Legacy election tally/fallback/assignment paths are deliberately untouched.
"""
from copy import deepcopy
from fastapi import HTTPException
import models
from voting_methods import EXPERIMENTAL_VOTING_METHODS


def validate_creation(proposal, db):
    from elections import elections_enabled, title_is_electable, trigger_source_enabled, allow_elected_revert
    from voting_capabilities import resolve_allowed_voting_methods
    from governance import mode_of, ADMIN_COUNCIL
    if db is None:
        raise ValueError('Election rules initialization requires a database session')
    org = db.get(models.Organization, proposal.org_id)
    scope = db.get(models.Organization, proposal.sub_org_id or proposal.org_id)
    title = db.get(models.OrgTitle, proposal.election_title_id) if proposal.election_title_id else None
    if org is None or scope is None or (proposal.sub_org_id and scope.parent_org_id != org.id):
        raise HTTPException(400, 'Election scope is invalid')
    if title is None or title.org_id != org.id or not title_is_electable(title):
        raise HTTPException(400, 'Election title must be electable in this organization')
    if not elections_enabled(org) or not trigger_source_enabled(org, proposal.election_trigger):
        raise HTTPException(400, 'Election or trigger is disabled')
    if proposal.voting_method not in EXPERIMENTAL_VOTING_METHODS or proposal.voting_method not in resolve_allowed_voting_methods(scope):
        raise HTTPException(400, 'Voting method is not enabled for this election scope')
    from voting_capabilities import validate_winner_count, require_new_method_choice
    try:
        validate_winner_count(proposal.num_winners)
        if proposal.num_winners > 1 or proposal.voting_method == "allocated_score":
            require_new_method_choice(scope, proposal.voting_method, proposal.num_winners)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if proposal.approval_winner_config is not None or proposal.budget_config is not None:
        raise HTTPException(400, 'This election method cannot use approval or budget configuration')
    if proposal.num_winners > 1 and (title.cardinality_mode == 'single' or title.bound_role == 'steward'):
        raise HTTPException(400, 'This title cannot have multiple elected occupants')
    if title.max_holders is not None and proposal.num_winners > title.max_holders:
        raise HTTPException(400, 'Winner count exceeds title capacity')
    if proposal.election_slate_mode not in ('fill_vacancies', 'refresh_slate'):
        raise HTTPException(400, 'Invalid election slate mode')
    if title.bound_role == 'steward' and mode_of(org) == ADMIN_COUNCIL and not allow_elected_revert(org):
        raise HTTPException(400, 'Elected revert is not authorized')
    membership = db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=proposal.author_id, status='active').first()
    if membership is None:
        raise HTTPException(403, 'An active organization member must open the election')
    role = db.get(models.Role, membership.role_id) if membership.role_id else None
    if proposal.election_trigger == 'admin_direct' and (role is None or role.system_key not in ('steward', 'admin')):
        raise HTTPException(403, 'Admin or steward role required')
    if proposal.election_trigger not in ('admin_direct', 'member_cosign'):
        raise HTTPException(400, 'Experimental scheduled method configuration is not supported')


def display_labels(proposal):
    return {option.id: (option.description or option.label) if proposal.is_election else option.label
            for option in proposal.options}


def freeze_election(proposal, tally, db):
    if proposal.num_winners > 1:
        from multiwinner_elections import freeze_election_set
        return freeze_election_set(proposal, tally, db)
    from elections import active_candidacies
    declared = {row.user_id for row in active_candidacies(db, proposal.id)}
    snapshot = {}
    for option in proposal.options:
        if option.label not in declared or option.label in [row['user_id'] for row in snapshot.values()]:
            raise ValueError('Election option does not map uniquely to an authorized candidate')
        snapshot[option.id] = {'user_id': option.label, 'display_name': option.description or option.label}
    if len(snapshot) != len(declared):
        raise ValueError('Election candidate options are not locked consistently')
    if len(tally.winners) > 1 or any(oid not in snapshot for oid in tally.winners):
        raise ValueError('Election tally has an invalid single winner')
    quorum = tally.quorum_met(proposal.quorum_threshold)
    winner_option = tally.winners[0] if tally.winners else None
    candidate_id = snapshot[winner_option]['user_id'] if winner_option else None
    policy = None
    reason = None
    if not quorum:
        reason = 'quorum_not_met'
    elif not snapshot:
        reason = 'no_candidates'
    elif len(snapshot) == 1:
        policy = 'uncontested'
        candidate_id = next(iter(snapshot.values()))['user_id']
    elif not winner_option:
        reason = tally.method_result['no_result_reason'] or 'no_meaningful_preference'
    return {'title_id': proposal.election_title_id, 'candidate_snapshot': snapshot,
            'counting_winner_option_id': winner_option, 'winner_user_id': candidate_id,
            'policy': policy, 'installation': 'pending', 'reason': reason}


def _active_member(db, proposal, user_id):
    member = db.query(models.OrgMembership).filter_by(org_id=proposal.org_id, user_id=user_id, status='active').first()
    if member is None:
        raise HTTPException(400, 'winner_not_active_member')
    if proposal.sub_org_id and not db.query(models.SubOrgMembership).filter_by(sub_org_id=proposal.sub_org_id, user_id=user_id, status='active').first():
        raise HTTPException(400, 'winner_not_suborg_member')
    return member


def _preflight_role(db, org, title, winner, member):
    from governance import mode_of, ADMIN_COUNCIL
    from elections import allow_elected_revert
    from routes.org_titles import _check_revoke_floor
    role = db.get(models.Role, member.role_id) if member.role_id else None
    authorized_revert = title.bound_role == 'steward' and mode_of(org) == ADMIN_COUNCIL and allow_elected_revert(org)
    if title.bound_role and role and role.system_key != title.bound_role and not authorized_revert:
        _check_revoke_floor(db, org, winner.id, role.system_key)
    if title.bound_role == 'steward' and mode_of(org) == ADMIN_COUNCIL and not allow_elected_revert(org):
        raise HTTPException(400, 'revert_not_authorized')
    pending_verification = False
    if title.bound_role and (not role or role.system_key != title.bound_role):
        if not db.query(models.Role).filter_by(org_id=org.id, system_key=title.bound_role).first():
            raise ValueError('Organization is missing the election bound role')
        from verification import check_role_grant_floor, check_role_residency_for_grant
        try:
            check_role_grant_floor(winner, org, title.bound_role)
            check_role_residency_for_grant(winner, org, title.bound_role)
        except HTTPException as exc:
            if exc.status_code == 403 and isinstance(exc.detail, dict) and exc.detail.get('error') == 'verification_required':
                pending_verification = True
            else:
                raise
    return pending_verification


def _install_frozen(db, proposal, *, actor_id=None, ip_address=None):
    if proposal.num_winners > 1:
        from multiwinner_elections import install_frozen_set
        return install_frozen_set(db, proposal, actor_id=actor_id, ip_address=ip_address)
    from audit_utils import log_audit_event
    from elections import (_apply_election_winner, _cap_winners_to_title_capacity,
        _refresh_slate_for_title, _advance_schedule_for_title, _flip_mode_to_single_steward)
    from governance import mode_of, ADMIN_COUNCIL
    record = deepcopy(proposal.final_method_result)
    if not record or 'election' not in record:
        raise ValueError('Experimental election must have a frozen result before assignment')
    outcome = record['election']
    if outcome['installation'] != 'pending':
        return record['status']
    # Lock title/organization state in addition to the already-locked proposal.
    org = db.query(models.Organization).filter_by(id=proposal.org_id).with_for_update().populate_existing().one()
    title = db.query(models.OrgTitle).filter_by(id=proposal.election_title_id, org_id=org.id).with_for_update().populate_existing().one()
    db.query(models.OrgMembership).filter_by(org_id=org.id).with_for_update().populate_existing().all()
    if outcome['reason']:
        outcome['installation'] = 'not_installed'
    else:
        winner = db.query(models.User).filter_by(id=outcome['winner_user_id']).with_for_update().populate_existing().one_or_none()
        try:
            if winner is None or not winner.is_active:
                raise HTTPException(400, 'winner_inactive')
            member = _active_member(db, proposal, winner.id)
            pending = _preflight_role(db, org, title, winner, member)
            from elections import title_is_electable
            if not title_is_electable(title):
                raise HTTPException(400, 'title_no_longer_electable')
            seated, overflow = _cap_winners_to_title_capacity(db, title, [winner.id], slate_mode=proposal.election_slate_mode)
            if not seated or overflow:
                raise HTTPException(400, 'title_capacity_unavailable')
            # Verification-pending system titles are role-derived, so there is
            # no label assignment to grant. Keep current roles/slate intact.
            if pending:
                outcome['installation'] = 'pending_verification'
                outcome['reason'] = 'verification_required'
                outcome['title_granted'] = False
            else:
                # Expected rejections during assignment/refresh roll back every
                # seat and role mutation, including any earlier slate removals.
                with db.begin_nested():
                    if proposal.election_slate_mode == 'refresh_slate':
                        _refresh_slate_for_title(db, org, title, [winner.id], actor_id=actor_id, ip_address=ip_address)
                    if title.bound_role == 'steward' and mode_of(org) == ADMIN_COUNCIL:
                        _flip_mode_to_single_steward(db, org, actor_id=actor_id, ip_address=ip_address, proposal_id=proposal.id)
                    from org_titles import is_holder
                    if title.is_system or not is_holder(db, title.id, winner.id):
                        _apply_election_winner(db, org, title, winner, actor_id=actor_id, ip_address=ip_address)
                    elif title.bound_role:
                        from routes.org_titles import _apply_bound_role_for_assign
                        from types import SimpleNamespace
                        _apply_bound_role_for_assign(db, org, winner, title.bound_role, SimpleNamespace(client=SimpleNamespace(host=ip_address)))
                    db.flush()
                outcome['installation'] = 'installed'
                outcome['title_granted'] = True
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise
            outcome['installation'] = 'rejected'
            outcome['reason'] = str(exc.detail)
            outcome['title_granted'] = False
    if proposal.election_trigger == 'scheduled':
        _advance_schedule_for_title(db, title)
    log_audit_event(db, action='election.resolved', target_type='proposal', target_id=proposal.id,
                    actor_id=actor_id, ip_address=ip_address,
                    details={**outcome, 'proposal_id': proposal.id, 'method': proposal.voting_method})
    proposal.final_method_result = record
    db.flush()
    return record['status']


def install_frozen(db, proposal, *, actor_id=None, ip_address=None):
    try:
        return _install_frozen(db, proposal, actor_id=actor_id, ip_address=ip_address)
    except Exception:
        db.rollback()
        raise


def announcement(outcome):
    """Human-readable close intent, using only the frozen identity snapshot."""
    if outcome.get('outcome_version') == 2:
        from multiwinner_elections import announcement_set
        return announcement_set(outcome)
    name = next((row['display_name'] for row in outcome['candidate_snapshot'].values()
                 if row['user_id'] == outcome['winner_user_id']), 'The recorded winner')
    if outcome['installation'] == 'installed':
        prefix = 'Uncontested election' if outcome['policy'] == 'uncontested' else 'Elected'
        return f'{prefix}: {name}. Office installation completed.'
    if outcome['installation'] == 'pending_verification':
        return f'{name} won; office installation is pending verification. No bound-role access was granted.'
    if outcome['installation'] == 'rejected':
        return f'{name} won but could not be installed. Existing seats and roles were preserved.'
    if outcome['reason'] == 'quorum_not_met':
        return 'Quorum not met; no seats were changed.'
    if outcome['reason'] == 'no_candidates':
        return 'No candidates; no seats were changed.'
    return 'No meaningful preference; no officeholder was installed.'
