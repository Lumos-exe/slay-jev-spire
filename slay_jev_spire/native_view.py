"""Expand current native facts for readability while retaining the full state."""
from copy import deepcopy


CURRENT_BOARD_INSTRUCTIONS=(
    ' current_board逐项展开当前真实手牌、角色状态和敌人意图；其中没有回合后果预测。'
    'reference_state完整保留原局面和所有模板、牌堆、机制资料。'
    '当前手牌与永久牌组、弃牌堆不同；先核对当前可用资源，再比较候选。')


def expand(value,state):
    if isinstance(value,list):return [expand(v,state) for v in value]
    if not isinstance(value,dict):return value
    ref=value.get('$native')
    if isinstance(ref,str) and ref in state.get('native_value_templates',{}):
        return expand(state['native_value_templates'][ref],state)
    ref=value.get('$card')
    if isinstance(ref,str) and ref in state.get('card_templates',{}):
        result=deepcopy(state['card_templates'][ref])
        result.update({k:v for k,v in value.items() if k not in {'$card','$remove'}})
        for key in value.get('$remove',[]):result.pop(key,None)
        return expand(result,state)
    return {k:expand(v,state) for k,v in value.items()}


def current_board(state):
    def pick(value,keys):return {k:value[k] for k in keys if k in value}
    power_fields=('id','name','amount','description','native_description','power_type')
    def powers(value):return [pick(p,power_fields) for p in value]
    player=expand(state.get('player',{}),state)
    result={'player':pick(player,('current_hp','max_hp','block','energy')),
            'turn':state.get('turn'),'hand':[],'enemies':[]}
    result['player']['powers']=powers(player.get('powers',[]))
    for c in expand(state.get('hand',[]),state):
        result['hand'].append(pick(c,('uuid','id','name','type','cost','native_values','description',
            'free_to_play_once','exhausts','ethereal','retain','self_retain','is_playable','target_damage_previews')))
    for index,e in enumerate(expand(state.get('enemies',[]),state)):
        item=pick(e,('id','name','current_hp','max_hp','block','intent','move_name',
                    'move_id','move_adjusted_damage','move_hits','is_gone','half_dead'))
        item['index']=index;item['powers']=powers(e.get('powers',[]));result['enemies'].append(item)
    result['relics']=[pick(r,('id','name','description','native_description','counter','used_up'))
                      for r in state.get('relics',[])]
    result['potions']=deepcopy(state.get('potions',[]))
    return result


def with_current_board(state):
    return {'current_board':current_board(state),'reference_state':state}
