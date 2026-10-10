"""Exact aggregate-only multiwinner extensions. Old v1 counters stay unchanged."""
from copy import deepcopy
from functools import cmp_to_key
from experimental_tally import ExperimentalTally, _rated_totals, count_star, count_majority_judgment, _mj_outcome, _lower_median, _ranked_pairs_graph
from voting_methods import candidate_priority, validate_voting_rules, option_set_version, GRADE_LABELS
from experimental_ballots import validate_ballot
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



def _mj_order(histograms, rules, proposal_id):
    # Each pair compares the complete original distributions. The existing
    # counter jumps common median runs; its input histograms are never depleted.
    supported = sorted(oid for oid,h in histograms.items() if any(h[1:]))
    priority = {oid:candidate_priority(rules,proposal_id,oid) for oid in supported}
    comparisons = []
    def compare(a,b):
        outcome = _mj_outcome({a:histograms[a],b:histograms[b]},priority)
        comparisons.append({"pool":sorted([a,b]),"winner":outcome["winner"],
            "tie_trace":outcome["tie_trace"],"priority_used":outcome["priority_used"]})
        return -1 if outcome["winner"]==a else 1
    return sorted(supported,key=cmp_to_key(compare)),comparisons


def count_majority_judgment_top_n(option_ids,weighted_ballots,rules,proposal_id):
    count=rules.get("num_winners")
    validate_voting_rules(rules,"majority_judgment",proposal_id,count)
    if count is None or count<2:raise ValueError("Majority Judgment top-N requires multiple winners")
    tally=count_majority_judgment(option_ids,weighted_ballots,rules,proposal_id)
    result=tally.method_result
    order,comparisons=_mj_order(result["grade_histograms"],rules,proposal_id)
    _selection(result,order,count)
    result.update(comparisons=comparisons,
        tie_trace=[{"comparison":i+1,**event} for i,row in enumerate(comparisons) for event in row["tie_trace"]],
        priority_used=any(row["priority_used"] for row in comparisons),
        selection_boundary_tie=len(order)>count and result["majority_grades"][order[count-1]]==result["majority_grades"][order[count]])
    return tally


def _validate_mj_top_n_record(result,record,rules,preference_weight):
    histograms=result.get("grade_histograms")
    if (not isinstance(histograms,dict) or len(histograms)>120 or result.get("preference_weight")!=preference_weight
            or result.get("grade_labels")!=list(GRADE_LABELS)
            or result.get("option_set_version")!=option_set_version(histograms)
            or set(record.get("option_labels",{}))!=set(histograms)):
        raise ValueError("Invalid frozen Majority Judgment aggregates")
    for h in histograms.values():
        if not isinstance(h,list) or len(h)!=6 or any(type(n) is not int or n<0 for n in h) or sum(h)!=preference_weight:
            raise ValueError("Invalid frozen grade frequencies")
    grades={oid:_lower_median(h) for oid,h in histograms.items()}
    if result.get("majority_grades")!=grades:raise ValueError("Invalid frozen original majority grades")
    order,comparisons=_mj_order(histograms,rules,rules["proposal_id"])
    expected=deepcopy(result);_selection(expected,order,rules["num_winners"])
    expected.update(comparisons=comparisons,
        tie_trace=[{"comparison":i+1,**event} for i,row in enumerate(comparisons) for event in row["tie_trace"]],
        priority_used=any(row["priority_used"] for row in comparisons),
        selection_boundary_tie=len(order)>rules["num_winners"] and grades[order[rules["num_winners"]-1]]==grades[order[rules["num_winners"]]])
    for key in ("winners","winner","ranked_order","supported_options","requested_count","filled_count","unfilled_count","unfilled_reason","no_result_reason","comparisons","tie_trace","priority_used","selection_boundary_tie"):
        if result.get(key)!=expected[key]:raise ValueError("Frozen grade ranking contradicts original histograms")
    if record.get("official_winners")!=(expected["winners"] if record.get("quorum_met") else []):
        raise ValueError("Invalid official Majority Judgment winners")



def _rp_order(pairwise,rules,proposal_id):
    priority={oid:candidate_priority(rules,proposal_id,oid) for oid in pairwise}
    graph=_ranked_pairs_graph(pairwise,priority)
    outgoing={oid:[] for oid in pairwise};indegree=dict.fromkeys(pairwise,0)
    for edge in graph["locked_edges"]:
        outgoing[edge["winner"]].append(edge["loser"]);indegree[edge["loser"]]+=1
    remaining=set(pairwise);order=[];source_ties=[]
    while remaining:
        sources=sorted((oid for oid in remaining if indegree[oid]==0),key=lambda oid:priority[oid])
        if not sources:raise ValueError("Ranked Pairs locked graph contains a cycle")
        if len(sources)>1:source_ties.append({"stage":"topological_source_priority","position":len(order)+1,"pool":sorted(sources),"selected":sources[0]})
        selected=sources[0];order.append(selected);remaining.remove(selected)
        for loser in outgoing[selected]:indegree[loser]-=1
    # The first source set is the old rule's complete winner pool; later
    # sources belong to this same graph, with no fresh matrix or edge locking.
    trace=[event for event in graph["tie_trace"] if event["stage"]=="edge_priority"]+source_ties
    graph.update(tie_trace=trace,priority_used=bool(trace),source_ties=source_ties)
    return order,graph


def _rp_selection(result,rules,proposal_id):
    matrix=result["pairwise"];count=rules["num_winners"]
    meaningful=any(any(row.values()) for row in matrix.values())
    order,graph=_rp_order(matrix,rules,proposal_id) if meaningful else ([],{"ordered_victories":[],"locked_edges":[],"skipped_edges":[],"source_candidates":[],"tie_trace":[],"priority_used":False,"source_ties":[]})
    _selection(result,order,count,reason=None if meaningful else "no_strict_preferences")
    result.update(graph)
    # graph winner is only a compatibility alias; _selection owns empty sets.
    result["winner"]=order[0] if order else None
    result.update(eligible_options=sorted(matrix),supported_options=sorted(matrix),
        selection_boundary_tie=bool(len(order)>count and any(row["position"]==count for row in graph["source_ties"])))
    return result


def count_ranked_pairs_top_n(option_ids,weighted_ballots,rules,proposal_id):
    count=rules.get("num_winners")
    validate_voting_rules(rules,"ranked_pairs",proposal_id,count)
    if count is None or count<2:raise ValueError("Ranked Pairs top-N requires multiple winners")
    ids=list(option_ids);version=option_set_version(ids)
    if len(ids)>120:raise ValueError("Too many voting options")
    ballots=[];ranked_weights=dict.fromkeys(ids,0);total=abstain=headcount=0
    for payload,weight in weighted_ballots:
        if type(weight) is not int or weight<0:raise ValueError("Voting weight must be a nonnegative integer")
        ballot=validate_ballot("ranked_pairs",payload,ids);total+=weight;headcount+=1
        if ballot.get("abstain"):abstain+=weight;continue
        if not weight:continue
        ranks={oid:i for i,group in enumerate(ballot["rank_groups"]) for oid in group}
        for oid in ranks:ranked_weights[oid]+=weight
        ballots.append((ranks,len(ballot["rank_groups"]),weight))
    eligible=sorted(oid for oid,n in ranked_weights.items() if n>0)
    matrix={a:dict.fromkeys(eligible,0) for a in eligible}
    for ranks,omitted,weight in ballots:
        ranked=[(oid,ranks.get(oid,omitted)) for oid in eligible]
        for a,ra in ranked:
            for b,rb in ranked:
                if ra<rb:matrix[a][b]+=weight
    result={"method":"ranked_pairs","rule_id":rules["rule_id"],"pairwise":matrix,
        "ranked_weights":ranked_weights,"preference_weight":total-abstain,"option_set_version":version}
    _rp_selection(result,rules,proposal_id)
    return ExperimentalTally(result,total_eligible=total,total_ballots_cast=total,total_abstain=abstain,eligible_headcount=headcount,participating_headcount=headcount)


def _validate_rp_top_n_record(result,record,rules,preference_weight):
    ranked=result.get("ranked_weights");matrix=result.get("pairwise")
    if (not isinstance(ranked,dict) or len(ranked)>120 or not isinstance(matrix,dict)
            or any(type(n) is not int or n<0 or n>preference_weight for n in ranked.values())
            or result.get("option_set_version")!=option_set_version(ranked)
            or set(record.get("option_labels",{}))!=set(ranked) or result.get("preference_weight")!=preference_weight
            or set(matrix)!={oid for oid,n in ranked.items() if n>0}):
        raise ValueError("Invalid frozen Ranked Pairs eligibility/matrix")
    ids=set(matrix)
    for a,row in matrix.items():
        if (not isinstance(row,dict) or set(row)!=ids or row[a]!=0
                or any(type(n) is not int or n<0 or n>preference_weight for n in row.values())):
            raise ValueError("Invalid frozen pairwise row")
    if any(matrix[a][b]+matrix[b][a]>preference_weight for a in ids for b in ids):raise ValueError("Frozen pairwise exceeds electorate")
    expected=deepcopy(result);_rp_selection(expected,rules,rules["proposal_id"])
    for key in ("winners","winner","ranked_order","supported_options","eligible_options","requested_count","filled_count","unfilled_count","unfilled_reason","no_result_reason","ordered_victories","locked_edges","skipped_edges","source_candidates","source_ties","tie_trace","priority_used","selection_boundary_tie"):
        if result.get(key)!=expected[key]:raise ValueError("Frozen order contradicts fixed Ranked Pairs graph")
    if record.get("official_winners")!=(expected["winners"] if record.get("quorum_met") else []):raise ValueError("Invalid official Ranked Pairs winners")


def count_multiwinner(method, option_ids, weighted_ballots, rules, proposal_id, num_winners):
    validate_voting_rules(rules, method, proposal_id, num_winners)
    from allocated_score import count_allocated_score
    counters = {"allocated_score":count_allocated_score,"score":count_score_top_n,"star":count_bloc_star,"majority_judgment":count_majority_judgment_top_n,"ranked_pairs":count_ranked_pairs_top_n}
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
    if (any(type(result.get(key)) is not int for key in ("requested_count","filled_count","unfilled_count"))
            or type(record.get("quorum_met")) is not bool):
        raise ValueError("Invalid frozen selection or quorum types")
    if record.get("record_version") != 2 or record.get("num_winners") != count:
        raise ValueError("Incompatible multiwinner frozen record")
    if method == "ranked_pairs":
        _validate_rp_top_n_record(result,record,rules,preference_weight)
        return
    if method == "majority_judgment":
        _validate_mj_top_n_record(result,record,rules,preference_weight)
        return
    scores = result.get("scores")
    histograms = result.get("score_histograms")
    if (method not in ("score","star","allocated_score") or not isinstance(scores,dict) or len(scores)>120 or not isinstance(histograms,dict)
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
    if method == "allocated_score":
        from allocated_score import validate_allocated_record
        validate_allocated_record(result,record,rules,preference_weight)
        return
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
