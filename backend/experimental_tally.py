"""Pure exact-integer counters for the released experimental methods.

STAR follows Phase 109 v1, compared against starvote 2.1.5 (MIT).
No reference package is imported by production and no shares are expanded.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from fractions import Fraction

from experimental_ballots import MAX_BALLOT_OPTIONS, validate_ballot
from voting_methods import RULE_IDS, candidate_priority, option_set_version, validate_voting_rules


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
        if (not isinstance(result, dict) or result.get("method") not in ("star", "score")
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
            return {key: convert(item) for key, item in value.items()}
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
