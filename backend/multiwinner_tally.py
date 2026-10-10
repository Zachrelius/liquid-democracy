"""Exact aggregate-only multiwinner extensions. Old v1 counters stay unchanged."""
from copy import deepcopy
from experimental_tally import ExperimentalTally, _rated_totals
from voting_methods import candidate_priority, validate_voting_rules, option_set_version
from voting_capabilities import PLANNED_CAPABILITIES, validate_winner_count


def _selection(result, order, count, *, reason=None):
    validate_winner_count(count)
    winners = order[:count]
    unfilled = count - len(winners)
    result.update(winners=winners, winner=winners[0] if winners else None, ranked_order=order,
        requested_count=count, filled_count=len(winners), unfilled_count=unfilled,
        unfilled_reason=(reason or "support_exhausted") if unfilled else None,
        no_result_reason=(reason or "no_supported_options") if not winners else None,
        supported_options=list(order))
    return result


def _score_order(scores, rules, proposal_id):
    supported = [oid for oid, value in scores.items() if value > 0]
    order = sorted(supported, key=lambda oid:(-scores[oid], candidate_priority(rules, proposal_id, oid)))
    groups = {}
    for oid in order: groups.setdefault(scores[oid], []).append(oid)
    trace = [{"stage":"score_priority", "pool":sorted(pool), "total":score}
             for score,pool in groups.items() if len(pool)>1]
    return order, trace


def count_score_top_n(option_ids, weighted_ballots, rules, proposal_id):
    count = rules.get("num_winners")
    validate_voting_rules(rules, "score", proposal_id, count)
    if count is None or count < 2: raise ValueError("Score top-N requires multiple winners")
    tally, _, ids = _rated_totals("score", option_ids, weighted_ballots, rules, proposal_id)
    result = tally.method_result
    order, trace = _score_order(result["scores"],rules,proposal_id)
    result.update(tie_trace=trace,priority_used=bool(trace))
    _selection(result,order,count)
    result["selection_boundary_tie"] = (len(order)>count and result["scores"][order[count-1]]==result["scores"][order[count]])
    return tally


def count_multiwinner(method, option_ids, weighted_ballots, rules, proposal_id, num_winners):
    validate_voting_rules(rules, method, proposal_id, num_winners)
    counters = {"score":count_score_top_n}
    if method not in counters: raise ValueError("No released multiwinner tally handler")
    return counters[method](option_ids,weighted_ballots,rules,proposal_id)


def validate_multiwinner_record(result, record, preference_weight):
    """Reconstruct Score ordering solely from immutable aggregates and rules."""
    rules = {**record.get("rules",{}), "tie_seed":record.get("tie_seed")}
    method = result.get("method")
    if method not in PLANNED_CAPABILITIES: raise ValueError("Invalid multiwinner method")
    count = rules.get("num_winners")
    validate_voting_rules(rules,method,rules.get("proposal_id"),count)
    if (count is None or count < 2 or result.get("requested_count") != count
            or result.get("rule_id") != rules["rule_id"] or type(result.get("priority_used")) is not bool):
        raise ValueError("Invalid frozen winner count")
    if record.get("record_version") != 2 or record.get("num_winners") != count:
        raise ValueError("Incompatible multiwinner frozen record")
    scores = result.get("scores")
    histograms = result.get("score_histograms")
    if (method != "score" or not isinstance(scores,dict) or len(scores)>120 or not isinstance(histograms,dict)
            or set(scores)!=set(histograms) or result.get("preference_weight")!=preference_weight
            or result.get("option_set_version")!=option_set_version(scores)
            or set(record.get("option_labels",{}))!=set(scores)):
        raise ValueError("Invalid frozen multiwinner aggregates")
    for oid, score in scores.items():
        histogram=histograms[oid]
        if (type(score) is not int or score<0 or not isinstance(histogram,list) or len(histogram)!=6
                or any(type(n) is not int or n<0 for n in histogram) or sum(histogram)!=preference_weight
                or sum(g*n for g,n in enumerate(histogram))!=score):
            raise ValueError("Invalid frozen rating histogram")
    order,trace=_score_order(scores,rules,rules["proposal_id"])
    expected=deepcopy(result)
    _selection(expected,order,count)
    expected.update(tie_trace=trace,priority_used=bool(trace),
        selection_boundary_tie=len(order)>count and scores[order[count-1]]==scores[order[count]])
    for key in ("winners","winner","ranked_order","supported_options","requested_count","filled_count",
                "unfilled_count","unfilled_reason","no_result_reason","tie_trace","priority_used","selection_boundary_tie"):
        if result.get(key)!=expected[key]: raise ValueError("Frozen selection contradicts aggregates/rules")
    official = result["winners"] if record.get("quorum_met") else []
    if record.get("official_winners") != official:
        raise ValueError("Invalid official frozen winners")
