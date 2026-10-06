"""Build paired requests with an inline current-board view and full reference state.

This experiment adds no predicted outcomes, ranking, candidate removal, or facts
absent from the original request. The full original state remains in the body.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from slay_jev_spire.native_view import current_board as view, expand, CURRENT_BOARD_INSTRUCTIONS

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();jobs=[]
    for path in sorted(args.source.glob('requests/*/*.jsonl')):
        request=json.loads(path.read_text(encoding='utf-8').splitlines()[0])
        name,profile,repeat=request['decision_id'].split(':')
        if profile!='native_readable':continue
        body=json.loads(request['body']);current=view(body['state'])
        for label in ('original_view','inline_current_view'):
            candidate=deepcopy(body)
            if label=='inline_current_view':
                candidate['state']={'current_board':current,'reference_state':candidate['state']}
                candidate['questions']['action']['instructions']+=CURRENT_BOARD_INSTRUCTIONS
            assert candidate['questions']['action']['criteria']==body['questions']['action']['criteria']
            jobs.append(dict(case=name,profile=label,repeat=int(repeat),body=candidate,aliases=request['aliases']))
    args.directory.mkdir(parents=True,exist_ok=True)
    with (args.directory/'requests.json').open('x',encoding='utf-8') as stream:
        json.dump(jobs,stream,ensure_ascii=False)
    print(json.dumps({'requests':len(jobs),'case_pairs':len(jobs)//2}))


if __name__=='__main__':main()
