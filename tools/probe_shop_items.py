"""Paired replay exposing native merchandise facts directly beside each choice."""
from copy import deepcopy
from hashlib import sha256
import argparse
import gzip
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire.state import enrich_summary


def item_facts(action):
    item=action['item'];kind=action['kind']
    result={'kind':kind,'name':item.get('name'),'id':item.get('id'),
            'price_gold':item['price']}
    if kind=='screen_shop_purge':
        result['description']='永久移除一张牌；具体卡牌在随后的原生选择界面中选择。'
    elif kind=='screen_shop_card':
        card=enrich_summary({'card':item},{})['card']
        result.update(card_type=card.get('type'),energy_cost=card.get('cost'),
            native_values=card.get('native_values'),upgrades=card.get('upgrades'),
            description=card.get('description'),exhausts=card.get('exhausts'),
            ethereal=card.get('ethereal'))
    else:result['description']=item.get('native_description',item.get('description'))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();jobs=[];sources=[]
    specs=[('series-03','native-loop-03-fresh',1,312,'act_two_healing'),
           ('series-03','native-loop-03-fresh',2,336,'act_two_options'),
           ('series-01','native-loop-01',0,22,'early_shop_after_inflame'),
           ('series-01','native-loop-01',0,97,'early_shop_offering'),
           ('series-01','native-loop-01',0,114,'shop_before_guardian')]
    for archive,series,index,step,name in specs:
        base=ROOT/'logs/native-loop'/archive/'logs'
        with gzip.open(base/f'series/{series}/run-{index}.jsonl.gz','rt',encoding='utf-8') as stream:
            row=next(r for r in map(json.loads,stream) if r.get('status')=='request_started' and r['step_id']==step)
        folder=base/'live/requests'/sha256(row['decision_id'].encode()).hexdigest()
        request=None
        for path in folder.glob('*.jsonl'):
            records=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            if any(r.get('event')=='http_response' and r.get('status_code')==200 for r in records):
                request=records[0];break
        if request is None:raise ValueError(row['decision_id'])
        original=json.loads(request['body']);actions={a['id']:a for a in row['candidates']}
        sources.append({'case':name,'run_id':row['run_id'],'step':step,'choices':[
            {'id':a['id'],'item':a.get('item')} for a in row['candidates']]})
        for repeat in range(3):
            for profile in ('reference_choices','native_item_choices'):
                body=deepcopy(original)
                if profile=='native_item_choices':
                    for wire_id,criterion in body['questions']['action']['criteria'].items():
                        action=actions[request['aliases'].get(wire_id,wire_id)]
                        if action['kind'].startswith('screen_shop_') and 'item' in action:
                            criterion['native_item']=item_facts(action)
                jobs.append(dict(case=name,repeat=repeat,profile=profile,body=body,aliases=request['aliases']))
    args.directory.mkdir(parents=True,exist_ok=True)
    with (args.directory/'requests.json').open('x',encoding='utf-8') as stream:json.dump(jobs,stream,ensure_ascii=False)
    (args.directory/'sources.json').write_text(json.dumps(sources,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'requests':len(jobs),'cases':len(sources)}))


if __name__=='__main__':main()
