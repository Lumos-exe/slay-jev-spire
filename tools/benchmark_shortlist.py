"""Time shortlist selection on a frozen pool and compare exact ordered output."""
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire.native_sequences import generate_plans
from slay_jev_spire.planning_config import SearchConfig


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=5)
    args=parser.parse_args()
    if args.repeats<1:parser.error('repeats must be positive')
    policies={}
    for label,path in [('baseline',args.baseline),('current',ROOT/'slay_jev_spire/shortlist.py')]:
        spec=importlib.util.spec_from_file_location(label,path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        policies[label]=module
    cases=[]
    for filename in ('shortlist_mechanical_recall.json','shortlist_adversarial_recall.json'):
        for case in json.loads((ROOT/'samples'/filename).read_text(encoding='utf-8')):
            # Keep the production node/depth bounds, relaxing ONLY offline wall
            # time so host speed cannot change the pool being compared.
            pool,search=generate_plans(case['summary'],case['actions'],SearchConfig(max_ms=60000))
            results={}
            for label,module in policies.items():
                durations=[];expected=None
                for _ in range(args.repeats):
                    started=time.perf_counter();chosen,stats=module.select(pool)
                    durations.append((time.perf_counter()-started)*1000)
                    output=([p['id'] for p in chosen],stats)
                    if expected is not None and output!=expected:raise AssertionError('Nondeterministic shortlist')
                    expected=output
                results[label]=dict(median_ms=round(statistics.median(durations),3),
                    samples_ms=durations,ids=expected[0],stats=expected[1])
            identical=all(results['baseline'][k]==results['current'][k] for k in ('ids','stats'))
            cases.append(dict(case=case['name'],pool_size=len(pool),truncated=search['truncated'],
                identical_order_and_stats=identical,results=results))
    report=dict(scope='Same bounded pool per case. Exact output/performance comparison, not recall improvement.',
        baseline_sha256=sha256(args.baseline.read_bytes()).hexdigest(),
        current_sha256=sha256((ROOT/'slay_jev_spire/shortlist.py').read_bytes()).hexdigest(),cases=cases)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([dict(case=c['case'],pool=c['pool_size'],identical=c['identical_order_and_stats'],
        ms={k:v['median_ms'] for k,v in c['results'].items()}) for c in cases],ensure_ascii=False))
    if not all(c['identical_order_and_stats'] for c in cases):raise SystemExit(1)


if __name__=='__main__':main()
