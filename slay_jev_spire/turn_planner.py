"""Enumerate known action sequences without strategic scoring or candidate cuts."""
from copy import deepcopy
from collections import Counter
from hashlib import sha256
import json
import time
from . import rules
from .semantics import observable_state
from .planning_config import SearchConfig

def projection(state, counters=False):
    return observable_state(state, counters)

def battle_projection(summary):
    return projection(rules.initial(summary), 'turn_counters' in summary)

def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                             default=sorted).encode()).hexdigest()


def search_key(state):
    # An observation projection is deliberately small and is NOT an equivalence
    # relation for search: retain flags, temporary costs, counters, enemy state,
    # card order, generated resources and uncertainties all affect the future.
    value=dict(state)
    # These piles have no known order. Headbutt/Exhume choose exact UUIDs;
    # known draw order lives separately in known_top. Keep the hand order,
    # because sequential exhaust/draw triggers can depend on it.
    for pile in ('discard_pile','exhaust_pile'):
        value[pile]=sorted(state[pile],key=lambda c:c['uuid'])
    return fingerprint(value)

def generate_plans(summary, actions, config=None):
    config = config or SearchConfig()
    started = time.monotonic()
    stats = dict(rule_version=rules.VERSION, beam_width=config.beam_width, expanded=0, continuation_nodes=0,
                 deduplicated=0, semantic_deduplicated=0, domination_pruned=0, planned_potion_uses=[],
                 domination_scope='No strategic pruning; only identical full search states are merged.',
                 depth=0, truncated=[], complete_enumeration=False)
    if 'player' not in summary:
        return [], stats
    root = rules.initial(summary)
    # Unsupported simulation must not remove sequence choices. Native
    # conditional sequences make no forecasts and require runtime validation.
    if root['uncertainties']:
        from .native_sequences import generate_plans as native_plans
        plans, stats = native_plans(summary, actions, config)
        stats['coverage_unknowns'] = list(root['uncertainties'])
        return plans, stats
    potion_options = rules.potion_steps(root, summary, actions)
    def available(state):
        if state['checkpoint'] or state['hp'] <= 0 or not rules.live(state): return []
        return rules.legal_steps(state) + [p for p in potion_options
            if state['potions'][p['potion_index']]['id'] == p['potion_id']
            and (p['target_index'] is None or p['target_index'] in rules.live(state))]
    use_counters = 'turn_counters' in summary
    root_legal = {(a.get('card_uuid'), a.get('target_index')) for a in actions if a.get('kind') == 'play'}
    beam = [(root, [], rules.outcome(root))]
    terminal = {}; visited = set()
    if any(a['command']=='END' for a in actions):
        terminal[search_key(root)]=(root,[dict(kind='end',expected_before=projection(root,use_counters))],beam[0][2])
    for depth in range(config.max_depth + 1):
        stats['depth'] = depth
        children = []
        for state, steps, out in beam:
            if depth == config.max_depth:
                if available(state): stats['truncated'].append('depth_budget')
                continue
            choices = available(state)
            expected=projection(state,use_counters) if choices else None
            for step in choices:
                is_potion = step['kind'] == 'potion'
                if not steps and not is_potion and (step['card_uuid'], step['target_index']) not in root_legal: continue
                if stats['expanded'] + stats['continuation_nodes'] >= config.max_nodes:
                    stats['truncated'].append('node_budget'); break
                if (time.monotonic() - started) * 1000 >= config.max_ms:
                    stats['truncated'].append('time_budget'); break
                child = rules.use_potion(state, step) if is_potion else rules.play(state, step)
                stats['expanded'] += 1
                bound = dict(step, expected_before=expected)
                if not is_potion:
                    card = next(c for c in state['hand'] if c['uuid'] == step['card_uuid'])
                    bound.update(card_id=card['id'], card_name=card.get('name', card['id']))
                bound['checkpoint'] = child['checkpoint']
                key = search_key(child)
                if key in visited:
                    stats['deduplicated'] += 1; continue
                visited.add(key)
                forecast=rules.outcome(child)
                sequence=steps+[bound]
                if available(child): children.append((child, sequence, forecast))
                ending=sequence if child['checkpoint'] or not rules.live(child) or child['hp'] <= 0 else sequence+[dict(kind='end',expected_before=projection(child,use_counters))]
                terminal[key]=(child,ending,forecast)
            if 'node_budget' in stats['truncated'] or 'time_budget' in stats['truncated']: break
        if stats['truncated'] or not children: break
        # Never discard unfinished branches because ending *now* would die.
        # The explicit time/node/depth budgets still bound the enumeration.
        beam = children
    stats['search_elapsed_ms'] = round((time.monotonic()-started)*1000,2)
    stats['enumeration_complete'] = not stats['truncated']
    stats['beam_pruned'] = 0
    stats['terminal_states'] = len(terminal)
    stats['observation_boundaries'] = dict(Counter(
        state['checkpoint'] for state, _, _ in terminal.values() if state['checkpoint']))
    stats['enumeration_scope'] = 'Supported transitions up to observation boundaries; not all complete turns.'
    selection_started=time.monotonic()
    nodes = list(terminal.values())
    # Retain every generated plan on exhaustion. No global single-action mode.
    stats['fallback_required'] = False
    stats['policy'] = 'exhaustive_known_actions'
    stats['beam_width_ignored'] = True
    stats['candidate_cap_pruned'] = 0
    stats['selection_elapsed_ms'] = 0
    stats['continuation_candidates'] = 0
    stats['continuation_elapsed_ms'] = 0
    stats['continuation_truncated'] = 0
    stats['continuation_unavailable'] = 0
    final_nodes = nodes
    plans = []
    for state, steps, out in final_nodes:
        out['position']=rules.outcome(state,include_position=True)['position']
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
    if stats['truncated']:
        from .native_sequences import generate_plans as native_plans
        # Include every legal starting action even if the simulation budget
        # ran out before reaching it. Existing multi-step plans stay eligible.
        proposals, _ = native_plans(summary, actions, SearchConfig(max_nodes=1))
        plans.extend(proposals)
    stats['truncated'] = sorted(set(stats['truncated']))
    stats['elapsed_ms'] = round((time.monotonic() - started) * 1000, 2)
    stats['candidates'] = len(plans)
    stats['complete_enumeration'] = stats['enumeration_complete']
    return plans, stats

def turn_plans(summary, actions, config=None):
    return generate_plans(summary, actions, config)[0]

def bind_plan_step(step, summary, actions):
    if step.get('execution_contract') == 'native_conditional':
        from .native_sequences import bind_plan_step as native_bind
        return native_bind(step, summary, actions)
    observed = battle_projection(summary)
    expected = step['expected_before']
    bindings = {}
    real_ids = {c['uuid'] for pile in ('hand','draw_pile','discard_pile','exhaust_pile') for c in expected[pile] if not c['uuid'].startswith('@generated:')}
    for pile in ('hand','draw_pile','discard_pile','exhaust_pile'):
        ordered = (sorted(expected[pile], key=lambda c: expected['hand_order'].index(c['uuid']))
                   if pile == 'hand' else expected[pile])
        for symbolic in ordered:
            if not symbolic['uuid'].startswith('@generated:'): continue
            actual = next((c for c in observed[pile] if c['uuid'] not in real_ids and c['uuid'] not in bindings
                           and {k:v for k,v in c.items() if k!='uuid'} == {k:v for k,v in symbolic.items() if k!='uuid'}), None)
            if actual is None: return None
            bindings[actual['uuid']] = symbolic['uuid']
    for pile in ('hand','draw_pile','discard_pile','exhaust_pile'):
        for card in observed[pile]: card['uuid'] = bindings.get(card['uuid'], card['uuid'])
        observed[pile].sort(key=lambda c:c['uuid'])
    observed['hand_order'] = [bindings.get(uid, uid) for uid in observed['hand_order']]
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
