"""Validate end-turn forecasts against actual receipts, without model calls."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from slay_jev_spire import rules
from slay_jev_spire.state import prepare_native_combat


def audit(paths):
    counts=Counter();failures=[];seen=set()
    for path in paths:
        opener=gzip.open if path.suffix=='.gz' else open
        with opener(path,'rt',encoding='utf-8') as source:
            for line in source:
                row=json.loads(line)
                if row.get('status')!='action_confirmed' or row.get('decision',{}).get('action',{}).get('kind')!='end':continue
                key=(row['run_id'],row['step_id'])
                if key in seen:continue
                seen.add(key);counts['end_receipts']+=1
                summary,_=prepare_native_combat(row['before'])
                out=rules.outcome(rules.initial(summary))
                if out['forecast_scope']!='deterministic':
                    counts['uncertified']+=1;continue
                game=row['after']['game_state']
                actual=game.get('combat_state',{}).get('player',{}).get('current_hp',game.get('current_hp'))
                if actual is None:
                    counts['missing_actual_hp']+=1;continue
                predicted=out['player_hp_after_turn'];counts['certified']+=1
                counts['exact_hp_matches']+=predicted==actual
                counts['predicted_fatal']+=predicted<=0
                counts['actual_fatal']+=actual<=0
                false_fatal=predicted<=0<actual
                false_safe=actual<=0<predicted
                counts['false_fatal']+=false_fatal;counts['false_safe']+=false_safe
                if predicted!=actual:
                    failures.append(dict(run_id=row['run_id'],step=row['step_id'],predicted_hp=predicted,
                        actual_hp=actual,false_fatal=false_fatal,false_safe=false_safe,
                        floor=row['before']['game_state'].get('floor'),screen_after=game.get('screen_type')))
    return dict(counts=dict(counts),mismatches=failures,
                scope='Observed END receipts only; not proof for unexecuted multi-action forecasts.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=audit(args.paths)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
