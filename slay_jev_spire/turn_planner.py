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
    result['potions'] = deepcopy(state['potions'])
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
    # Copy count is not realized value: Anger in discard can dilute the deck.
    # Copies that are useful now earn their actual damage/block in later steps.
    setup += (3 + min(3,state['energy'])) * useful_draws
    pollution = out.get('unexhausted_status_cards', 0) + out.get('unexhausted_curse_cards', 0)
    # Status cards can be fuel in the right deck. They are never generically
    # rewarded as though Wounds were extra attacks; modeled exhaust pays back
    # through its actual draw/block effects and removes this cost.
    resource_cost = 2 * pollution + 2 * len(out.get('potions_used', []))
    waste = out.get('wasted_block') or 0
    kill = int(out['combat_won'])
    after_turn_hp = estimate.get('enemy_hp_after_turn_by_target')
    enemy_hp = sum(after_turn_hp) if after_turn_hp is not None else estimate['enemy_hp']
    primary = (kill, hp > 0, -enemy_hp - 2.5 * loss + 2 * setup - state['hp_spent'] - resource_cost - .05 * waste)
    return [primary + (-len(steps),), (kill, hp, -enemy_hp, setup),
            (kill, -enemy_hp, hp, setup-resource_cost), (kill, setup-resource_cost, hp, -enemy_hp)]


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
        score=_quality((current, sequence, result))[0]
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


def _equivalent_end_state(state, out):
    """Deduplicate interchangeable card instances, never compare dominance.

    Keep piles, costs, upgrades, counters, powers and every modeled outcome.
    Information-boundary plans retain their exact sequence identity instead.
    """
    value = projection(state, True)
    for pile in ('hand', 'draw_pile', 'discard_pile', 'exhaust_pile'):
        cards = [{k: v for k, v in c.items() if k not in
                  {'uuid', 'card_uuid', 'hand_index', 'play_index'}} for c in state[pile]]
        value[pile] = sorted(cards, key=lambda c: json.dumps(c, sort_keys=True, ensure_ascii=False))
    return fingerprint([value, out, state['known_top'], state['attacks_this_combat']])


def _resource_signature(node):
    """Only plain ENDs with interchangeable future discards are comparable."""
    state, steps, out = node
    if (out['forecast_scope'] != 'deterministic' or not steps or steps[-1]['kind'] != 'end'
            or state['checkpoint'] or state['uncertainties'] or state['known_top']
            or state['draws'] or state['generated'] or out['exhausted_card_counts']
            or out['player_hp_after_turn'] is None or out['player_hp_after_turn'] <= 0
            or out['retained_block'] is None): return None
    # End-turn triggers are not represented by a complete future state here.
    # Exclude them instead of claiming equivalence from the HP projection alone.
    safe_powers = {'Strength', 'Dexterity', 'Weak', 'Vulnerable', 'Frail',
                   'Artifact', 'Barricade', 'NoBlock', 'No Draw'}
    if (set(state['powers']) - safe_powers
            or set(state['relics']) - (rules.PASSIVE_RELICS | {'Calipers', 'Ice Cream'})
            or {'Runic Pyramid', 'Red Skull'} & set(state['relics'])): return None
    enemy_hp = out.get('enemy_hp_after_turn_by_target')
    if (enemy_hp is None or any(hp <= 0 for hp in enemy_hp)
            or enemy_hp != out['enemy_hp_by_target']
            or any(e['intent'] == 'SLEEP' or e['half_dead'] or e['gone'] for e in state['enemies'])): return None
    piles = ('hand', 'draw_pile', 'discard_pile', 'exhaust_pile')
    cards = [c for pile in piles for c in state[pile]]
    if (any(c.get(k) for c in cards for k in ('retain', 'self_retain', 'is_retained'))
            or any(c.get('ethereal') or c['type'] in {'STATUS', 'CURSE'} for c in state['hand'])
            or any(c['id'] not in rules.CARD_SPECS for c in cards)): return None
    def card(c):
        return {k: v for k, v in c.items() if k not in {'uuid', 'card_uuid', 'hand_index', 'play_index'}}
    # Keep every non-identity card field: costs, upgrades, native fields and
    # one-use flags remain significant. Draw/exhaust never merge with discard.
    value = {k: v for k, v in state.items() if k not in {*piles, 'hp', 'block', 'enemies', 'initial_exhaust_ids'}}
    value['initial_exhaust_ids'] = sorted(state['initial_exhaust_ids'])
    value['future_discard'] = sorted([card(c) for c in state['hand'] + state['discard_pile']],
                                    key=lambda c: json.dumps(c, sort_keys=True, ensure_ascii=False))
    for pile in ('draw_pile', 'exhaust_pile'): value[pile] = [card(c) for c in state[pile]]
    value['enemies'] = [{k: v for k, v in e.items() if k != 'hp'} for e in state['enemies']]
    value['retained_block'] = out['retained_block']
    return fingerprint(value)


def _prune_resource_dominated(nodes):
    """At most 32 final candidates; retain unknowns and all resource tradeoffs."""
    if len(nodes) > 32: return nodes, 0
    signatures = [_resource_signature(n) for n in nodes]
    kept = []
    for i, node in enumerate(nodes):
        out = node[2]
        dominated = False
        if signatures[i] is not None:
            for j, other in enumerate(nodes):
                if i == j or signatures[i] != signatures[j]: continue
                better = other[2]
                hp = out['player_hp_after_turn']; other_hp = better['player_hp_after_turn']
                enemies = out['enemy_hp_after_turn_by_target']; other_enemies = better['enemy_hp_after_turn_by_target']
                if other_hp >= hp and all(a <= b for a, b in zip(other_enemies, enemies)):
                    if other_hp > hp or any(a < b for a, b in zip(other_enemies, enemies)):
                        dominated = True; break
        if not dominated: kept.append(node)
    return kept, len(nodes) - len(kept)

def generate_plans(summary, actions, config=None):
    config = config or SearchConfig()
    started = time.monotonic()
    stats = dict(rule_version=rules.VERSION, beam_width=config.beam_width, expanded=0, continuation_nodes=0,
                 deduplicated=0, semantic_deduplicated=0, domination_pruned=0, planned_potion_uses=[],
                 domination_scope='At most 32 deterministic ENDs; identical future resources, no retain/draw/generation/exhaust/end-turn triggers; all enemies survive; per-target HP comparison.',
                 depth=0, truncated=[], complete_enumeration=False)
    if 'player' not in summary:
        return [], stats
    root = rules.initial(summary)
    potion_prefixes = rules.potion_steps(root, summary, actions)
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
            available = rules.legal_steps(state)
            if not steps and state['hp'] > 0 and rules.live(state) and not state['checkpoint']:
                available = potion_prefixes + available
            for step in available:
                is_potion = step['kind'] == 'potion'
                if not steps and not is_potion and (step['card_uuid'], step['target_index']) not in root_legal: continue
                if stats['expanded'] + stats['continuation_nodes'] >= config.max_nodes:
                    stats['truncated'].append('node_budget'); break
                if (time.monotonic() - started) * 1000 >= config.max_ms:
                    stats['truncated'].append('time_budget'); break
                child = rules.use_potion(state, step) if is_potion else rules.play(state, step)
                stats['expanded'] += 1
                bound = dict(step, expected_before=projection(state, use_counters))
                if not is_potion:
                    card = next(c for c in state['hand'] if c['uuid'] == step['card_uuid'])
                    bound.update(card_id=card['id'], card_name=card.get('name', card['id']))
                bound['checkpoint'] = child['checkpoint']
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
        def potion_cost(node):
            return tuple((p['potion_index'],p['potion_id']) for p in node[2].get('potions_used',[]))
        safest = {}
        for node in lethal:
            cost=potion_cost(node)
            safest[cost]=max(safest.get(cost,0),node[0]['hp'])
        # A consumable kill must not erase the option to save that potion.
        nodes = [n for n in nodes if potion_cost(n) not in safest or n[2]['combat_won']
                 or n[0]['hp'] > safest[potion_cost(n)] or n[2]['forecast_scope'] != 'deterministic']
    unique_nodes = {}
    for node in nodes:
        state, steps, out = node
        key = (_equivalent_end_state(state, out) if out['forecast_scope'] == 'deterministic'
               else fingerprint([{k: v for k, v in s.items() if k != 'expected_before'} for s in steps]))
        if key in unique_nodes:
            stats['semantic_deduplicated'] += 1
        else: unique_nodes[key] = node
    final_nodes, stats['domination_pruned'] = _prune_resource_dominated(
        _diverse(list(unique_nodes.values()), config.beam_width))
    plans = []
    for state, steps, out in final_nodes:
        sequence = [{k: s[k] for k in ('kind', 'card_id', 'card_uuid', 'card_name', 'target_index', 'selection_uuid',
                    'potion_index', 'potion_id', 'subaction', 'potency') if k in s} for s in steps]
        plan_id = 'plan_' + fingerprint(sequence)[:12]
        description = ' -> '.join('END' if s['kind'] == 'end' else
            (('Use ' + s['potion_id']) if s['kind'] == 'potion' else s['card_name']) +
            (f' -> enemy {s["target_index"]}' if s.get('target_index') is not None else '') for s in sequence)
        plans.append(dict(id=plan_id, kind='turn_plan', command='PLAN', hand_index=None,
                          card_uuid=None, target_index=None, steps=steps, sequence=sequence,
                          description=description, outcome=out, checkpoint=state['checkpoint'],
                          uncertainties=state['uncertainties'], notes=state['notes']))
    stats['planned_potion_uses'] = sorted({s['source_action_id'] for p in plans for s in p['steps'] if s['kind'] == 'potion'})
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
    if step['kind'] == 'potion':
        return next((a for a in actions if a.get('kind') == 'potion' and all(a.get(k) == step.get(k)
                    for k in ('potion_index', 'potion_id', 'subaction', 'target_index'))), None)
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
