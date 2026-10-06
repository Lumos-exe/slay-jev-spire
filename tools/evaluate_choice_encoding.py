"""Paired live-snapshot replay: serialized vs structured native option data.

No automatic correctness oracle: preserve decisions for tactical review. Candidate
sets, ordering, state, and instructions are equal within each paired repeat.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from slay_jev_spire.config import load_jev_key
    from slay_jev_spire import selectors
    from slay_jev_spire.jev_provider import capture_http
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();directory=args.directory
    load_jev_key()
    cases=json.loads((directory/'cases.json').read_text(encoding='utf-8'))
    structured=selectors.action_criteria
    def legacy(action):
        return structured(action) if action.get('kind') in {'potion','turn_plan','shop_plan'} else action['description']
    def evaluate(case,repeat,profile):
        actions=list(case['candidates']);random.Random(repeat).shuffle(actions)
        started=time.monotonic();row=dict(case=case['name'],repeat=repeat,profile=profile,
            order=[a['id'] for a in actions],candidate_count=len(actions))
        try:
            with capture_http(directory,f'{case["name"]}:{profile}:{repeat}'):
                decision=selectors.choose_jev(case['summary'],actions)
            action=decision['action']
            row.update(status='ok',selected_id=action['id'],selected_card=action.get('card',{}).get('id'),
                selected_item=action.get('item',{}).get('id'),model=decision['returned_model'],
                usage=decision.get('usage'))
        except selectors.SelectionError as error:
            row.update(status=error.code or 'selection_error')
        row['elapsed_ms']=round((time.monotonic()-started)*1000,2)
        return row
    with (directory/'results.jsonl').open('x',encoding='utf-8') as out:
        for profile,encode in [('string_options',legacy),('structured_options',structured)]:
            selectors.action_criteria=encode
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(evaluate,case,repeat,profile) for case in cases for repeat in range(3)]
                for future in as_completed(futures):
                    row=future.result();out.write(json.dumps(row)+'\n');out.flush()
                    print(json.dumps(row),flush=True)


if __name__=='__main__':main()
