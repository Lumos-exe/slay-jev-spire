"""Summarize transaction evidence for one actual run without loading all states."""
import argparse
from collections import Counter
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-id',required=True)
parser.add_argument('--include-run-id',action='append',default=[],help='Additional controller segments of the same game.')
parser.add_argument('--offset',type=int,default=0)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
sent=Counter();committed=Counter();statuses=Counter();faults=[];stops=[];battles=[];result=None
run_ids={args.run_id,*args.include_run_id}
identifiers=[value.encode() for value in run_ids]
with (ROOT/'logs/live/runs.jsonl').open('rb') as stream:
    stream.seek(args.offset)
    for line in stream:
        if not any(identifier in line for identifier in identifiers) or not line.endswith(b'\n'):continue
        row=json.loads(line)
        if row.get('run_id') not in run_ids:continue
        status=row.get('status');statuses[status]+=1
        tx=row.get('transaction_id')
        if status=='command_sent' and tx:sent[tx]+=1
        if status=='action_confirmed' and row.get('native_receipt'):committed[tx]+=1
        if status=='fault_injected':faults.append({'fault':row['fault'],'transaction_id':tx})
        if status=='stopped':stops.append({k:row.get(k) for k in ('step_id','reason','message')})
        if status=='battle_complete':battles.append(row['result'])
        if status=='complete':result=row.get('result')
report=dict(run_id=args.run_id,event_counts=dict(statuses),result=result,battles=battles,
    included_run_ids=sorted(run_ids),
    sent_transactions=len(sent),native_commits=len(committed),duplicate_commit_ids=[k for k,n in committed.items() if n>1],
    technical_stops=stops,
    faults=[{**f,'send_count':sent[f['transaction_id']],'commit_count':committed[f['transaction_id']]} for f in faults])
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
