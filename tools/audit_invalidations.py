"""Compare recorded state changes which invalidated a proposed native action."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire.session import gameplay_state


def differences(left,right,path=''):
    if isinstance(left,dict) and isinstance(right,dict):
        result=[]
        for key in sorted(left.keys()|right.keys()):
            if key not in left or key not in right:
                result.append(dict(path=path+'/'+key,before=left.get(key),after=right.get(key)))
            else:result.extend(differences(left[key],right[key],path+'/'+key))
        return result
    if isinstance(left,list) and isinstance(right,list) and len(left)==len(right):
        return [d for index,(a,b) in enumerate(zip(left,right)) for d in differences(a,b,path+'/'+str(index))]
    return [] if left==right else [dict(path=path,before=left,after=right)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();previous=None;report=[]
    with (ROOT/'logs/live/runs.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            if not line.endswith('\n') or args.run_id not in line:continue
            row=json.loads(line)
            if row.get('run_id')!=args.run_id:continue
            if row['status']=='decision':previous=row
            if row['status']=='decision_invalidated' and previous:
                report.append(dict(step=row['step_id'],floor=row['before'].get('game_state',{}).get('floor'),
                    old_revision=previous['before'].get('jev_protocol',{}).get('revision'),
                    new_revision=row['before'].get('jev_protocol',{}).get('revision'),
                    differences=differences(gameplay_state(previous['before']),gameplay_state(row['before']))))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in item.items() if k!='differences'} |
        {'changed_paths':[d['path'] for d in item['differences']]} for item in report],ensure_ascii=True))


if __name__=='__main__':main()
