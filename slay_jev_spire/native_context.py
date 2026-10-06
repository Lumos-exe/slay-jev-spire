"""Organize native facts without a card/relic-name knowledge registry."""
from collections import Counter
from copy import deepcopy


def observed_fields(entity):
    """Native scalar fields; legacy snapshot support does not gate new content."""
    native=entity.get('native_fields',{})
    return {**entity.get('monster_state',{}),**native.get('class_fields',{}),
            **native.get('instance_fields',{})}


def strategy_context(summary, actions):
    result={}
    deck=summary.get('deck',[])
    if deck:
        result['deck']={'size':len(deck),'type_counts':dict(Counter(c.get('type','unknown') for c in deck)),
            'cost_counts':dict(Counter(str(c.get('cost','unknown')) for c in deck)),
            'cards':[{'id':c.get('id'),'uuid':c.get('uuid'),'upgrades':c.get('upgrades'),
                'native_values':deepcopy(c.get('native_values'))} for c in deck],
            'scope':'Counts and values come from native fields. Card functions are described by the game, not inferred from a name registry.'}
    current=summary.get('current_map_node');nodes={(n['x'],n['y']):n for n in summary.get('map',[])}
    if isinstance(current,dict) and nodes:
        todo=[((current.get('x'),current.get('y')),0)];seen=set();nearest={}
        while todo:
            key,depth=todo.pop(0)
            if key in seen or key not in nodes:continue
            seen.add(key);node=nodes[key]
            if depth:nearest.setdefault(node.get('symbol'),depth)
            todo.extend(((c['x'],c['y']),depth+1) for c in node.get('children',[]))
        result['route_ahead']={'nearest_reachable_nodes':nearest,
            'scope':'Visible graph distances only; question-mark contents are unknown.'}
    if summary.get('act_boss'):result['known_boss']=summary['act_boss']
    if summary.get('screen_state',{}).get('for_upgrade'):
        result['native_upgrade_previews']={a['id']:deepcopy(a.get('card',{}).get('upgrade_preview')) for a in actions if a.get('card')}
    return result
