"""Optional pinned oracle: STARVOTE_REFERENCE_PATH points to isolated pip target.

Reference starvote==2.1.5, Larry Hastings, MIT license. No source copied into
production. We provide identical committed candidate priority to the reference;
all-bottom/no-ballot/single-option platform no-result rules are tested separately.
"""
import os
import random
import sys

import pytest

from experimental_tally import count_star
from voting_methods import candidate_priority, new_voting_rules


def test_star_matches_pinned_reference_on_2000_synthetic_profiles():
    path = os.environ.get("STARVOTE_REFERENCE_PATH")
    if path:
        sys.path.insert(0, path)
    starvote = pytest.importorskip("starvote", reason="Optional pinned synthetic oracle not installed")
    assert starvote.__version__ == "2.1.5"
    rng = random.Random(109)
    for _ in range(2000):
        ids = [str(i) for i in range(rng.randint(2, 8))]
        weighted = [({"scores": {oid: rng.randrange(6) for oid in ids}}, rng.randint(1, 4))
                    for _ in range(rng.randint(1, 12))]
        if not any(any(payload["scores"].values()) for payload, _ in weighted):
            continue
        rules = new_voting_rules("star", "p")
        priority = sorted(ids, key=lambda oid: candidate_priority(rules, "p", oid))
        reference_ballots = [payload["scores"] for payload, weight in weighted for _ in range(weight)]
        reference = starvote.star_voting(reference_ballots, tiebreaker=starvote.predefined_permutation_tiebreaker(priority), verbosity=0)
        assert count_star(ids, weighted, rules, "p").winners == reference
