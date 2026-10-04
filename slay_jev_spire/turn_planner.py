"""Bounded whole-turn beam search with explicit information boundaries."""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import time
from . import rules

@dataclass(frozen=True)
class SearchConfig:
    beam_width: int = 32
    max_nodes: int = 8000
    max_depth: int = 24
    max_ms: int = 500

    def __post_init__(self):
        if any(type(x) is not int or x < 1 for x in (self.beam_width, self.max_nodes, self.max_depth, self.max_ms)):
            raise ValueError('Search budgets must be positive integers.')
        if self.beam_width > 128:
            raise ValueError('Beam width must not exceed 128.')

def projection(state, counters=False):
    def card(c):
        return {k: c.get(k) for k in ('uuid', 'id', 'cost', 'upgrades', 'base_damage', 'base_block', 'magic_number')}
    result = {k: deepcopy(state[k]) for k in ('turn', 'energy', 'hp', 'max_hp', 'block', 'relics')}
    result['powers'] = {k: v for k, v in state['powers'].items() if v != 0}
    result['combust_hp_loss'] = state['combust_hp_loss']
    for pile in ('hand', 'draw_pile', 'discard_pile', 'exhaust_pile'):
        result[pile] = sorted([card(c) for c in state[pile]], key=lambda c: str(c['uuid']))
    result['enemies'] = [{k: deepcopy(e[k]) for k in ('id', 'hp', 'block', 'intent', 'damage', 'hits')} |
                         {'powers': {k: v for k, v in e['powers'].items() if v != 0} if e['hp'] > 0 else {}}
                         for e in state['enemies']]
    if counters:
        result['turn_counters'] = {k: state[k] for k in ('plays', 'attacks', 'skills')}
    return result

def battle_projection(summary):
    return projection(rules.initial(summary), 'turn_counters' in summary)

def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

def _quality(node):
    state, steps, out = node
    estimate = out.get('known_hand_continuation',{}).get('outcome',out)
    loss = estimate['incoming_hp_loss']
    if loss is None: loss = out.get('standing_hp_loss_estimate')
    if loss is None: loss = state['hp']
    hp = estimate.get('player_hp_after_turn')
    if hp is None: hp = state['hp'] - loss
    setup = sum(max(0, v) for k, v in state['powers'].items() if k in {
        'Strength', 'Dexterity', 'Feel No Pain', 'Dark Embrace', 'Corruption', 'Barricade',
        'Demon Form', 'Metallicize', 'Rage', 'Juggernaut', 'Double Tap', 'Berserk'})
    useful_draws = sum(p['expected_affordable_draws'] for p in out.get('draw_prospects',[]))
    setup += (3 + min(3,state['energy'])) * useful_draws + 2 * out['generated_cards']
    kill = int(out['combat_won'])
    enemy_hp = estimate['enemy_hp']
    primary = (kill, hp > 0, -enemy_hp - 2.5 * loss + 2 * setup - state['hp_spent'])
    return [primary + (-len(steps),), (kill, hp, -out['enemy_hp'], setup),
            (kill, -enemy_hp, hp, setup), (kill, setup, hp, -enemy_hp)]


def _known_hand_continuation(state, deadline, max_nodes):
    """Bounded conditional continuation, without inventing the unseen cards."""
    if state['checkpoint'] != 'draw_cards' or state['uncertainties']:
        return None, 0
    if any(p['has_on_draw_risks'] for p in state['draw_prospects']):
        return None, 0
    root=deepcopy(state);root.update(checkpoint=None,draws=0,draw_prospects=[])
    queue=[(root,[])];best=None;seen=set();nodes=0
    while queue and nodes < min(64,max_nodes) and time.monotonic() < deadline:
        current,sequence=queue.pop();nodes+=1
        result=rules.outcome(current)
        if result['forecast_scope']!='deterministic': continue
        loss=result['incoming_hp_loss']
        score=(current['hp']-(loss or 0)>0, -result['enemy_hp']-2.5*(loss or 0))
        if best is None or score > best[0]: best=(score,sequence,result)
        for step in rules.legal_steps(current):
            child=rules.play(current,step)
            if child['checkpoint']: continue
            key=fingerprint(projection(child,True))
            if key in seen: continue
            seen.add(key)
            card=next(c for c in current['hand'] if c['uuid']==step['card_uuid'])
            queue.append((child,sequence+[{'card_id':card['id'],'target_index':step['target_index']}]))
    if best is None: return None, nodes
    result=best[2];result['forecast_scope']='conditional_known_hand';result['combat_won']=False
    return {'sequence':best[1], 'outcome':result,
            'assumption':'Continue using only cards already in hand, assuming the draw does not change HP, energy, costs, hand-dependent legality, effect scaling or triggers. Replan after observing it.'}, nodes

def _diverse(nodes, width):
    if len(nodes) <= width:
        return sorted(nodes, key=lambda n: _quality(n)[0], reverse=True)
    rankings = [sorted(range(len(nodes)), key=lambda i: _quality(nodes[i])[k], reverse=True) for k in range(4)]
    selected = []; seen = set()
    for rank in range(len(nodes)):
        for order in rankings:
            index = order[rank]
            if index not in seen:
                selected.append(nodes[index]); seen.add(index)
                if len(selected) == width: return selected
    return selected

def generate_plans(summary, actions, config=None):
    config = config or SearchConfig()
    started = time.monotonic()
    stats = dict(rule_version=rules.VERSION, beam_width=config.beam_width, expanded=0, continuation_nodes=0,
                 deduplicated=0, depth=0, truncated=[], complete_enumeration=False)
    if 'player' not in summary:
        return [], stats
    root = rules.initial(summary)
    use_counters = 'turn_counters' in summary
    root_legal = {(a.get('card_uuid'), a.get('target_index')) for a in actions if a.get('kind') == 'play'}
    beam = [(root, [], rules.outcome(root))]
    terminal = {}; visited = set()
    for depth in range(config.max_depth + 1):
        stats['depth'] = depth
        children = []
        for state, steps, out in beam:
            if steps or any(a['command'] == 'END' for a in actions):
                end_steps = steps if state['checkpoint'] or not rules.live(state) else steps + [dict(kind='end', expected_before=projection(state, use_counters))]
                key = fingerprint([projection(state, True), state['checkpoint'], state['uncertainties'], steps[-1].get('selection_uuid') if steps else None])
                if key not in terminal or len(end_steps) < len(terminal[key][1]):
                    terminal[key] = (state, end_steps, out)
            if depth == config.max_depth:
                if rules.legal_steps(state): stats['truncated'].append('depth_budget')
                continue
            for step in rules.legal_steps(state):
                if depth == 0 and (step['card_uuid'], step['target_index']) not in root_legal: continue
                if stats['expanded'] + stats['continuation_nodes'] >= config.max_nodes:
                    stats['truncated'].append('node_budget'); break
                if (time.monotonic() - started) * 1000 >= config.max_ms:
                    stats['truncated'].append('time_budget'); break
                child = rules.play(state, step)
                stats['expanded'] += 1
                bound = dict(step, expected_before=projection(state, use_counters))
                card = next(c for c in state['hand'] if c['uuid'] == step['card_uuid'])
                bound.update(card_id=card['id'], card_name=card.get('name', card['id']), checkpoint=child['checkpoint'])
                key = fingerprint([projection(child, True), child['known_top'], child['checkpoint'], step.get('selection_uuid')])
                if key in visited:
                    stats['deduplicated'] += 1; continue
                visited.add(key)
                forecast=rules.outcome(child)
                continuation, continued_nodes=_known_hand_continuation(child,started+config.max_ms/1000,
                    config.max_nodes-stats['expanded']-stats['continuation_nodes'])
                stats['continuation_nodes'] += continued_nodes
                if continuation: forecast['known_hand_continuation']=continuation
                children.append((child, steps + [bound], forecast))
            if 'node_budget' in stats['truncated'] or 'time_budget' in stats['truncated']: break
        for state, steps, out in children:
            ending = steps if state['checkpoint'] or not rules.live(state) else steps + [dict(kind='end', expected_before=projection(state, use_counters))]
            terminal.setdefault(fingerprint([projection(state, True), state['checkpoint'], steps[-1].get('selection_uuid')]), (state, ending, out))
        if stats['truncated'] or not children: break
        beam = _diverse(children, config.beam_width)
        if len(children) > config.beam_width: stats['beam_pruned'] = stats.get('beam_pruned', 0) + len(children) - config.beam_width
    nodes = list(terminal.values())
    lethal = [n for n in nodes if n[2]['combat_won']]
    if lethal:
        safest = max(n[0]['hp'] for n in lethal)
        nodes = [n for n in nodes if n[2]['combat_won'] or n[0]['hp'] > safest or n[2]['forecast_scope'] != 'deterministic']
    unique_nodes = {}
    for node in nodes:
        state, steps, out = node
        key = fingerprint([{k: v for k, v in s.items() if k != 'expected_before'} for s in steps])
        unique_nodes.setdefault(key, node)
    plans = []
    for state, steps, out in _diverse(list(unique_nodes.values()), config.beam_width):
        sequence = [{k: s[k] for k in ('kind', 'card_id', 'card_uuid', 'card_name', 'target_index', 'selection_uuid') if k in s} for s in steps]
        plan_id = 'plan_' + fingerprint(sequence)[:12]
        description = ' -> '.join('END' if s['kind'] == 'end' else s['card_name'] + (f' -> enemy {s["target_index"]}' if s.get('target_index') is not None else '') for s in sequence)
        plans.append(dict(id=plan_id, kind='turn_plan', command='PLAN', hand_index=None,
                          card_uuid=None, target_index=None, steps=steps, sequence=sequence,
                          description=description, outcome=out, checkpoint=state['checkpoint'],
                          uncertainties=state['uncertainties'], notes=state['notes']))
    stats['truncated'] = sorted(set(stats['truncated']))
    stats['elapsed_ms'] = round((time.monotonic() - started) * 1000, 2)
    stats['candidates'] = len(plans)
    stats['complete_enumeration'] = not stats['truncated'] and not stats.get('beam_pruned')
    return plans, stats

def turn_plans(summary, actions, config=None):
    return generate_plans(summary, actions, config)[0]

def bind_plan_step(step, summary, actions):
    observed = battle_projection(summary)
    expected = step['expected_before']
    bindings = {}
    real_ids = {c['uuid'] for pile in ('hand','draw_pile','discard_pile','exhaust_pile') for c in expected[pile] if not c['uuid'].startswith('@generated:')}
    for pile in ('hand','draw_pile','discard_pile','exhaust_pile'):
        for symbolic in expected[pile]:
            if not symbolic['uuid'].startswith('@generated:'): continue
            actual = next((c for c in observed[pile] if c['uuid'] not in real_ids and c['uuid'] not in bindings
                           and {k:v for k,v in c.items() if k!='uuid'} == {k:v for k,v in symbolic.items() if k!='uuid'}), None)
            if actual is None: return None
            bindings[actual['uuid']] = symbolic['uuid']
    for pile in ('hand','draw_pile','discard_pile','exhaust_pile'):
        for card in observed[pile]: card['uuid'] = bindings.get(card['uuid'], card['uuid'])
        observed[pile].sort(key=lambda c:c['uuid'])
    if observed != expected:
        return None
    action = next((a for a in actions if a.get('kind') == step['kind'] and
                 (step['kind'] == 'end' or (bindings.get(a.get('card_uuid'), a.get('card_uuid')) == step['card_uuid'] and a.get('target_index') == step.get('target_index')))), None)
    if action and step.get('selection_uuid'):
        inverse = {v:k for k,v in bindings.items()}
        return dict(action, planned_selection_uuid=inverse.get(step['selection_uuid'], step['selection_uuid']))
    return action

def proven_lethal_plan(summary, actions):
    for plan in turn_plans(summary, actions):
        if plan['outcome']['combat_won']:
            return [a for step in plan['steps'] if (a := bind_plan_step(step, summary, actions))]
    return None
