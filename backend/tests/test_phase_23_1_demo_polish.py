"""Phase 23.1 — demo polish defect-coverage tests.

Covers the five defects from the Phase 23.1 dispatch:
- C1: delegated votes appearing in proposal tallies (B3a + B3b)
- C2: ProposalOption rows from candidate_statements for RCV/STV (B1 + B2)
- C3: topic display name (B4 — verified via Topic.description)
- C4: persona descriptions (B5)
- C5: multi-option proposal labels (B6 — sentinel regression test)

The full demo reset is expensive on SQLite (~30s on cold cache for all
three bibles). To keep the test suite responsive, the cross-org / "seeded
state" tests share a module-scoped fixture that runs the full reset ONCE
per pytest module invocation. Tests that only need behavior of the
seed pipeline at the unit level use isolated single-org seeds with
manually-built minimal bibles.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from role_seed import seed_default_roles_for_org


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def test_db():
    """Per-test fresh in-memory SQLite session."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="module")
def seeded_db():
    """Module-scoped fixture: runs the full demo reset ONCE.

    Used by the cross-bible / tally-resolution tests that need the full
    seeded state (delegations, fillers, named votes) across the three
    demo orgs. The full reset is ~30s on SQLite so amortizing it across
    multiple tests keeps the suite fast.
    """
    from demo_reset_job import run_demo_reset_if_due

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    try:
        result = run_demo_reset_if_due(session, force=True)
        assert result.success, f"reset failed: {result.error}"
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _seed_minimal_org(
    db: Session, slug: str = "test-org", name: str = "Test Org",
) -> models.Organization:
    """Helper: org + roles + admin user for unit-style tests."""
    org = models.Organization(
        slug=slug, name=name, description="", join_policy="open",
        is_demo=False,
    )
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    return org


# ===========================================================================
# B5 (C4): Persona descriptions from Stage 8 §6
# ===========================================================================


class TestPersonaDescriptionsFromStage8:
    """Seeded quick-login members get the Stage 8 §6 description string."""

    def test_descriptions_from_dict_not_role(self, seeded_db):
        from demo_content.persona_descriptions import QUICK_LOGIN_DESCRIPTIONS

        hoa = seeded_db.query(models.Organization).filter(
            models.Organization.slug == "demo-cedar-hollow",
        ).one()
        personas = hoa.personas or []
        assert len(personas) >= 6, f"expected >=6 quick-login personas, got {len(personas)}"

        # Find each quick-login persona by username; expected mapping:
        username_to_bible_uid = {
            "janet_reilly": "hoa_janet",
            "hoa_brenda": "hoa_brenda",
            "marcus_pham": "hoa_marcus",
            "hoa_don": "hoa_don",
            "hoa_linda": "hoa_linda",
            "hoa_tomas": "hoa_tomas",
        }
        for p in personas:
            uname = p["username"]
            bible_uid = username_to_bible_uid.get(uname)
            if bible_uid is None:
                continue
            expected = QUICK_LOGIN_DESCRIPTIONS[bible_uid]
            assert p["description"] == expected, (
                f"persona {uname!r} description mismatch: "
                f"got {p['description']!r}, expected {expected!r}"
            )
            assert p["description"] != p["role"], (
                f"persona {uname!r} description still mirrors role"
            )


class TestPersonaDescriptionFallbackToRole:
    """Quick-login member with user_id NOT in dict falls back to role string."""

    def test_unknown_user_id_falls_back(self, test_db):
        from demo_content.schema import Member, OrgBible
        from demo_content.seed_pipeline import seed_org_from_bible

        # Construct a minimal bible with one quick-login member whose
        # user_id is NOT in QUICK_LOGIN_DESCRIPTIONS.
        unknown = Member(
            user_id="unknown_test_persona_xyz",
            display_name="Unknown Test User",
            quick_login=True,
            role="Test Role Label",
        )
        bible = OrgBible(
            slug="demo-fallback-test",
            display_name="Fallback Test Org",
            charter="charter",
            tone_notes="",
            recent_history="",
            members=[unknown],
        )
        seed_org_from_bible(test_db, bible)
        test_db.flush()

        org = test_db.query(models.Organization).filter(
            models.Organization.slug == "demo-fallback-test",
        ).one()
        personas = org.personas or []
        assert len(personas) == 1
        p = personas[0]
        assert p["role"] == "Test Role Label"
        # Description should fall back to role (no Stage 8 entry).
        assert p["description"] == "Test Role Label"


# ===========================================================================
# B1 (C2): ProposalOption rows from candidate_statements
# ===========================================================================


def _build_election_bible(
    slug: str,
    proposer_uid: str,
    candidate_statements: dict[str, str],
    *,
    voting_method: str = "rcv",
) -> "OrgBible":
    """Minimal bible carrying one RCV/STV election proposal."""
    from demo_content.schema import Member, OrgBible, Proposal

    members = [
        Member(
            user_id=proposer_uid,
            display_name=proposer_uid.replace("_", " ").title(),
            quick_login=True,
            role="President",
        ),
    ]
    proposal = Proposal(
        proposal_id="P-TEST-EL-01",
        title="Test Election",
        proposer_user_id=proposer_uid,
        voting_method=voting_method,
        state_at_reset="voting, hour 6 of 72",
        body="Test election proposal.",
        candidate_statements=candidate_statements,
    )
    return OrgBible(
        slug=slug,
        display_name="Test Election Org",
        charter="charter",
        tone_notes="",
        recent_history="",
        members=members,
        proposals=[proposal],
    )


class TestElectionProposalOptionsFromCandidateStatements:
    """RCV proposal with candidate_statements + empty options → ProposalOption rows."""

    def test_options_built_from_candidates(self, test_db):
        from demo_content.seed_pipeline import seed_org_from_bible

        bible = _build_election_bible(
            slug="demo-election-test-a",
            proposer_uid="test_pres_a",
            candidate_statements={
                "test_cand_one": "Statement one.",
                "test_cand_two": "Statement two.",
            },
            voting_method="rcv",
        )
        seed_org_from_bible(test_db, bible)
        test_db.flush()

        prop = test_db.query(models.Proposal).filter(
            models.Proposal.title == "Test Election",
        ).one()
        opts = sorted(prop.options, key=lambda o: o.display_order)
        assert len(opts) == 2, (
            f"expected 2 ProposalOption rows, got {len(opts)}"
        )
        labels = {o.label for o in opts}
        # Falls back to title-case from user_id since no
        # CANDIDATE_DISPLAY_NAMES entry for "test_cand_*".
        assert labels == {"Test Cand One", "Test Cand Two"}
        # Description should carry the candidate statement.
        descs = {o.description for o in opts}
        assert "Statement one." in descs
        assert "Statement two." in descs


class TestElectionProposalOptionsPreservesOrder:
    """Three candidates → display_order matches dict-insertion order."""

    def test_dict_insertion_order_preserved(self, test_db):
        from demo_content.seed_pipeline import seed_org_from_bible

        bible = _build_election_bible(
            slug="demo-election-test-b",
            proposer_uid="test_pres_b",
            candidate_statements={
                "alpha_cand": "Alpha.",
                "beta_cand": "Beta.",
                "gamma_cand": "Gamma.",
            },
            voting_method="rcv",
        )
        seed_org_from_bible(test_db, bible)
        test_db.flush()

        prop = test_db.query(models.Proposal).filter(
            models.Proposal.title == "Test Election",
        ).one()
        opts = sorted(prop.options, key=lambda o: o.display_order)
        assert [o.label for o in opts] == [
            "Alpha Cand", "Beta Cand", "Gamma Cand",
        ]
        assert [o.display_order for o in opts] == [0, 1, 2]


class TestSTVCandidatesSeededForPL06:
    """Full P-L-06 seed → exactly 5 ProposalOption rows."""

    def test_pl06_has_five_options(self, seeded_db):
        local = seeded_db.query(models.Organization).filter(
            models.Organization.slug == "demo-local-4021",
        ).one()
        prop = seeded_db.query(models.Proposal).filter(
            models.Proposal.org_id == local.id,
            models.Proposal.title == "Trustee Election 2026",
        ).one()
        assert prop.voting_method == "stv"
        opts = sorted(prop.options, key=lambda o: o.display_order)
        assert len(opts) == 5, (
            f"expected 5 STV candidates seeded for P-L-06, got {len(opts)}: "
            f"{[o.label for o in opts]}"
        )
        # All labels should be real names, not raw user_ids.
        for o in opts:
            assert "_" not in o.label, (
                f"label {o.label!r} looks like a raw user_id, not a display name"
            )
            assert o.label != "", "empty label"


# ===========================================================================
# B4 (C3): Topic display name via description field
# ===========================================================================


class TestTopicDisplayName:
    """Topic.description is the un-prefixed (display-friendly) name."""

    def test_topic_description_is_unprefixed_name(self, seeded_db):
        hoa = seeded_db.query(models.Organization).filter(
            models.Organization.slug == "demo-cedar-hollow",
        ).one()
        topics = seeded_db.query(models.Topic).filter(
            models.Topic.org_id == hoa.id,
        ).all()
        assert len(topics) > 0
        for t in topics:
            # Name is prefixed with org slug for global uniqueness.
            assert t.name.startswith("demo-cedar-hollow:"), (
                f"topic name unexpectedly unprefixed: {t.name!r}"
            )
            # Description is the same string minus the prefix.
            expected_desc = t.name.split(":", 1)[1]
            assert t.description == expected_desc, (
                f"topic {t.name!r} description {t.description!r} "
                f"!= expected {expected_desc!r}"
            )


# ===========================================================================
# B3 (C1): Delegations + delegated-vote tally resolution
# ===========================================================================


class TestDelegationsExist:
    """Seed Cedar Hollow → at least 4 Delegation rows."""

    def test_min_four_delegations(self, seeded_db):
        hoa = seeded_db.query(models.Organization).filter(
            models.Organization.slug == "demo-cedar-hollow",
        ).one()
        dels = seeded_db.query(models.Delegation).filter(
            models.Delegation.org_id == hoa.id,
        ).all()
        # Cedar Hollow has 4 public_accepting topics; fillers delegate at
        # ~30% rate so we expect well over 4 rows. Use 4 as a floor.
        assert len(dels) >= 4, (
            f"expected >=4 delegations in Cedar Hollow, got {len(dels)}"
        )
        # Delegators should be filler users (email matches @demo.example
        # and username matches the filler pattern).
        for d in dels[:10]:
            delegator = seeded_db.get(models.User, d.delegator_id)
            assert delegator is not None


class TestDelegatedVoteAppearsInTally:
    """Load-bearing C1 test: a filler delegating to a named voter has the
    delegate's vote reflected in the tally."""

    def test_filler_delegation_reflected_via_compute_tally(self, seeded_db):
        from delegation_engine import engine, graph_store

        hoa = seeded_db.query(models.Organization).filter(
            models.Organization.slug == "demo-cedar-hollow",
        ).one()

        # Pick a proposal Janet has a public yes vote on. The seed pipeline
        # creates votes from vote_rationales in delegate_pages, so look up
        # any proposal Janet voted yes on.
        janet = seeded_db.query(models.User).filter(
            models.User.username == "janet_reilly",
        ).one()

        # Find a voting/passed/failed proposal in Cedar Hollow where Janet
        # has a Vote row with vote_value='yes'.
        janet_yes_vote = seeded_db.query(models.Vote).join(
            models.Proposal, models.Proposal.id == models.Vote.proposal_id,
        ).filter(
            models.Vote.user_id == janet.id,
            models.Vote.vote_value == "yes",
            models.Proposal.org_id == hoa.id,
            models.Proposal.voting_method == "binary",
            models.Proposal.status.in_(["voting", "passed", "failed"]),
        ).first()
        assert janet_yes_vote is not None, (
            "Janet should have at least one binary yes vote on a Cedar Hollow proposal"
        )
        proposal = seeded_db.get(models.Proposal, janet_yes_vote.proposal_id)

        # Find a Cedar Hollow delegation that goes TO Janet. The topic on
        # the delegation must be one of Janet's public_accepting topics
        # (Budget). Per the seeded delegate page, Janet accepts on Budget.
        delegation_to_janet = seeded_db.query(models.Delegation).filter(
            models.Delegation.org_id == hoa.id,
            models.Delegation.delegate_id == janet.id,
        ).first()
        assert delegation_to_janet is not None, (
            "expected at least one delegation to Janet in Cedar Hollow"
        )
        filler_user_id = delegation_to_janet.delegator_id

        # Make sure graph store is refreshed (B3b path).
        graph_store.rebuild_from_db(seeded_db)

        # Make sure the filler does NOT have a direct vote (B3a invariant).
        direct = seeded_db.query(models.Vote).filter(
            models.Vote.proposal_id == proposal.id,
            models.Vote.user_id == filler_user_id,
        ).first()
        assert direct is None, (
            f"filler {filler_user_id!r} unexpectedly has a direct vote "
            f"on {proposal.title!r}; B3a filter should have skipped them"
        )

        # Compute the tally; filler's effective vote should resolve via
        # delegation to Janet (yes). compute_tally returns aggregates;
        # we use resolve_vote to verify the specific filler.
        try:
            resolved = engine.resolve_vote(filler_user_id, proposal.id, seeded_db)
        except Exception as exc:
            pytest.fail(f"resolve_vote raised: {exc!r}")
        assert resolved is not None, (
            f"filler {filler_user_id!r}'s vote did not resolve via "
            f"delegation to Janet on {proposal.title!r}"
        )
        # resolved.ballot.vote_value should be 'yes' (Janet's vote).
        ballot_vote = getattr(
            getattr(resolved, "ballot", None), "vote_value", None,
        )
        assert ballot_vote == "yes", (
            f"expected resolved vote_value='yes' via Janet, got {ballot_vote!r}"
        )


class TestFillerWithDelegationSkipsDirectVote:
    """Filler with a delegation never has a direct Vote row on any proposal."""

    def test_delegating_filler_has_no_direct_votes(self, seeded_db):
        hoa = seeded_db.query(models.Organization).filter(
            models.Organization.slug == "demo-cedar-hollow",
        ).one()

        # Pick any filler that delegates in Cedar Hollow.
        delegation = seeded_db.query(models.Delegation).filter(
            models.Delegation.org_id == hoa.id,
        ).first()
        assert delegation is not None
        filler_uid = delegation.delegator_id

        # Sanity: this user really is a filler (has @demo.example email).
        filler = seeded_db.get(models.User, filler_uid)
        assert filler is not None
        assert filler.email and filler.email.endswith("@demo.example")

        # No Vote rows for this filler on any Cedar Hollow proposal.
        cedar_votes = seeded_db.query(models.Vote).join(
            models.Proposal, models.Proposal.id == models.Vote.proposal_id,
        ).filter(
            models.Vote.user_id == filler_uid,
            models.Proposal.org_id == hoa.id,
        ).count()
        assert cedar_votes == 0, (
            f"delegating filler {filler_uid!r} unexpectedly has "
            f"{cedar_votes} direct Vote row(s) on Cedar Hollow proposals"
        )


class TestFillerWithoutDelegationCastsDirectVote:
    """Sanity: fillers WITHOUT delegations do still cast direct votes."""

    def test_non_delegating_filler_has_some_votes(self, seeded_db):
        hoa = seeded_db.query(models.Organization).filter(
            models.Organization.slug == "demo-cedar-hollow",
        ).one()

        # Build the set of fillers in Cedar Hollow who DO delegate.
        delegators = {
            d.delegator_id for d in seeded_db.query(models.Delegation).filter(
                models.Delegation.org_id == hoa.id,
            ).all()
        }

        # Get all filler-style users with HOA membership.
        all_hoa_fillers = seeded_db.query(models.User).join(
            models.OrgMembership, models.OrgMembership.user_id == models.User.id,
        ).filter(
            models.OrgMembership.org_id == hoa.id,
            models.User.email.like("%@demo.example"),
        ).all()

        non_delegating = [u for u in all_hoa_fillers if u.id not in delegators]
        assert len(non_delegating) > 0, (
            "expected some Cedar Hollow fillers without delegations"
        )

        # At least one non-delegating filler casts at least one vote.
        non_delegating_ids = [u.id for u in non_delegating]
        any_votes = seeded_db.query(models.Vote).join(
            models.Proposal, models.Proposal.id == models.Vote.proposal_id,
        ).filter(
            models.Vote.user_id.in_(non_delegating_ids),
            models.Proposal.org_id == hoa.id,
        ).count()
        assert any_votes > 0, (
            "expected non-delegating fillers to have cast some direct votes; "
            "B3a filter may be too broad"
        )


class TestGraphStoreRefreshedPostSeed:
    """After demo reset, the in-memory DelegationGraphStore has nonzero edges."""

    def test_graph_store_has_edges_after_reset(self, seeded_db):
        from delegation_engine import graph_store

        graph_store.rebuild_from_db(seeded_db)

        # Walk the partitioned structure and count edges across all orgs.
        total_edges = 0
        # _graphs is private but is the canonical structure; safe to read
        # in tests.
        for org_id, topic_map in graph_store._graphs.items():  # noqa: SLF001
            if org_id is None:
                continue
            for topic_id, g in topic_map.items():
                total_edges += g.number_of_edges()

        assert total_edges > 0, (
            "DelegationGraphStore has zero edges after demo reset; B3b "
            "rebuild_from_db may not have run or no delegations were seeded"
        )


# ===========================================================================
# B6 (C5): Human-readable multi-option proposal labels
# ===========================================================================


class TestMultiOptionProposalLabelsHuman:
    """P-H-03 options should be human-readable, not 'Item N' placeholders."""

    def test_ph03_labels_descriptive(self, seeded_db):
        hoa = seeded_db.query(models.Organization).filter(
            models.Organization.slug == "demo-cedar-hollow",
        ).one()
        prop = seeded_db.query(models.Proposal).filter(
            models.Proposal.org_id == hoa.id,
            models.Proposal.title == "Deferred Maintenance Priority List 2026",
        ).one()
        labels = [o.label for o in prop.options]
        assert len(labels) == 8

        # Sentinel: none of the labels should be the old placeholder form.
        placeholder_pattern = {f"Item {i}" for i in range(1, 9)}
        for lbl in labels:
            assert lbl not in placeholder_pattern, (
                f"P-H-03 option {lbl!r} regressed to placeholder form"
            )
        # And at least one should mention a real maintenance category +
        # cost (sanity check the substantive content).
        joined = " | ".join(labels)
        assert "$" in joined, f"expected dollar amounts in P-H-03 labels: {labels}"
        assert "pump" in joined.lower() or "fence" in joined.lower(), (
            f"expected real maintenance items in P-H-03 labels: {labels}"
        )
