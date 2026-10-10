"""Deterministic pure-counter time/memory/trace benchmarks at approved limits."""
import sys,json,time,tracemalloc,random,platform,os,gzip
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from multiwinner_tally import count_multiwinner
from voting_methods import new_voting_rules
METHODS=('score','star','majority_judgment','ranked_pairs','allocated_score')
def main():
    results=[]
    cases=[(1000,20,2,1,'random'),(1000,20,5,1,'random'),(10000,20,5,1,'random'),(10000,20,20,1,'random'),(1000,120,5,1,'random'),(1000,120,120,1,'random'),(1000,120,120,10**9,'dense_tie'),(1000,20,10,10**12,'random')]
    if '--supplement' in sys.argv:
        cases=[(1000,120,120,10**12,'heterogeneous_weights')]
    for method in METHODS:
        for n,c,k,w,profile in cases:
            rng=random.Random(113);ids=[str(i) for i in range(c)]
            ratings=[{oid:5 if profile=='dense_tie' else rng.randrange(6) for oid in ids} for _ in range(n)]
            ballots=[({'rank_groups':[[oid] for oid in ids]} if profile=='dense_tie' else {'rank_groups':[[oid for oid in ids if row[oid]==v] for v in range(5,-1,-1) if any(row[oid]==v for oid in ids)]},w) for row in ratings] if method=='ranked_pairs' else [({'grades' if method=='majority_judgment' else 'scores':row},w) for row in ratings]
            if profile=='heterogeneous_weights':
                ballots=[(payload,rng.randrange(1,w+1)) for payload,_ in ballots]
            rules=new_voting_rules(method,'benchmark',k)
            start=time.perf_counter();result=count_multiwinner(method,ids,ballots,rules,'benchmark',k);elapsed=time.perf_counter()-start
            tracemalloc.start();count_multiwinner(method,ids,ballots,rules,'benchmark',k);_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            raw=json.dumps(result.to_record(),separators=(',',':')).encode()
            fractions=[]
            def visit(value):
                if isinstance(value,dict):
                    if set(value)=={'numerator','denominator'}:fractions.append(int(value['denominator']).bit_length())
                    else:
                        for item in value.values():visit(item)
                elif isinstance(value,list):
                    for item in value:visit(item)
            visit(result.method_result)
            row=dict(method=method,voters=n,options=c,winners=k,weight=w,profile=profile,seconds=round(elapsed,4),peak_counter_bytes=peak,serialized_bytes=len(raw),gzip_bytes=len(gzip.compress(raw)),max_denominator_bits=max(fractions,default=0),queries=0)
            results.append(row);print(json.dumps(row),flush=True)
    report={'python':platform.python_version(),'platform':platform.platform(),'logical_processors':os.cpu_count(),'timing':'untraced; input prebuilt; separate tracemalloc counter peak; pure counter has zero SQL','results':results}
    Path(sys.argv[1]).write_text(json.dumps(report,indent=2))
if __name__=='__main__':main()
