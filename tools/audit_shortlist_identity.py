"""Measure cosmetic-identity sensitivity; witnesses are not optimality proofs."""
import argparse
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire.native_sequences import generate_plans


def witness_matches(plan,witness):
    if witness.get('no_potions') and any(s['kind']=='potion' for s in plan['sequence']):
        return False
    played=[s for s in plan['sequence'] if s['kind']=='play']
    if 'unordered_cards' in witness:
        return sorted(s.get('card_id') for s in played)==sorted(witness['unordered_cards']) and all(s.get('target_index')==witness['target'] for s in played)
    if 'ordered_cards' in witness:
        return [s.get('card_id') for s in played]==witness['ordered_cards'] and all(s.get('target_index')==witness['target'] for s in played)
    return any(s.get('card_id') in witness['contains_any_card'] for s in played)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy-file',type=Path,default=ROOT/'slay_jev_spire/shortlist.py')
    parser.add_argument('--fixtures',type=Path,default=ROOT/'samples/shortlist_mechanical_recall.json')
    parser.add_argument('--repeats',type=int,default=100)
    parser.add_argument('--allow-truncated',action='store_true',help='Report bounded-pool recall separately instead of requiring complete enumeration.')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.repeats<1:parser.error('repeats must be positive')
    spec=importlib.util.spec_from_file_location('audited_shortlist',args.policy_file)
    policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
    rng=random.Random(20261006);results=[]
    for case in json.loads(args.fixtures.read_text(encoding='utf-8')):
        pool,search=generate_plans(case['summary'],case['actions'])
        if not search['complete_enumeration'] and not args.allow_truncated:raise RuntimeError('Fixture enumeration truncated')
        baseline,_=policy.select(pool);baseline_ids=[p['id'] for p in baseline]
        trials=[]
        for repeat in range(args.repeats):
            changed=deepcopy(pool);names={}
            for plan in changed:
                for step in plan['sequence']:
                    for field in ('card_uuid','selection_uuid'):
                        uid=step.get(field)
                        if uid is not None:
                            # Match the original diagnostic's RNG consumption.
                            step[field]=names.setdefault(uid,f'{rng.getrandbits(128):032x}')
            chosen,_=policy.select(changed);ids=[p['id'] for p in chosen]
            trials.append(dict(repeat=repeat,retained=len(chosen),common=len(set(ids)&set(baseline_ids)),
                               identical_selection_and_order=ids==baseline_ids,
                               witness_recalled=any(witness_matches(p,case['witness']) for p in chosen)))
        results.append(dict(case=case['name'],candidates=len(pool),complete_enumeration=search['complete_enumeration'],
                            truncated=search['truncated'],generator_recall=any(witness_matches(p,case['witness']) for p in pool),
                            baseline_recall=any(witness_matches(p,case['witness']) for p in baseline),
                            witness_recalled=sum(t['witness_recalled'] for t in trials),
                            identical_selection_and_order=sum(t['identical_selection_and_order'] for t in trials),
                            mean_common=sum(t['common'] for t in trials)/len(trials),trials=trials))
    report=dict(policy_sha256=sha256(args.policy_file.read_bytes()).hexdigest(),
                fixtures_sha256=sha256(args.fixtures.read_bytes()).hexdigest(),seed=20261006,repeats=args.repeats,
                scope='Same pool and meaning; rename opaque UUIDs only. Witness recall is not general optimal-plan recall.',cases=results)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k!='trials'} for r in results],ensure_ascii=False))


if __name__=='__main__':main()
