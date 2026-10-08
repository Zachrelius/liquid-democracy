"""Pure exact-integer counters for the released experimental methods.

STAR follows Phase 109 v1, compared against starvote 2.1.5 (MIT).
No reference package is imported by production and no shares are expanded.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from decimal import Decimal

from experimental_ballots import MAX_BALLOT_OPTIONS, validate_ballot
from voting_methods import candidate_priority, option_set_version, validate_voting_rules


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
        winner = self.method_result["winner"]
        return [winner] if winner is not None else []

    @property
    def tied(self):
        return self.method_result["priority_used"]

    def quorum_met(self, threshold):
        return self.total_eligible > 0 and Decimal(self.total_ballots_cast) >= Decimal(str(threshold)) * self.total_eligible

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
        if (not isinstance(result, dict) or result.get("method") != "star"
                or result.get("rule_id") != "star_0_5_v1"
                or type(result.get("priority_used")) is not bool
                or "winner" not in result or "no_result_reason" not in result):
            raise ValueError("Invalid persisted experimental method result")
        if value["total_ballots_cast"] + value["not_cast"] != value["total_eligible"]:
            raise ValueError("Inconsistent persisted participation count")
        if value["total_abstain"] > value["total_ballots_cast"]:
            raise ValueError("Inconsistent persisted abstention count")
        scores = result.get("scores")
        histograms = result.get("score_histograms")
        finalists = result.get("finalists")
        runoff = result.get("runoff")
        preference_weight = value["total_ballots_cast"] - value["total_abstain"]
        if (not isinstance(scores, dict) or len(scores) > MAX_BALLOT_OPTIONS
                or not isinstance(histograms, dict) or set(histograms) != set(scores)
                or not isinstance(finalists, list) or len(finalists) != len(set(finalists))
                or any(oid not in scores for oid in finalists)
                or not isinstance(runoff, dict) or set(runoff) != set(finalists)
                or result.get("preference_weight") != preference_weight
                or not isinstance(result.get("tie_trace"), list)):
            raise ValueError("Inconsistent persisted STAR aggregates")
        for oid, score in scores.items():
            histogram = histograms[oid]
            if (type(score) is not int or score < 0 or not isinstance(histogram, list)
                    or len(histogram) != 6 or any(type(n) is not int or n < 0 for n in histogram)
                    or sum(histogram) != preference_weight
                    or sum(grade * n for grade, n in enumerate(histogram)) != score):
                raise ValueError("Invalid persisted STAR score histogram")
        if result["winner"] is not None:
            if (len(finalists) != 2 or result["winner"] not in finalists
                    or result["no_result_reason"] is not None
                    or any(type(n) is not int or n < 0 for n in runoff.values())
                    or type(result.get("equal_preference")) is not int
                    or result["equal_preference"] < 0
                    or sum(runoff.values()) + result["equal_preference"] != preference_weight):
                raise ValueError("Invalid persisted STAR runoff")
        elif result["no_result_reason"] not in (
                "fewer_than_two_options", "no_positive_weight_preferences", "all_bottom_ratings"):
            raise ValueError("Missing persisted no-result reason")
        return cls(**value)


def public_tally(tally: ExperimentalTally) -> dict:
    """Transport exact counts as decimal strings; never lose JS precision."""
    def convert(value):
        if type(value) is int:
            return str(value)
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value
    return convert(tally.to_record())


def count_star(option_ids, weighted_ballots, rules, proposal_id) -> ExperimentalTally:
    validate_voting_rules(rules, "star", proposal_id)
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
        ballot = validate_ballot("star", payload, ids)
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
    five = {oid: histograms[oid][5] for oid in ids}
    result = {
        "method": "star", "rule_id": rules["rule_id"], "scores": scores,
        "score_histograms": histograms, "five_star_counts": five,
        "preference_weight": total - abstain,
        "finalists": [], "runoff": {}, "equal_preference": 0,
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
            for a in boundary:
                prefs[a] += weight * sum(ratings.get(a, 0) > ratings.get(b, 0) for b in boundary if b != a)
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
