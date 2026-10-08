"""Deterministic synthetic pure-counter benchmark; no database or network.

Run from backend: python scripts/benchmark_phase109_star.py
Peak memory is additional counter allocation (prebuilt input excluded).
This does not substitute for endpoint concurrency/connection measurements.
"""
import json
import os
from pathlib import Path
import platform
import random
import sys
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experimental_tally import count_star, count_score
from voting_methods import new_voting_rules


def main():
    method = sys.argv[1] if len(sys.argv) > 1 else "star"
    counter = {"star": count_star, "score": count_score}[method]
    results = []
    cases = [(1000, 20, 1, "random"), (10000, 20, 1, "random"),
             (1000, 120, 1, "random"), (1000, 120, 10**9, "all_tie"),
             (1000, 20, 10**9, "random"), (1000, 20, 10**12, "random")]
    for n, c, weight, profile in cases:
        rng = random.Random(109)
        ids = [str(i) for i in range(c)]
        ballots = [({"scores": {oid: (5 if profile == "all_tie" else rng.randrange(6))
                               for oid in ids}}, weight) for _ in range(n)]
        rules = new_voting_rules(method, "benchmark")
        started = time.perf_counter()
        counter(ids, ballots, rules, "benchmark")
        seconds = time.perf_counter() - started
        tracemalloc.start()
        counter(ids, ballots, rules, "benchmark")
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results.append(dict(voters=n, options=c, weight=weight, profile=profile,
                            seconds=round(seconds, 4), peak_counter_bytes=peak, queries=0))
    print(json.dumps({"method": method, "machine": platform.platform(), "python": platform.python_version(),
                      "processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
                      "logical_processors": os.cpu_count(), "results": results}, indent=2))


if __name__ == "__main__":
    main()
