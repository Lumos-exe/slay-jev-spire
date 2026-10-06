"""Conditional sequences of visible resources, without a combat simulator.

Only the first action is certified legal by the game. Later actions are
proposals under unchanged costs/resources, checked again against the game.
No card/relic name or estimated damage participates in candidate generation.
"""
from collections import deque
from copy import deepcopy
from hashlib import sha256
import json
import time

from .planning_config import SearchConfig

INSTRUCTIONS = (
    '你负责杀戮尖塔战斗。从统一候选池选择最有助于赢得战斗和整局的牌序。'
    'actions直接列出按顺序执行的牌名和目标，sequence与turn_steps保留精确牌实例；finish=END表示执行后结束回合，'
    'finish=OBSERVE表示执行动作段后观察并重新规划，绝不等于结束回合。'
    '完整牌序与观察段一起比较。需要先抽牌、弃牌、生成牌、获取能量或改变费用再决定时，可选相应观察段。'
    '已能决定后续动作时选择包含它们的牌序；完整牌序也会逐步核验，不必为了例行核验而只选一张牌。'
    '这些是条件牌序：只有首步已获游戏合法性确认；后续按当前显示费用与资源枚举，'
    '没有计算卡牌、遗物、能力或敌人的效果，没有伤害预测或本地收益评分。'
    '你须结合完整原生描述、能力、遗物、敌人意图和机制判断后续是否可行以及顺序价值。'
    '执行中逐步检查原生合法性；手牌、能量、费用、新遗物、目标或敌人意图改变时会停止旧牌序并重新规划。'
    '不能假设未知抽牌，也不能把没有结果字段视为零收益。候选顺序不表示推荐。'
    '候选范围与截断情况见candidate_generation；新增资源产生的后续牌序在实际观察后补充。'
    '卡牌、药水和敌人的当前字段及完整档案均在局面中；只返回候选ID。')


def cost(card):
    if card.get('native_values',{}).get('free_to_play') or card.get('free_to_play_once'):
        return 0
    return card.get('native_values', {}).get('cost_for_turn', card.get('cost'))


def observation(summary):
    """Resource envelope; damage/block previews are deliberately not forecasts."""
    return dict(identity=deepcopy(summary.get('identity')), turn=summary.get('turn'),
        hand=sorted((c['uuid'], cost(c)) for c in summary.get('hand', [])),
        energy=summary['player']['energy'],
        relic_ids=sorted(r['id'] for r in summary.get('relics', [])),
        potions=[p['id'] for p in summary.get('potions', [])],
        enemies=[(e.get('entity_id'), e.get('id'), e.get('move_id'), e.get('intent'),
                  e.get('is_gone', False), e.get('half_dead', False), e['current_hp'] > 0)
                 for e in summary.get('enemies', [])])


def bind_plan_step(step, summary, actions):
    # JSON roundtrips turn tuples into lists in journals.
    if json.dumps(observation(summary), sort_keys=True) != json.dumps(step['expected_before'], sort_keys=True):
        return None
    keys = ('kind', 'card_uuid', 'target_index') if step['kind'] == 'play' else (
        ('kind', 'potion_index', 'potion_id', 'subaction', 'target_index') if step['kind'] == 'potion' else ('kind',))
    return next((a for a in actions if all(a.get(k) == step.get(k) for k in keys)), None)


def generate_plans(summary, actions, config=None):
    config = config or SearchConfig()
    started = time.perf_counter()
    stats = dict(policy='native_conditional_sequences', expanded=0, truncated=[],
        fallback_required=False, beam_pruned=0, candidate_cap_pruned=0,
        budgets=dict(max_nodes=config.max_nodes, max_depth=config.max_depth, max_ms=config.max_ms),
        scope='All ordered visible-resource sequences within current displayed energy/costs; '
              'future legality is conditional. Drawn/generated cards and changed costs require a new observation.')
    if 'player' not in summary:
        return [], stats
    root = observation(summary)
    cards = {c['uuid']: c for c in summary['hand']}
    first = [a for a in actions if a['kind'] in {'play', 'potion'}]
    end_allowed = any(a['kind'] == 'end' for a in actions)
    # Later targets are proposals. Do not confuse a root canUse=false with a
    # permanent ban (e.g. a card whose hand-dependent condition can be cleared).
    later = []
    for uid, card in cards.items():
        value = cost(card)
        if type(value) is not int or (value < -1 and not any(a.get('card_uuid') == uid for a in first)):
            continue
        targets = [i for i, e in enumerate(summary['enemies'])
                   if e['current_hp'] > 0 and not e.get('is_gone') and not e.get('half_dead')] if card.get('has_target') else [None]
        later.extend(dict(kind='play', card_uuid=uid, target_index=i) for i in targets)
    later.extend(a for a in first if a['kind'] == 'potion' and a.get('subaction') == 'use')
    plans = []

    def add(steps, envelope, ending):
        bound = steps + ([dict(kind='end', expected_before=envelope, execution_contract='native_conditional')] if ending else [])
        sequence = [{k: s[k] for k in ('kind', 'card_id', 'card_uuid', 'card_name',
                     'target_index', 'potion_index', 'potion_id', 'subaction') if k in s} for s in bound]
        encoded = json.dumps(sequence, sort_keys=True, separators=(',', ':'))
        checkpoint = None if ending else 'observe_after_segment'
        if not ending:
            bound = [*bound[:-1], dict(bound[-1], checkpoint=checkpoint)]
        plans.append(dict(id='native_plan_' + sha256(encoded.encode()).hexdigest()[:16],
            kind='turn_plan', command='PLAN', steps=bound, sequence=sequence,
            checkpoint=checkpoint, execution_contract='native_conditional',
            description=' -> '.join('END' if s['kind']=='end' else
                ('PLAY '+s['card_name'] if s['kind']=='play' else s['subaction'].upper()+' '+s['potion_id'])+
                (f" @enemy {s['target_index']}" if s.get('target_index') is not None else '') for s in sequence)
                + ('' if ending else ' -> OBSERVE'), uncertainties=[], notes=[]))

    if end_allowed:
        add([], root, True)
    queue = deque([(root, [], first)])
    while queue:
        envelope, steps, choices = queue.popleft()
        for choice in choices:
            # Always represent EVERY native first action, even with a tiny
            # budget. Limits stop expansion; they never replace the pool.
            if steps and (stats['expanded'] >= config.max_nodes or
                          (time.perf_counter() - started) * 1000 >= config.max_ms):
                stats['truncated'].append('node_budget' if stats['expanded'] >= config.max_nodes else 'time_budget')
                continue
            kind = choice['kind']
            child = dict(envelope)
            if kind == 'play':
                uid = choice['card_uuid']
                held = dict(envelope['hand'])
                if uid not in held:
                    continue
                value = held[uid]
                if steps and value > envelope['energy']:
                    continue
                child['hand'] = [(u, c) for u, c in envelope['hand'] if u != uid]
                child['energy'] = 0 if value == -1 else max(0, envelope['energy'] - max(0, value))
            else:
                index = choice['potion_index']
                if envelope['potions'][index] != choice['potion_id']:
                    continue
                child['potions'] = list(envelope['potions'])
                child['potions'][index] = 'Potion Slot'
            step = {k: choice[k] for k in ('kind', 'card_uuid', 'target_index',
                    'potion_index', 'potion_id', 'subaction') if k in choice}
            step['expected_before'] = envelope
            step['execution_contract'] = 'native_conditional'
            if kind == 'play':
                step.update(card_id=cards[uid]['id'], card_name=cards[uid].get('name', cards[uid]['id']))
            segment = steps + [step]
            stats['expanded'] += 1
            add(segment, child, False)
            if end_allowed and choice.get('subaction') != 'discard':
                add(segment, child, True)
            if choice.get('subaction') == 'discard':
                continue
            remaining = [a for a in later if (a['kind'] == 'play' and a['card_uuid'] in dict(child['hand'])
                         and (cost(cards[a['card_uuid']]) <= child['energy'])) or
                         (a['kind'] == 'potion' and child['potions'][a['potion_index']] == a['potion_id'])]
            if remaining:
                if len(segment) >= config.max_depth:
                    stats['truncated'].append('depth_budget')
                else:
                    queue.append((child, segment, remaining))
    stats.update(candidates=len(plans), complete_enumeration=not stats['truncated'],
        enumeration_complete=not stats['truncated'], truncated=sorted(set(stats['truncated'])),
        first_actions=len(first), represented_first_actions=len({
            json.dumps(p['sequence'][0], sort_keys=True) for p in plans if p['sequence'][0]['kind'] != 'end'}),
        multi_action_candidates=sum(sum(s['kind'] != 'end' for s in p['sequence']) > 1 for p in plans),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2))
    return plans, stats
