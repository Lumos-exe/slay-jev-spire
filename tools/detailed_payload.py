"""Detailed condition C kept solely for reproducible offline ABC experiments."""
from copy import deepcopy
from collections import Counter
from hashlib import sha256
import json


def plan_criteria(action):
    if action.get('kind')=='shop_plan':
        return {k:deepcopy(action[k]) for k in ('kind','cost','gold_left','purchases')}
    if action.get('kind') == 'potion':
        return {'kind':'potion','subaction':action.get('subaction'),
                'potion_index':action.get('potion_index'),'target_index':action.get('target_index'),
                'potion':deepcopy(action.get('potion',{'id':action.get('potion_id')})),
                'description':action['description'],
                'followup':'Use does not end the turn. Observe actual effects or generated choices, then continue planning; no unobserved result is assumed.'}
    if action.get('kind') != 'turn_plan':
        return action['description']
    # Full plans remain in JSONL. Send decision facts once, not repeated prose,
    # UI names, and a second full outcome inside every conditional continuation.
    out = action.get('outcome', {})
    fields = ('enemy_hp_by_target','enemy_hp_after_turn_by_target','incoming_hp_loss','player_hp_after_turn',
              'standing_hp_loss_estimate','remaining_energy','block','powers',
              'self_damage','healing','draw_count','generated_cards','exhaust_count',
              'combat_won','forecast_scope','generated_card_counts','generated_card_types',
              'new_status_cards','new_curse_cards','effective_block','wasted_block',
              'remaining_block_after_turn','retained_block','potions_used',
              'unexhausted_status_cards','unexhausted_curse_cards','exhausted_card_counts')
    result = {'sequence':[{k:v for k,v in s.items() if k!='card_name' and v is not None} for s in action['sequence']],
              'outcome':{k:out[k] for k in fields if k in out},
              'checkpoint':action.get('checkpoint'),'uncertainties':action.get('uncertainties',[])}
    result['tactical_summary']={k:out.get(k) for k in ('enemy_hp_by_target','enemy_hp_after_turn_by_target',
        'player_hp_after_turn','standing_hp_loss_estimate','remaining_energy','block','forecast_scope','combat_won')}
    result['tactical_summary']['boundary']=action.get('checkpoint') or ('END' if action['sequence'] and action['sequence'][-1]['kind']=='end' else 'combat_over')
    if out.get('interruptions'): result['outcome']['interruptions']=deepcopy(out['interruptions'])
    if out.get('interruptions'):
        result['tactical']={'cancelled_current_attack_damage':sum(x.get('cancelled_attack_damage') or 0 for x in out['interruptions']),
            'hp_loss_estimate_after_cancellation':out.get('standing_hp_loss_estimate'),
            'observe_reaction_then_continue':True}
    if out.get('economy',{}).get('targets'): result['outcome']['economy']=deepcopy(out['economy'])
    if out.get('draw_prospects'):
        result['draw_prospects']=[{k:p[k] for k in ('count','pool_size','affordable_cards','expected_affordable_draws','has_on_draw_risks') if k in p} for p in out['draw_prospects']]
    if out.get('position'): result['position']=deepcopy(out['position'])
    growing=[{'target_index':e['index'],'hp_after_actions':e['hp_after_cards'],
              'strength_after_actions':e['powers_after_cards'].get('Strength',0),
              'permanent_strength_per_skill':e['powers_after_cards']['Anger']}
             for e in out.get('position',{}).get('enemies_after_cards',[]) if e.get('powers_after_cards',{}).get('Anger')]
    if growing:
        result.setdefault('tactical',{})['enemies_growing_from_skills']=growing
    continuation=out.get('known_hand_continuation')
    if continuation:
        result['known_hand_continuation']={'sequence':continuation['sequence'],
            **{k:continuation['outcome'][k] for k in ('enemy_hp_by_target','enemy_hp_after_turn_by_target','incoming_hp_loss','player_hp_after_turn',
                'remaining_energy','block','effective_block','wasted_block','retained_block',
                'unexhausted_status_cards','unexhausted_curse_cards') if k in continuation['outcome']},
            'scope':'conditional_known_hand'}
    if action.get('notes'):
        result['notes']=[{k:v for k,v in n.items() if k!='continuation'} for n in action['notes']]
    return result


def model_payload(summary, actions):
    from slay_jev_spire.selectors import strategy_context, share_native_values
    """Lossless card-template sharing and request-local identity aliases."""
    templates = {}; aliases = {}
    dynamic = {'uuid','card_uuid','hand_index','play_index','is_playable','valid_target_indices','effect','target_damage_previews'}
    def alias(value):
        if value not in aliases: aliases[value] = f'c{len(aliases)+1}'
        return aliases[value]
    def visit(value, cards=False):
        if isinstance(value,list): return [visit(v,cards) for v in value]
        if not isinstance(value,dict): return value
        if cards and 'id' in value and 'uuid' in value and ('native_values' in value or 'type' in value):
            template={k:visit(v,False) for k,v in value.items() if k not in dynamic}
            key='card_'+sha256(json.dumps([value['id'],value.get('upgrades',0)],ensure_ascii=False).encode()).hexdigest()[:12]
            if key not in templates: templates[key]=template
            instance={k:alias(v) if k in {'uuid','card_uuid'} else visit(v,False) for k,v in value.items() if k in dynamic}
            instance.update({k:v for k,v in template.items() if k not in templates[key] or v!=templates[key][k]})
            removed=[k for k in templates[key] if k not in template]
            if removed: instance['$remove']=removed
            return {'$card':key,**instance}
        return {k:alias(v) if k in {'uuid','card_uuid','selection_uuid'} and isinstance(v,str) else visit(v,cards) for k,v in value.items()}
    state=visit(summary,True)
    if summary.get('screen_type') not in {None,'NONE'} and summary.get('deck'):
        deck=summary['deck'];counts=Counter(c.get('id') for c in deck)
        state['deck_profile']={'size':len(deck),'starting_cards':sum(counts[k] for k in ('Strike_R','Defend_R','Bash')),
            'types':dict(Counter(c.get('type','unknown') for c in deck)),'card_counts':dict(counts)}
        strategy = strategy_context(summary, actions)
        if strategy: state['strategy_context'] = strategy
    criteria=visit({a['id']:plan_criteria(a) for a in actions})
    turn_ids={a['id'] for a in actions if a.get('kind')=='turn_plan'}
    if turn_ids:
        first=next(c for k,c in criteria.items() if k in turn_ids)
        outcome_base=deepcopy(first['outcome'])
        state['outcome_baseline']=outcome_base
        tactical_columns=list(first['tactical_summary'])
        state['tactical_columns']=tactical_columns
        step_keys={};turn_steps={}
        for ident,criterion in criteria.items():
            if ident not in turn_ids: continue
            criterion['tactical_summary']=[criterion['tactical_summary'][k] for k in tactical_columns]
            sequence=[]
            for step in criterion['sequence']:
                key=json.dumps(step,sort_keys=True,ensure_ascii=False)
                if key not in step_keys:
                    ref='s'+str(len(step_keys));step_keys[key]=ref;turn_steps[ref]=step
                sequence.append(step_keys[key])
            criterion['sequence']=sequence
            out=criterion['outcome']
            criterion['outcome']={'$delta':{k:v for k,v in out.items() if k not in outcome_base or v!=outcome_base[k]}}
            removed=[k for k in outcome_base if k not in out]
            if removed: criterion['outcome']['$remove']=removed
        state['turn_steps']=turn_steps
    position_templates={};position_keys={};string_counts=Counter()
    def count_strings(value):
        if isinstance(value,str):string_counts[value]+=1
        elif isinstance(value,list):
            for item in value:count_strings(item)
        elif isinstance(value,dict):
            for item in value.values():count_strings(item)
    for criterion in criteria.values():
        if isinstance(criterion,dict):
            count_strings(criterion.get('position'))
            count_strings(criterion.get('outcome'))
    def share_position(value):
        if not isinstance(value,(dict,list)):
            if not isinstance(value,str) or string_counts[value]<2:return value
            ref_size=len(json.dumps({'$position':'f'+str(len(position_templates))}))
            if len(json.dumps(value,ensure_ascii=False))<=ref_size:return value
        key=json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        if key not in position_keys:
            content=({k:share_position(v) for k,v in value.items()} if isinstance(value,dict)
                     else [share_position(v) for v in value] if isinstance(value,list) else value)
            alias='f'+str(len(position_templates))
            position_keys[key]=alias;position_templates[alias]=content
        return {'$position':position_keys[key]}
    baseline=next((c['position'] for c in criteria.values() if isinstance(c,dict) and 'position' in c),None)
    if baseline is not None: state['position_baseline']=share_position(baseline)
    for criterion in criteria.values():
        if isinstance(criterion,dict) and 'position' in criterion:
            delta={k:v for k,v in criterion['position'].items() if v!=baseline.get(k)}
            criterion['position']={'$position_delta':share_position(delta)['$position']}
    for ident,criterion in criteria.items():
        if ident in turn_ids:
            criterion['outcome']['$delta']=share_position(criterion['outcome']['$delta'])
    if position_templates:
        # Repeated record shapes have identical field names. Share the names,
        # not the values, so no simulated fact or candidate is removed.
        shapes=Counter(tuple(value) for value in position_templates.values()
                       if isinstance(value,dict) and len(value)>1)
        schemas={};shape_ids={}
        for shape,count in shapes.items():
            ident='r'+str(len(schemas))
            members=[v for v in position_templates.values() if isinstance(v,dict) and tuple(v)==shape]
            original=sum(len(json.dumps(v,ensure_ascii=False)) for v in members)
            encoded=sum(len(json.dumps({'$record':[ident,list(v.values())]},ensure_ascii=False)) for v in members)
            encoded+=len(json.dumps({ident:shape},ensure_ascii=False))
            if encoded<original:
                schemas[ident]=list(shape);shape_ids[shape]=ident
        for ident,value in list(position_templates.items()):
            if isinstance(value,dict) and tuple(value) in shape_ids:
                position_templates[ident]={'$record':[shape_ids[tuple(value)],list(value.values())]}
        state['position_templates']=position_templates
        if schemas:state['position_schemas']=schemas
    if summary.get('screen_type')=='SHOP_SCREEN':
        from .shopping import PURCHASES
        registry={};items={}
        def ref(action):
            key=action['id']
            if key not in registry:
                registry[key]='s'+str(len(registry))
                item=action.get('item',{})
                items[registry[key]]=visit(dict(kind=action['kind'],item_id=item.get('id','purge'),
                    card_uuid=item.get('uuid'),price=item['price']))
            return registry[key]
        for action in actions:
            steps=action.get('steps') if action.get('kind')=='shop_plan' else [action] if action.get('kind') in PURCHASES else None
            if steps:
                cost=sum(s['item']['price'] for s in steps)
                criteria[action['id']]={'buy':[ref(s) for s in steps],'gold_cost':cost,
                                        'gold_left':summary.get('gold',0)-cost}
        if items:
            state['shop_items']=items
            state['shop_item_scope']='Package buy entries reference shop_items; native descriptions and full cards are in screen_state/card_templates. Costs are gold, not energy.'
            for k in ('shop_bundles','shop_bundle_scope'):
                state.get('strategy_context',{}).pop(k,None)
    if templates: state={'card_templates':dict(sorted(templates.items())),**state}
    state,criteria=share_native_values(state,criteria)
    return state,criteria,{v:k for k,v in aliases.items()}
