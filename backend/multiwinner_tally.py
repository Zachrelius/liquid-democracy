"""Exact aggregate-only multiwinner extensions. Old v1 counters stay unchanged."""
from copy import deepcopy
from experimental_tally import ExperimentalTally, _rated_totals, count_star
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


def count_bloc_star(option_ids, weighted_ballots, rules, proposal_id):
    count = rules.get("num_winners")
    validate_voting_rules(rules, "star", proposal_id, count)
    if count is None or count < 2: raise ValueError("Bloc STAR requires multiple winners")
    ballots = list(weighted_ballots)
    tally, _, ids = _rated_totals("star", option_ids, ballots, rules, proposal_id)
    result = tally.method_result
    supported = sorted(oid for oid in ids if result["scores"][oid] > 0)
    remaining = list(supported)
    winners = []
    rounds = []
    while remaining and len(winners) < count:
        if len(remaining) == 1:
            winner = remaining[0]
            rounds.append({"pool":list(remaining),"selection":"single_supported_option",
                "winner":winner,"competitive_runoff":False,"scores":{winner:result["scores"][winner]},
                "score_histograms":{winner:result["score_histograms"][winner]},
                "finalists":[],"runoff":{},"equal_preference":0,"tie_trace":[],"priority_used":False})
        else:
            # Omission remains zero. Remove elected keys from the counting view
            # without renormalizing or changing original represented weights.
            view = [(payload if payload.get("abstain") else {"scores":{oid:value for oid,value in payload["scores"].items() if oid in remaining}},weight)
                    for payload,weight in ballots]
            round_result = count_star(remaining, view, rules, proposal_id).method_result
            winner = round_result["winner"]
            if winner is None: raise ValueError("Supported STAR pool produced no winner")
            rounds.append({**deepcopy(round_result),"pool":list(remaining),"selection":"competitive_runoff","competitive_runoff":True})
        winners.append(winner)
        remaining.remove(winner)
    _selection(result,winners,count)
    result.update(supported_options=supported,remaining_options=remaining,rounds=rounds,
        priority_used=any(row["priority_used"] for row in rounds),
        tie_trace=[{"round":i+1,**trace} for i,row in enumerate(rounds) for trace in row["tie_trace"]],
        selection_boundary_tie=False)
    return tally


def count_multiwinner(method, option_ids, weighted_ballots, rules, proposal_id, num_winners):
    validate_voting_rules(rules, method, proposal_id, num_winners)
    counters = {"score":count_score_top_n,"star":count_bloc_star}
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
    if (method not in ("score","star") or not isinstance(scores,dict) or len(scores)>120 or not isinstance(histograms,dict)
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
    if method == "star":
        _validate_bloc_star_record(result,record,rules,preference_weight)
        return
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


def _validate_bloc_star_record(result,record,rules,preference_weight):
    from voting_methods import _metadata, RULE_IDS
    count=rules["num_winners"]
    supported=sorted(oid for oid,n in result["scores"].items() if n>0)
    remaining=list(supported);winners=[];trace=[];priority=False
    rounds=result.get("rounds")
    if not isinstance(rounds,list) or len(rounds)!=min(count,len(supported)):
        raise ValueError("Invalid frozen Bloc STAR round count")
    for i,row in enumerate(rounds):
        if (not isinstance(row,dict) or row.get("pool")!=remaining or row.get("winner") not in remaining
                or row.get("scores")!={oid:result["scores"][oid] for oid in remaining}
                or row.get("score_histograms")!={oid:result["score_histograms"][oid] for oid in remaining}):
            raise ValueError("Frozen STAR round contradicts original totals/pool")
        if len(remaining)==1:
            if (row.get("selection")!="single_supported_option" or row.get("competitive_runoff") is not False
                    or row.get("finalists")!=[] or row.get("runoff")!={} or row.get("tie_trace")!=[]
                    or row.get("priority_used") is not False or row.get("equal_preference")!=0):
                raise ValueError("Invalid singleton STAR disclosure")
        else:
            if row.get("selection")!="competitive_runoff" or row.get("competitive_runoff") is not True:
                raise ValueError("Missing frozen competitive runoff")
            legacy=deepcopy(row);legacy["rule_id"]=RULE_IDS["star"]
            legacy_rules={**_metadata("star",rules["proposal_id"]),"tie_commitment":rules["tie_commitment"]}
            legacy_record={"tally":{**deepcopy(record["tally"]),"method_result":legacy},"method":"star","rules":legacy_rules}
            ExperimentalTally.from_record(legacy_record)
        trace.extend({"round":i+1,**event} for event in row["tie_trace"])
        priority |= row["priority_used"]
        winners.append(row["winner"]);remaining.remove(row["winner"])
    expected=deepcopy(result);_selection(expected,winners,count)
    expected.update(supported_options=supported,remaining_options=remaining,tie_trace=trace,priority_used=priority,selection_boundary_tie=False)
    for key in ("winners","winner","ranked_order","supported_options","remaining_options","requested_count","filled_count","unfilled_count","unfilled_reason","no_result_reason","tie_trace","priority_used","selection_boundary_tie"):
        if result.get(key)!=expected[key]:raise ValueError("Frozen Bloc STAR selection contradicts rounds")
    if record.get("official_winners")!=(winners if record.get("quorum_met") else []):
        raise ValueError("Invalid official Bloc STAR winners")
