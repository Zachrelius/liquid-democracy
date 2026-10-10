"""Pure exact-integer counters for the released experimental methods.

STAR follows Phase 109 v1, compared against starvote 2.1.5 (MIT).
No reference package is imported by production and no shares are expanded.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from fractions import Fraction

from experimental_ballots import MAX_BALLOT_OPTIONS, validate_ballot
from voting_methods import GRADE_LABELS, RULE_IDS, candidate_priority, option_set_version, validate_voting_rules


@dataclass
class ExperimentalTally:
    method_result: dict
    total_eligible: int = 0
    total_ballots_cast: int = 0
    total_abstain: int = 0
    not_cast: int = 0
    eligible_headcount: int = 0
    participating_headcount: int = 0

    @property
    def votes_cast(self):
        return self.total_ballots_cast

    @property
    def winners(self):
        if "winners" in self.method_result:
            return list(self.method_result["winners"])
        winner = self.method_result["winner"]
        return [winner] if winner is not None else []

    @property
    def tied(self):
        return self.method_result["priority_used"]

    def quorum_met(self, threshold):
        # Fraction cross-products stay exact beyond Decimal's default 28-digit
        # context and never round an almost-met quorum up to the threshold.
        ratio = Fraction(str(threshold))
        return (self.total_eligible > 0 and
                self.total_ballots_cast * ratio.denominator >= self.total_eligible * ratio.numerator)

    def to_record(self):
        return asdict(self)

    @classmethod
    def from_record(cls, record):
        if not isinstance(record, dict) or not isinstance(record.get("tally"), dict):
            raise ValueError("Final experimental tally record is missing")
        value = deepcopy(record["tally"])
        required = {"method_result", "total_eligible", "total_ballots_cast", "total_abstain",
                    "not_cast", "eligible_headcount", "participating_headcount"}
        if set(value) != required:
            raise ValueError("Final experimental tally record is incompatible")
        for key in required - {"method_result"}:
            if type(value[key]) is not int or value[key] < 0:
                raise ValueError("Invalid persisted participation count")
        result = value["method_result"]
        if record.get("record_version") == 2:
            if not isinstance(result, dict): raise ValueError("Invalid multiwinner result")
            from multiwinner_tally import validate_multiwinner_record
            if value["total_ballots_cast"] + value["not_cast"] != value["total_eligible"] or value["total_abstain"] > value["total_ballots_cast"]:
                raise ValueError("Inconsistent persisted participation count")
            validate_multiwinner_record(result,record,value["total_ballots_cast"]-value["total_abstain"])
            if record.get("method") != result.get("method"):
                raise ValueError("Frozen method contradicts tally")
            return cls(**value)
        if (not isinstance(result, dict) or result.get("method") not in RULE_IDS
                or result.get("rule_id") != RULE_IDS[result["method"]]
                or type(result.get("priority_used")) is not bool
                or "winner" not in result or "no_result_reason" not in result):
            raise ValueError("Invalid persisted experimental method result")
        if "method" in record and record["method"] != result["method"]:
            raise ValueError("Persisted record method contradicts tally")
        if "rules" in record:
            rules = record["rules"]
            if (not isinstance(rules, dict) or rules.get("method") != result["method"]
                    or rules.get("rule_id") != result["rule_id"]):
                raise ValueError("Persisted record rules contradict tally")
        if value["total_ballots_cast"] + value["not_cast"] != value["total_eligible"]:
            raise ValueError("Inconsistent persisted participation count")
        if value["total_abstain"] > value["total_ballots_cast"]:
            raise ValueError("Inconsistent persisted abstention count")
        if result["method"] == "majority_judgment":
            _validate_mj_record(result, value["total_ballots_cast"] - value["total_abstain"], record)
            return cls(**value)
        if result["method"] == "ranked_pairs":
            _validate_ranked_pairs_record(result, value["total_ballots_cast"] - value["total_abstain"], record)
            return cls(**value)
        scores = result.get("scores")
        histograms = result.get("score_histograms")
        is_star = result["method"] == "star"
        five = result.get("five_star_counts")
        finalists = result.get("finalists") if is_star else []
        runoff = result.get("runoff") if is_star else {}
        preference_weight = value["total_ballots_cast"] - value["total_abstain"]
        if (not isinstance(scores, dict) or len(scores) > MAX_BALLOT_OPTIONS
                or not isinstance(histograms, dict) or set(histograms) != set(scores)
                or (is_star and (not isinstance(five, dict) or set(five) != set(scores)))
                or not isinstance(finalists, list) or len(finalists) != len(set(finalists))
                or any(oid not in scores for oid in finalists)
                or not isinstance(runoff, dict) or set(runoff) != set(finalists)
                or result.get("preference_weight") != preference_weight
                or not isinstance(result.get("tie_trace"), list)):
            raise ValueError("Inconsistent persisted rating aggregates")
        if not is_star and any(key in result for key in ("finalists", "runoff", "five_star_counts", "equal_preference")):
            raise ValueError("Persisted Score result contains STAR-only fields")
        if result.get("option_set_version") != option_set_version(scores):
            raise ValueError("Invalid persisted option set version")
        for oid, score in scores.items():
            histogram = histograms[oid]
            if (type(score) is not int or score < 0 or not isinstance(histogram, list)
                    or len(histogram) != 6 or any(type(n) is not int or n < 0 for n in histogram)
                    or sum(histogram) != preference_weight
                    or (is_star and (type(five[oid]) is not int or five[oid] != histogram[5]))
                    or sum(grade * n for grade, n in enumerate(histogram)) != score):
                raise ValueError("Invalid persisted score histogram")
        if result["winner"] is not None and not is_star:
            if (len(scores) < 2 or not any(scores.values())
                    or result["winner"] not in scores or result["no_result_reason"] is not None
                    or scores[result["winner"]] != max(scores.values())):
                raise ValueError("Invalid persisted Score winner")
            tied = sum(n == max(scores.values()) for n in scores.values()) > 1
            if result["priority_used"] != tied:
                raise ValueError("Persisted Score tie contradicts priority use")
        elif result["winner"] is not None:
            if (len(finalists) != 2 or result["winner"] not in finalists
                    or result["no_result_reason"] is not None
                    or any(type(n) is not int or n < 0 for n in runoff.values())
                    or type(result.get("equal_preference")) is not int
                    or result["equal_preference"] < 0
                    or sum(runoff.values()) + result["equal_preference"] != preference_weight):
                raise ValueError("Invalid persisted STAR runoff")
            possible = finalists
            for values in (runoff, scores, five):
                highest = max(values[oid] for oid in possible)
                possible = [oid for oid in possible if values[oid] == highest]
                if len(possible) == 1:
                    break
            if result["winner"] not in possible:
                raise ValueError("Persisted winner contradicts STAR runoff")
            if len(possible) > 1 and not result["priority_used"]:
                raise ValueError("Persisted STAR tie omitted priority use")
        elif result["no_result_reason"] not in (
                "fewer_than_two_options", "no_positive_weight_preferences", "all_bottom_ratings"):
            raise ValueError("Missing persisted no-result reason")
        if (result["no_result_reason"] == "all_bottom_ratings" and any(scores.values())
                or result["no_result_reason"] == "no_positive_weight_preferences" and preference_weight != 0
                or result["no_result_reason"] == "fewer_than_two_options" and len(scores) >= 2):
            raise ValueError("Persisted no-result reason contradicts aggregates")
        return cls(**value)


def public_tally(tally: ExperimentalTally) -> dict:
    """Transport exact counts as decimal strings; never lose JS precision."""
    def convert(value):
        if type(value) is int:
            return str(value)
        if isinstance(value, dict):
            return {key: deepcopy(item) if key == "majority_grades" else convert(item)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value
    return convert(tally.to_record())


def _rated_totals(method, option_ids, weighted_ballots, rules, proposal_id):
    """Shared rating aggregation; method-specific winner selection stays separate."""
    validate_voting_rules(rules, method, proposal_id)
    ids = list(option_ids)
    if len(ids) > MAX_BALLOT_OPTIONS:
        raise ValueError("Too many voting options")
    version = option_set_version(ids)  # also checks duplicate IDs
    scores = dict.fromkeys(ids, 0)
    histograms = {oid: [0] * 6 for oid in ids}
    preference_ballots = []
    total = abstain = headcount = 0
    for payload, weight in weighted_ballots:
        if type(weight) is not int or weight < 0:
            raise ValueError("Voting weight must be a nonnegative integer")
        ballot = validate_ballot(method, payload, ids)
        total += weight
        headcount += 1
        if ballot.get("abstain"):
            abstain += weight
            continue
        if not weight:
            continue
        ratings = ballot["scores"]
        preference_ballots.append((ratings, weight))
        for oid in ids:
            rating = ratings.get(oid, 0)
            scores[oid] += rating * weight
            histograms[oid][rating] += weight
    result = {
        "method": method, "rule_id": rules["rule_id"], "scores": scores,
        "score_histograms": histograms,
        "preference_weight": total - abstain,
        "winner": None, "tie_trace": [], "priority_used": False,
        "no_result_reason": None, "option_set_version": version,
    }
    tally = ExperimentalTally(result, total_eligible=total, total_ballots_cast=total,
                              total_abstain=abstain, eligible_headcount=headcount,
                              participating_headcount=headcount)
    if len(ids) < 2:
        result["no_result_reason"] = "fewer_than_two_options"
    elif not preference_ballots:
        result["no_result_reason"] = "no_positive_weight_preferences"
    elif not any(scores.values()):
        result["no_result_reason"] = "all_bottom_ratings"
    return tally, preference_ballots, ids


def count_score(option_ids, weighted_ballots, rules, proposal_id) -> ExperimentalTally:
    tally, _, ids = _rated_totals("score", option_ids, weighted_ballots, rules, proposal_id)
    result = tally.method_result
    if result["no_result_reason"]:
        return tally
    maximum = max(result["scores"].values())
    tied = [oid for oid in ids if result["scores"][oid] == maximum]
    if len(tied) > 1:
        result["priority_used"] = True
        result["tie_trace"] = [{"stage": "score_priority", "pool": sorted(tied)}]
    result["winner"] = min(tied, key=lambda oid: candidate_priority(rules, proposal_id, oid))
    return tally


def _lower_median(histogram):
    target = (sum(histogram) + 1) // 2
    if target == 0:
        return None
    cumulative = 0
    for grade, count in enumerate(histogram):
        cumulative += count
        if cumulative >= target:
            return grade


def _median_pair_runs(histogram):
    """Run-length encode the exact median-removal sequence in pairs.

    For even N=2k, removal visits sorted positions k,k+1,k-1,k+2,... .
    For odd N=2k+1, first remove k+1, then k,k+2,k-1,k+3,... .
    The descending lower half and ascending upper half therefore interleave.
    Six histogram bins produce at most eleven pair runs, regardless of N.
    """
    remaining = list(histogram)
    needed = sum(remaining) // 2
    lower = []
    for grade in range(6):
        take = min(needed, remaining[grade])
        if take:
            lower.append([grade, take])
            remaining[grade] -= take
            needed -= take
    if sum(histogram) % 2:
        remaining[next(g for g, n in enumerate(remaining) if n)] -= 1
    lower.reverse()
    upper = [[g, n] for g, n in enumerate(remaining) if n]
    runs = []
    left = right = 0
    while left < len(lower):
        take = min(lower[left][1], upper[right][1])
        runs.append((lower[left][0], upper[right][0], take))
        lower[left][1] -= take
        upper[right][1] -= take
        if not lower[left][1]:
            left += 1
        if not upper[right][1]:
            right += 1
    return runs


def _mj_outcome(histograms, priority):
    initial = {oid: _lower_median(histogram) for oid, histogram in histograms.items()}
    best = max(initial.values())
    pool = sorted(oid for oid in histograms if initial[oid] == best)
    trace = []
    runs = {oid: _median_pair_runs(histograms[oid]) for oid in pool}
    positions = dict.fromkeys(pool, 0)
    consumed = dict.fromkeys(pool, 0)
    removed = sum(next(iter(histograms.values()))) % 2
    while len(pool) > 1 and positions[pool[0]] < len(runs[pool[0]]):
        for half in (0, 1):
            grades = {oid: runs[oid][positions[oid]][half] for oid in pool}
            maximum = max(grades.values())
            survivors = [oid for oid in pool if grades[oid] == maximum]
            if len(survivors) < len(pool):
                trace.append({"stage": "median_removal", "pool": pool,
                              "removed_per_candidate": removed + half,
                              "majority_grades": grades, "remaining_candidates": survivors})
                pool = survivors
            if len(pool) == 1:
                break
        if len(pool) == 1:
            break
        # All surviving candidates share this pair of medians. Jump the
        # complete common run, including potentially trillions of removals.
        jump = min(runs[oid][positions[oid]][2] - consumed[oid] for oid in pool)
        for oid in pool:
            consumed[oid] += jump
            if consumed[oid] == runs[oid][positions[oid]][2]:
                positions[oid] += 1
                consumed[oid] = 0
        removed += 2 * jump
    priority_used = len(pool) > 1
    if priority_used:
        trace.append({"stage": "identical_distribution_priority", "pool": pool})
    return {"majority_grades": initial, "winner": min(pool, key=lambda oid: priority[oid]),
            "tie_trace": trace, "priority_used": priority_used}


def count_majority_judgment(option_ids, weighted_ballots, rules, proposal_id):
    validate_voting_rules(rules, "majority_judgment", proposal_id)
    ids = list(option_ids)
    if len(ids) > MAX_BALLOT_OPTIONS:
        raise ValueError("Too many voting options")
    version = option_set_version(ids)
    histograms = {oid: [0] * 6 for oid in ids}
    total = abstain = headcount = 0
    for payload, weight in weighted_ballots:
        if type(weight) is not int or weight < 0:
            raise ValueError("Voting weight must be a nonnegative integer")
        ballot = validate_ballot("majority_judgment", payload, ids)
        total += weight
        headcount += 1
        if ballot.get("abstain"):
            abstain += weight
            continue
        for oid in ids:
            histograms[oid][ballot["grades"].get(oid, 0)] += weight
    preference_weight = total - abstain
    reason = ("fewer_than_two_options" if len(ids) < 2 else
              "no_positive_weight_preferences" if preference_weight == 0 else
              "all_bottom_ratings" if not any(any(h[1:]) for h in histograms.values()) else None)
    result = {"method": "majority_judgment", "rule_id": rules["rule_id"],
              "grade_histograms": histograms, "majority_grades": {oid: _lower_median(h) for oid, h in histograms.items()},
              "grade_labels": list(GRADE_LABELS), "preference_weight": preference_weight,
              "winner": None, "tie_trace": [], "priority_used": False,
              "no_result_reason": reason, "option_set_version": version}
    if reason is None:
        result.update(_mj_outcome(histograms, {oid: candidate_priority(rules, proposal_id, oid) for oid in ids}))
    return ExperimentalTally(result, total_eligible=total, total_ballots_cast=total,
                             total_abstain=abstain, eligible_headcount=headcount,
                             participating_headcount=headcount)


def _validate_mj_record(result, preference_weight, record):
    histograms = result.get("grade_histograms")
    if (not isinstance(histograms, dict) or len(histograms) > MAX_BALLOT_OPTIONS
            or type(result.get("preference_weight")) is not int
            or result["preference_weight"] != preference_weight
            or result.get("grade_labels") != list(GRADE_LABELS)):
        raise ValueError("Invalid persisted Majority Judgment histograms")
    for histogram in histograms.values():
        if (not isinstance(histogram, list) or len(histogram) != 6
                or any(type(n) is not int or n < 0 for n in histogram)
                or sum(histogram) != preference_weight):
            raise ValueError("Invalid persisted grade frequencies")
    if result.get("option_set_version") != option_set_version(histograms):
        raise ValueError("Invalid persisted option set version")
    reason = ("fewer_than_two_options" if len(histograms) < 2 else
              "no_positive_weight_preferences" if preference_weight == 0 else
              "all_bottom_ratings" if not any(any(h[1:]) for h in histograms.values()) else None)
    if result["no_result_reason"] != reason:
        raise ValueError("Persisted Majority Judgment reason contradicts histograms")
    initial = {oid: _lower_median(h) for oid, h in histograms.items()}
    displayed = result.get("majority_grades")
    if (displayed != initial or not isinstance(displayed, dict)
            or any(code is not None and type(code) is not int for code in displayed.values())):
        raise ValueError("Persisted majority grades contradict histograms")
    if reason is not None:
        if result["winner"] is not None or result["priority_used"] or result.get("tie_trace") != []:
            raise ValueError("No-result record contains Majority Judgment winner")
        return
    if not isinstance(record.get("rules"), dict) or "tie_seed" not in record:
        raise ValueError("Final Majority Judgment record requires frozen rules and seed")
    rules = {**record["rules"], "tie_seed": record["tie_seed"]}
    proposal_id = rules.get("proposal_id")
    validate_voting_rules(rules, "majority_judgment", proposal_id)
    expected = _mj_outcome(histograms, {oid: candidate_priority(rules, proposal_id, oid) for oid in histograms})
    if any(result.get(field) != value for field, value in expected.items()):
        raise ValueError("Persisted Majority Judgment result contradicts histograms/rules")


def _ranked_pairs_graph(pairwise, priority):
    """Lock sorted victories using incremental bitset transitive closure."""
    ids = sorted(pairwise)
    index = {oid: i for i, oid in enumerate(ids)}
    victories = [{"winner": a, "loser": b, "margin": pairwise[a][b] - pairwise[b][a],
                  "support": pairwise[a][b]} for a in ids for b in ids
                 if pairwise[a][b] > pairwise[b][a]]
    victories.sort(key=lambda e: (-e["margin"], -e["support"], priority[e["winner"]], priority[e["loser"]]))
    tied_strengths = {}
    for edge in victories:
        tied_strengths.setdefault((edge["margin"], edge["support"]), []).append(
            {"winner": edge["winner"], "loser": edge["loser"]})
    trace = [{"stage": "edge_priority", "margin": margin, "support": support, "edges": edges}
             for (margin, support), edges in tied_strengths.items() if len(edges) > 1]
    reachable = [0] * len(ids)
    incoming = set()
    locked, skipped = [], []
    for edge in victories:
        a, b = index[edge["winner"]], index[edge["loser"]]
        if reachable[b] & (1 << a):
            skipped.append({**edge, "reason": "would_create_cycle"})
            continue
        locked.append({**edge, "reason": "locked"})
        incoming.add(edge["loser"])
        descendants = reachable[b] | (1 << b)
        for i in range(len(ids)):
            if i == a or reachable[i] & (1 << a):
                reachable[i] |= descendants
    sources = sorted((oid for oid in ids if oid not in incoming), key=lambda oid: priority[oid])
    if len(sources) > 1:
        trace.append({"stage": "source_priority", "pool": sorted(sources)})
    return {"ordered_victories": victories, "locked_edges": locked, "skipped_edges": skipped,
            "source_candidates": sources, "winner": sources[0] if sources else None,
            "tie_trace": trace, "priority_used": bool(trace)}


def count_ranked_pairs(option_ids, weighted_ballots, rules, proposal_id) -> ExperimentalTally:
    validate_voting_rules(rules, "ranked_pairs", proposal_id)
    ids = list(option_ids)
    if len(ids) > MAX_BALLOT_OPTIONS:
        raise ValueError("Too many voting options")
    version = option_set_version(ids)
    pairwise = {a: dict.fromkeys(ids, 0) for a in ids}
    total = abstain = headcount = 0
    for payload, weight in weighted_ballots:
        if type(weight) is not int or weight < 0:
            raise ValueError("Voting weight must be a nonnegative integer")
        ballot = validate_ballot("ranked_pairs", payload, ids)
        total += weight
        headcount += 1
        if ballot.get("abstain"):
            abstain += weight
            continue
        if not weight:
            continue
        groups = ballot["rank_groups"]
        ranks = {oid: rank for rank, group in enumerate(groups) for oid in group}
        ranked = [(oid, ranks.get(oid, len(groups))) for oid in ids]
        # O(options squared) once per effective ballot, independent of shares.
        for a, rank_a in ranked:
            row = pairwise[a]
            for b, rank_b in ranked:
                if rank_a < rank_b:
                    row[b] += weight
    reason = ("fewer_than_two_options" if len(ids) < 2 else
              "no_positive_weight_preferences" if total == abstain else
              "no_strict_preferences" if not any(any(row.values()) for row in pairwise.values()) else None)
    result = {"method": "ranked_pairs", "rule_id": rules["rule_id"], "pairwise": pairwise,
              "ordered_victories": [], "locked_edges": [], "skipped_edges": [], "source_candidates": [],
              "preference_weight": total - abstain, "winner": None, "tie_trace": [],
              "priority_used": False, "no_result_reason": reason, "option_set_version": version}
    if reason is None:
        priority = {oid: candidate_priority(rules, proposal_id, oid) for oid in ids}
        result.update(_ranked_pairs_graph(pairwise, priority))
    return ExperimentalTally(result, total_eligible=total, total_ballots_cast=total,
                             total_abstain=abstain, eligible_headcount=headcount,
                             participating_headcount=headcount)


def _validate_ranked_pairs_record(result, preference_weight, record):
    matrix = result.get("pairwise")
    if (not isinstance(matrix, dict) or len(matrix) > MAX_BALLOT_OPTIONS
            or type(result.get("preference_weight")) is not int
            or result["preference_weight"] != preference_weight):
        raise ValueError("Invalid persisted Ranked Pairs matrix")
    ids = set(matrix)
    if result.get("option_set_version") != option_set_version(ids):
        raise ValueError("Invalid persisted option set version")
    for a, row in matrix.items():
        if (not isinstance(row, dict) or set(row) != ids
                or any(type(n) is not int or n < 0 or n > preference_weight for n in row.values())
                or row[a] != 0):
            raise ValueError("Invalid persisted Ranked Pairs matrix row")
    if any(matrix[a][b] + matrix[b][a] > preference_weight for a in ids for b in ids):
        raise ValueError("Persisted pairwise preferences exceed voting power")
    reason = ("fewer_than_two_options" if len(ids) < 2 else
              "no_positive_weight_preferences" if preference_weight == 0 else
              "no_strict_preferences" if not any(any(row.values()) for row in matrix.values()) else None)
    if result["no_result_reason"] != reason:
        raise ValueError("Persisted Ranked Pairs reason contradicts matrix")
    fields = ("ordered_victories", "locked_edges", "skipped_edges", "source_candidates", "tie_trace")
    if any(not isinstance(result.get(field), list) for field in fields):
        raise ValueError("Invalid persisted Ranked Pairs graph")
    if reason is not None:
        if result["winner"] is not None or result["priority_used"] or any(result[field] for field in fields):
            raise ValueError("No-result record contains a Ranked Pairs winner")
        return
    # Full production records carry the committed seed; derive the graph only
    # from frozen aggregates, never from mutable current ballots or membership.
    if "rules" in record and "tie_seed" in record:
        rules = {**record["rules"], "tie_seed": record["tie_seed"]}
        proposal_id = rules.get("proposal_id")
        validate_voting_rules(rules, "ranked_pairs", proposal_id)
        priority = {oid: candidate_priority(rules, proposal_id, oid) for oid in ids}
        expected = _ranked_pairs_graph(matrix, priority)
        if any(result.get(field) != value for field, value in expected.items()):
            raise ValueError("Persisted Ranked Pairs graph contradicts matrix/rules")
    else:
        raise ValueError("Final Ranked Pairs record requires frozen rules and seed")


def count_star(option_ids, weighted_ballots, rules, proposal_id) -> ExperimentalTally:
    tally, preference_ballots, ids = _rated_totals("star", option_ids, weighted_ballots, rules, proposal_id)
    result = tally.method_result
    scores = result["scores"]
    five = {oid: result["score_histograms"][oid][5] for oid in ids}
    result.update(five_star_counts=five, finalists=[], runoff={}, equal_preference=0)
    if result["no_result_reason"]:
        return tally

    def cut(pool, values, needed):
        ordered = sorted(pool, key=lambda oid: (-values[oid], oid))
        if len(ordered) <= needed:
            return ordered, []
        cutoff = values[ordered[needed - 1]]
        selected = [oid for oid in ordered if values[oid] > cutoff]
        boundary = [oid for oid in ordered if values[oid] == cutoff]
        if len(boundary) == needed - len(selected):
            return selected + boundary, []
        return selected, boundary

    finalists, boundary = cut(ids, scores, 2)
    if boundary:
        prefs = dict.fromkeys(boundary, 0)
        for ratings, weight in preference_ballots:
            # Fixed six-value scale: sum strict pairwise preferences by a
            # score histogram, avoiding O(options squared) work per tie ballot.
            frequencies = [0] * 6
            for a in boundary:
                frequencies[ratings.get(a, 0)] += 1
            lower = [0] * 6
            for rating in range(1, 6):
                lower[rating] = lower[rating - 1] + frequencies[rating - 1]
            for a in boundary:
                prefs[a] += weight * lower[ratings.get(a, 0)]
        result["tie_trace"].append({"stage": "finalist_preferences", "pool": sorted(boundary), "values": prefs})
        selected, boundary = cut(boundary, prefs, 2 - len(finalists))
        finalists.extend(selected)
    if boundary:
        result["tie_trace"].append({"stage": "finalist_five_stars", "pool": sorted(boundary), "values": {oid: five[oid] for oid in boundary}})
        selected, boundary = cut(boundary, five, 2 - len(finalists))
        finalists.extend(selected)
    if boundary:
        result["priority_used"] = True
        result["tie_trace"].append({"stage": "finalist_priority", "pool": sorted(boundary)})
        finalists.extend(sorted(boundary, key=lambda oid: candidate_priority(rules, proposal_id, oid))[:2-len(finalists)])
    result["finalists"] = finalists
    a, b = finalists
    runoff = {a: 0, b: 0}
    for ratings, weight in preference_ballots:
        left, right = ratings.get(a, 0), ratings.get(b, 0)
        if left == right:
            result["equal_preference"] += weight
        else:
            runoff[a if left > right else b] += weight
    result["runoff"] = runoff
    winner, tie = cut(finalists, runoff, 1)
    for stage, values in (("runoff_total_score", scores), ("runoff_five_stars", five)):
        if not tie:
            break
        result["tie_trace"].append({"stage": stage, "pool": sorted(tie), "values": {oid: values[oid] for oid in tie}})
        winner, tie = cut(tie, values, 1)
    if tie:
        result["priority_used"] = True
        result["tie_trace"].append({"stage": "runoff_priority", "pool": sorted(tie)})
        winner = [min(tie, key=lambda oid: candidate_priority(rules, proposal_id, oid))]
    result["winner"] = winner[0]
    return tally
