"""Independent exact implementation of the Phase 113 Appendix-D contract.

Original represented weight is separate from remaining fraction. Equal full
profiles may be grouped without changing their allocation; no shares expanded.
Only aggregate contribution bands enter the frozen record. No reference code
or third-party runtime dependency is included in this MIT implementation.
"""
from fractions import Fraction
from math import gcd
from experimental_tally import _rated_totals
from voting_methods import validate_voting_rules,candidate_priority


def quantity(value):
    value=Fraction(value)
    return {"numerator":str(value.numerator),"denominator":str(value.denominator)}


def read_quantity(value):
    if not isinstance(value,dict) or set(value)!={"numerator","denominator"}:raise ValueError("Invalid rational quantity")
    n,d=value["numerator"],value["denominator"]
    if (not isinstance(n,str) or not n.isdigit() or not isinstance(d,str) or not d.isdigit()
            or str(int(n))!=n or str(int(d))!=d or int(d)<=0 or gcd(int(n),int(d))!=1):
        raise ValueError("Noncanonical rational quantity")
    return Fraction(int(n),int(d))


def _totals(profiles,remaining):
    # Sum integer score vectors within equal remaining fractions first.
    # This avoids constructing a rational for every share/candidate term.
    buckets={}
    for p in profiles:
        f=p["fraction"]
        if not f:continue
        if f not in buckets:buckets[f]=dict.fromkeys(remaining,0)
        row=buckets[f];base=p["base"];scores=p["scores"]
        for oid in remaining:row[oid]+=base*scores[oid]
    return {oid:sum((f*row[oid] for f,row in buckets.items() if row[oid]),Fraction(0)) for oid in remaining}


def count_allocated_score(option_ids,weighted_ballots,rules,proposal_id):
    from multiwinner_tally import _selection
    count=rules.get("num_winners")
    validate_voting_rules(rules,"allocated_score",proposal_id,count)
    tally,ballots,ids=_rated_totals("allocated_score",option_ids,weighted_ballots,rules,proposal_id)
    ids=sorted(ids);groups={}
    for ratings,base in ballots:
        key=tuple(ratings.get(oid,0) for oid in ids)
        if any(key):groups[key]=groups.get(key,0)+base
    profiles=[{"base":base,"fraction":Fraction(1),"scores":dict(zip(ids,key))} for key,base in sorted(groups.items())]
    informative=sum(p["base"] for p in profiles);quota=Fraction(informative,count)
    remaining=list(ids);winners=[];rounds=[];tie_trace=[]
    priority={oid:candidate_priority(rules,proposal_id,oid) for oid in ids}
    while remaining and len(winners)<count:
        totals=_totals(profiles,remaining);highest=max(totals.values())
        if highest<=0:break
        tied=sorted(oid for oid,n in totals.items() if n==highest)
        winner=min(tied,key=lambda oid:priority[oid])
        if len(tied)>1:tie_trace.append({"stage":"allocated_score_priority","round":len(winners)+1,"pool":tied,"total":quantity(highest)})
        before=sum((p["base"]*p["fraction"] for p in profiles),Fraction(0));needed=min(quota,before)
        bands={}
        for p in profiles:
            if p["fraction"]>0:bands.setdefault(p["fraction"]*p["scores"][winner],[]).append(p)
        trace=[];allocated=Fraction(0)
        for contribution,band in sorted(bands.items(),reverse=True):
            if needed<=0:break
            mass=sum((p["base"]*p["fraction"] for p in band),Fraction(0))
            spend=min(needed,mass);ratio=spend/mass
            for p in band:p["fraction"]*=1-ratio
            trace.append({"contribution":quantity(contribution),"remaining_mass":quantity(mass),"allocated_mass":quantity(spend),"allocated_fraction":quantity(ratio)})
            needed-=spend;allocated+=spend
        after=sum((p["base"]*p["fraction"] for p in profiles),Fraction(0))
        rounds.append({"pool":list(remaining),"winner":winner,"totals":{oid:quantity(n) for oid,n in totals.items()},
            "priority_used":len(tied)>1,"remaining_weight_before":quantity(before),"allocated_weight":quantity(allocated),
            "remaining_weight_after":quantity(after),"quota_shortfall":quantity(quota-allocated),"allocation_bands":trace})
        winners.append(winner);remaining.remove(winner)
    result=tally.method_result;_selection(result,winners,count,reason="no_remaining_positive_support")
    result.update(quota=quantity(quota),informative_weight=informative,remaining_weight=quantity(sum((p["base"]*p["fraction"] for p in profiles),Fraction(0))),
        allocated_weight=quantity(sum((read_quantity(row["allocated_weight"]) for row in rounds),Fraction(0))),
        rounds=rounds,remaining_options=remaining,supported_options=sorted(oid for oid,n in result["scores"].items() if n>0),
        stop_totals={oid:quantity(n) for oid,n in _totals(profiles,remaining).items()},
        stop_reason="winner_count_reached" if len(winners)==count else "no_remaining_positive_support",
        priority_used=bool(tie_trace),tie_trace=tie_trace,selection_boundary_tie=False)
    return tally


def validate_allocated_record(result,record,rules,preference_weight):
    # Original rating histograms are validated by the shared v2 reader.
    allowed={"method","rule_id","scores","score_histograms","preference_weight","winner","tie_trace","priority_used","no_result_reason","option_set_version","winners","ranked_order","requested_count","filled_count","unfilled_count","unfilled_reason","supported_options","quota","informative_weight","remaining_weight","allocated_weight","rounds","remaining_options","stop_totals","stop_reason","selection_boundary_tie"}
    if set(result)!=allowed:raise ValueError("Nonaggregate allocation result")
    count=rules["num_winners"];informative=result.get("informative_weight")
    if type(informative) is not int or not 0<=informative<=preference_weight:raise ValueError("Invalid informative weight")
    quota=read_quantity(result.get("quota"))
    if quota!=Fraction(informative,count):raise ValueError("Invalid original fixed quota")
    ids=sorted(result["scores"]);remaining=list(ids);winners=[];trace=[];mass=Fraction(informative);spent=Fraction(0)
    last_totals={oid:Fraction(n) for oid,n in result["scores"].items()}
    rounds=result.get("rounds")
    if not isinstance(rounds,list) or len(rounds)>count:raise ValueError("Invalid allocation rounds")
    for i,row in enumerate(rounds):
        if not isinstance(row,dict) or set(row)!={"pool","winner","totals","priority_used","remaining_weight_before","allocated_weight","remaining_weight_after","quota_shortfall","allocation_bands"} or row.get("pool")!=remaining or not isinstance(row.get("totals"),dict) or set(row["totals"])!=set(remaining):raise ValueError("Invalid allocated candidate pool")
        totals={oid:read_quantity(n) for oid,n in row["totals"].items()}
        if any(n>min(5*mass,last_totals[oid]) for oid,n in totals.items()) or (i==0 and totals!=last_totals):raise ValueError("Invalid remaining score totals")
        highest=max(totals.values(),default=Fraction(0));tied=sorted(oid for oid,n in totals.items() if n==highest)
        if highest<=0 or row.get("winner")!=min(tied,key=lambda oid:candidate_priority(rules,rules["proposal_id"],oid)):raise ValueError("Invalid allocated-score winner")
        if type(row.get("priority_used")) is not bool or row["priority_used"]!=(len(tied)>1):raise ValueError("Invalid allocated priority flag")
        if len(tied)>1:trace.append({"stage":"allocated_score_priority","round":i+1,"pool":tied,"total":quantity(highest)})
        if read_quantity(row.get("remaining_weight_before"))!=mass:raise ValueError("Inconsistent allocation mass")
        allocated=read_quantity(row.get("allocated_weight"));after=read_quantity(row.get("remaining_weight_after"))
        if allocated!=min(quota,mass) or after!=mass-allocated or read_quantity(row.get("quota_shortfall"))!=quota-allocated:raise ValueError("Allocation does not conserve mass")
        bands=row.get("allocation_bands")
        if not isinstance(bands,list) or not bands:raise ValueError("Missing aggregate contribution bands")
        previous=Fraction(6);band_spend=Fraction(0);band_mass=Fraction(0)
        for j,band in enumerate(bands):
            if not isinstance(band,dict) or set(band)!={"contribution","remaining_mass","allocated_mass","allocated_fraction"}:raise ValueError("Nonaggregate allocation band")
            contribution=read_quantity(band["contribution"]);size=read_quantity(band["remaining_mass"]);used=read_quantity(band["allocated_mass"]);ratio=read_quantity(band["allocated_fraction"])
            if contribution>=previous or contribution>5 or size<=0 or ratio>1 or ratio<=0 or used!=size*ratio or (j<len(bands)-1 and ratio!=1):raise ValueError("Invalid descending fractional boundary allocation")
            previous=contribution;band_spend+=used;band_mass+=size
        if band_spend!=allocated or band_mass>mass:raise ValueError("Inconsistent aggregate bands")
        winner=row["winner"];winners.append(winner);remaining.remove(winner);mass=after;spent+=allocated;last_totals=totals
    from multiwinner_tally import _selection
    expected={};_selection(expected,winners,count,reason="no_remaining_positive_support")
    expected.update(remaining_options=remaining,supported_options=sorted(oid for oid,n in result["scores"].items() if n>0),
        remaining_weight=quantity(mass),allocated_weight=quantity(spent),tie_trace=trace,priority_used=bool(trace),selection_boundary_tie=False,
        stop_reason="winner_count_reached" if len(winners)==count else "no_remaining_positive_support")
    stop=result.get("stop_totals")
    if not isinstance(stop,dict) or set(stop)!=set(remaining):raise ValueError("Invalid final candidate totals")
    for oid,n in stop.items():
        n=read_quantity(n)
        if n>min(5*mass,last_totals[oid]) or (len(winners)<count and n!=0):raise ValueError("Invalid support exhaustion")
    if not rounds and any(result["scores"].values()):raise ValueError("Missing supported allocation round")
    for key,value in expected.items():
        if result.get(key)!=value:raise ValueError("Inconsistent frozen allocation summary")
    if record.get("official_winners")!=(winners if record.get("quorum_met") else []):raise ValueError("Invalid official Allocated Score winners")
