"""Explicit model decision protocol; never chooses an action by local utility."""
import time


def review_reason(action, candidates):
    if len(candidates)<2:return None
    if action.get('kind')=='end':return 'native_end_with_alternatives'
    if action.get('kind') in {'play','potion'}:return 'native_action_comparison'
    if action.get('kind')!='turn_plan':return 'native_decision_comparison'
    out=action.get('outcome', {});seq=action['sequence']
    if seq==[{'kind':'end'}]:return 'empty_turn_with_alternatives'
    if (out.get('forecast_scope')=='deterministic' and out.get('player_hp_after_turn')==0
        and any(c.get('outcome',{}).get('forecast_scope')=='deterministic'
                and (c['outcome'].get('player_hp_after_turn') or 0)>0 for c in candidates)):
        return 'known_survival_conflict'
    if seq and seq[-1]['kind']=='end' and out.get('remaining_energy',0)>0:
        return 'end_with_unused_energy'
    if out.get('new_status_cards',0)>0 and not out.get('combat_won'):
        return 'adds_status_cards'
    return None


def choose_reviewed(summary, candidates, choose, *, review=True):
    """Initial full comparison, model challenger, then one model pair comparison.

    The original choice remains eligible in the final pair. Waiting is never
    vetoed, even if it triggered review. No repeated voting or local override.
    """
    started=time.monotonic()
    conditional=summary.get('combat_choice_mode')=='native_conditional_sequences'
    native=conditional or not any(c.get('kind')=='turn_plan' for c in candidates)
    protocol=('native-sequence-' if conditional else 'native-' if native else 'temporal-')+('review-v1' if review else 'flat-v1')
    common=dict(summary,_decision_stage='initial')
    common['_combat_view' if 'player' in summary else '_native_review']=('native' if native else 'temporal') if 'player' in summary else True
    initial=choose(common,candidates)
    reason=review_reason(initial['action'],candidates) if review else None
    if not reason:
        initial['decision_protocol']=protocol
        return initial
    alternatives=[c for c in candidates if c['id']!=initial['action']['id']]
    challenger=choose(dict(common,_decision_stage='challenger',_review_reason=reason),alternatives)
    pair=sorted([initial['action'],challenger['action']],key=lambda a:a['id'])
    final=choose(dict(common,_decision_stage='pair'),pair)
    results=(initial,challenger,final)
    final['decision_review']={'trigger':reason,'initial_id':initial['action']['id'],
        'challenger_id':challenger['action']['id'],'final_pair':[c['id'] for c in pair],
        'changed':initial['action']['id']!=final['action']['id'],
        'initial_candidate_count':len(candidates),'challenger_candidate_count':len(alternatives)}
    final['model_requests']=sum(r.get('model_requests',1) for r in results)
    final['usage']={k:sum(r.get('usage',{}).get(k) for r in results)
        if all(type(r.get('usage',{}).get(k)) is int for r in results) else None
        for k in ('input_tokens','output_tokens')}
    final['usage_incomplete']=any(r.get('usage_incomplete',False) for r in results)
    final['latency_ms']=round((time.monotonic()-started)*1000,2)
    final['decision_protocol']=protocol
    return final


def temporal_view(summary, candidates, state, criteria, references):
    """Readable segments and time-scoped, unweighted effects from one forecast."""
    inverse={v:k for k,v in references.items()}
    cards={c['uuid']:c for pile in ('hand','draw_pile','discard_pile','exhaust_pile') for c in summary.get(pile,[])}
    conditional_steps=state.get('turn_steps') if any(c.get('execution_contract')=='native_conditional' for c in candidates) else None
    for key in ('_combat_view','_decision_stage','_review_reason','turn_steps','simple_result_columns','simple_result_scope'):
        state.pop(key,None)
    if conditional_steps is not None:
        state['turn_steps']=conditional_steps
        state['conditional_sequence_scope']='Sequences without outcome fields use current displayed resources only. Later legality and effects are not simulated; each step is revalidated in game.'
    if not any(c.get('kind')=='turn_plan' for c in candidates):
        state['native_action_scope']='Current game-provided legal actions and live fields. No simulated turn outcomes. Execute one action, then observe the actual result.'
    else:state['prediction_semantics']={
        'after_actions':'After listed cards/potions; block and unused energy are NOT next-turn resources.',
        'if_end_now':'Conditional result of resolving current known enemy actions. player_hp_remaining is absolute HP; 0 means death.',
        'unknown':'null means not modeled/known. A segment ending at a draw needs a new observation.',
        'objective':'Win this encounter and preserve resources for later encounters; compare damage, survival, setup and actual mechanics.'}
    for candidate in candidates:
        if candidate.get('kind')=='play':
            uid=candidate['card_uuid'];card=cards.get(uid,{})
            target=candidate.get('target_index')
            criteria[candidate['id']]={'action':'play','card':card.get('id'),
                'card_ref':inverse.get(uid,uid),'cost_for_turn':card.get('native_values',{}).get('cost_for_turn',card.get('cost')),
                'free_to_play_once':card.get('free_to_play_once'),'native_description':card.get('description',card.get('raw_description')),
                'target':None if target is None else {'index':target,'id':summary['enemies'][target].get('id')},
                'native_damage_preview':next((p for p in card.get('target_damage_previews',[]) if p.get('target_index')==target),None),
                'preview_scope':'Game card fields; not final HP loss or a predicted turn.'}
            continue
        if candidate.get('kind')=='end':
            criteria[candidate['id']]={'action':'END','meaning':'End player turn now with current block; enemies execute their intents. Unused resources obey native game rules.'}
            continue
        if candidate.get('kind')!='turn_plan':continue
        if candidate.get('execution_contract')=='native_conditional':continue
        steps=[]
        for step in candidate['sequence']:
            item={'action':step['kind']}
            if step['kind']=='play':
                item.update(card=step['card_id'],card_ref=inverse.get(step['card_uuid'],step['card_uuid']))
                if step.get('selection_uuid'):
                    uid=step['selection_uuid'];item['selected_card']={'id':cards.get(uid,{}).get('id'),'ref':inverse.get(uid,uid)}
            if step['kind']=='potion':item['potion']=step['potion_id']
            if step.get('target_index') is not None:
                index=step['target_index'];item['target']={'index':index,'id':summary['enemies'][index].get('id')}
            steps.append(item)
        o=candidate['outcome']
        criteria[candidate['id']]={'actions':steps,'after_actions':{
            'enemy_hp':o.get('enemy_hp_by_target'),'block_before_enemy_actions':o.get('block'),
            'unused_energy':o.get('remaining_energy'),'player_powers':o.get('powers'),
            'generated_cards':o.get('generated_card_counts',{}),'exhausted_cards':o.get('exhausted_card_counts',{}),
            'self_hp_spent':o.get('self_damage'),'self_healing':o.get('healing')},
            'if_end_now':{'player_hp_remaining':o.get('player_hp_after_turn'),
                'incoming_hp_loss':o.get('incoming_hp_loss'),'remaining_block_after_enemy_actions':o.get('remaining_block_after_turn'),
                'scope':o.get('forecast_scope')},
            'combat_won':o.get('combat_won'),'observation_boundary':candidate.get('checkpoint'),
            'unresolved':candidate.get('uncertainties',[])}
    return state,criteria


def comparison_instruction(summary):
    stage=summary.get('_decision_stage');text=''
    if stage=='challenger':
        text+='本次从这些候选中选出最有价值的替代方案，用于下一次两方案对照。'
        if summary.get('_review_reason')=='known_survival_conflict':
            text+='已知存在能够活过当前攻击的方案，优先找出这些活路。'
    if stage=='pair':text+='本次只有两个方案，直接逐项比较它们；如果等待或不消费更有价值，可以选择它。'
    return text


def instructions(summary):
    if summary.get('_combat_view')=='native':
        return ('你负责杀戮尖塔，选择当前最有助于赢得战斗和后续整局的一步原生合法动作。'
            '游戏提供手牌、实时费用、能力、遗物、敌人状态及意图；这里没有程序收益评分或模拟整回合结果。'
            '考虑出牌顺序与后续可用手牌、实际攻击和格挡需求、蓄力与增益、状态污染和药水。'
            '不要把可打等同于有价值；也不要无理由放弃当前能做的有效行动。等待本身可以是合理选择。'
            '未知抽牌必须等执行后再观察，不假设抽到有利牌。描述与回调来自游戏，回调列表不等于完整效果代码。'
            '共享的card_templates、native_value_templates与card_ref对应同一张牌；实时数据优先于基础档案。'
            '只返回当前候选ID。')+comparison_instruction(summary)
    base=('选择一个合法动作段。结合当前手牌、费用、敌人招式和机制，比较实际收益、伤害、存活和后续回合能力。'
          'actions按顺序执行；after_actions是出牌后的状态，if_end_now是假如此刻结束回合的后果。'
          'player_hp_remaining是剩余生命，0表示死亡。格挡通常在下个玩家回合清空，未用能量通常不保留。'
          '信息边界后的抽牌未知；不能把null当成零伤害，也不能假设抽到有利牌。'
          '只有已推演的方案带有结果字段，原生单动作没有预测结果。'
          '等待可能有用，但应比较尚能使用的牌和药水；状态牌、副作用与敌人反应也属于后果。'
          'card_templates和native_value_templates为共享资料；只返回当前候选ID。')
    return base+comparison_instruction(summary)
