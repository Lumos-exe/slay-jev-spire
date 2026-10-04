"""Pure adapters for native noncombat choices; evidence never simulates effects."""

from copy import deepcopy
import json
import math
from .models import Action
from .state import UnsupportedState
from .state import UnsupportedState, _require
from .state import prepare_native_combat, potion_candidates

SUPPORTED_SCREENS = {'EVENT','CHEST','SHOP_ROOM','SHOP_SCREEN','REST','BOSS_REWARD','GRID','HAND_SELECT'}


def _require(condition, message):
    if not condition:
        raise UnsupportedState(message)


def _action(screen, command, description, kind, **metadata):
    return {'id':f"{screen.lower()}_{command.lower().replace(' ', '_')}",'command':command,'description':description,'kind':f'screen_{kind}','screen_type':screen,'hand_index':None,'card_uuid':None,'target_index':None,**deepcopy(metadata)}


def _label(item):
    return item['name'].lower()


def _price(value):
    _require(type(value) in (int,float) and math.isfinite(value) and value >= 0,'Invalid native price.')
    return value


def prepare_screen(raw: dict) -> list[Action]:
    """Preserve native choice indices, including filtered unavailable potion slots."""
    try:
        game=raw['game_state']; screen=game['screen_type']; state=game.get('screen_state',{})
        commands=raw['available_commands']; choices=game.get('choice_list',[])
        _require(screen in SUPPORTED_SCREENS,'Screen is not supported.')
        _require(isinstance(commands,list) and all(isinstance(x,str) for x in commands),'Invalid commands.')
        _require(isinstance(choices,list) and all(isinstance(x,str) for x in choices),'Invalid choices.')
        entries=[]
        if screen=='EVENT':
            seen=set()
            for option in state['options']:
                _require(type(option['disabled']) is bool,'Invalid event availability.')
                if option['disabled']: continue
                i=option['choice_index']
                _require(type(i) is int and 0 <= i < len(choices) and i not in seen,'Invalid event choice index.')
                _require(choices[i]==option['label'].lower(),'Event labels do not align.')
                seen.add(i); entries.append((i,'event',option.get('text',option['label']),{'option':option}))
            _require(seen==set(range(len(choices))),'Event indices do not align.')
        elif screen=='SHOP_SCREEN':
            stock=[]; gold=_price(game['gold'])
            if state.get('purge_available') is True and _price(state['purge_cost'])<=gold:
                stock.append(('purge',{'name':'purge','price':state['purge_cost']}))
            for group,kind in [('cards','shop_card'),('relics','shop_relic'),('potions','shop_potion')]:
                for item in state.get(group,[]):
                    if _price(item['price'])<=gold: stock.append((kind,item))
            _require(choices==[_label(item) for _,item in stock],'Shop labels do not align.')
            for i,(kind,item) in enumerate(stock):
                if kind=='shop_potion' and not any(p.get('id')=='Potion Slot' for p in game.get('potions',[])): continue
                entries.append((i,'shop_purge' if kind=='purge' else kind,json.dumps(item,ensure_ascii=False),{'item':item}))
        elif screen in {'GRID','HAND_SELECT'}:
            hand=screen=='HAND_SELECT'; cards=state['hand' if hand else 'cards']; selected=state.get('selected' if hand else 'selected_cards',[])
            no_choices=(not hand and state.get('confirm_up') is True) or (hand and len(selected)>=state['max_cards'])
            _require(choices==([] if no_choices else [_label(c) for c in cards]),'Selection labels do not align.')
            selected_ids={c.get('uuid') for c in selected if c.get('uuid')}
            for i,c in enumerate(cards if not no_choices else []):
                if c.get('uuid') in selected_ids: continue
                _require(bool(c.get('uuid')),'Selected card needs UUID evidence.')
                entries.append((i,'hand_select' if hand else 'grid',json.dumps(c,ensure_ascii=False),{'card':c,'card_uuid':c['uuid'],'selection_state':state}))
        elif screen=='BOSS_REWARD':
            relics=state['relics']; _require(choices==[_label(r) for r in relics],'Boss relic labels do not align.')
            entries=[(i,'boss_relic',json.dumps(r,ensure_ascii=False),{'item':r}) for i,r in enumerate(relics)]
        else:
            expected={'CHEST':([] if state.get('chest_open') is True else ['open']),'SHOP_ROOM':['shop'],'REST':[x.lower() for x in state.get('rest_options',[])]}[screen]
            _require(choices==expected,'Room labels do not align.')
            entries=[(i,{'CHEST':'chest','SHOP_ROOM':'shop_room','REST':'rest'}[screen],label+' (native option; effect not inferred)',{'label':label}) for i,label in enumerate(choices)]
        actions=[_action(screen,f'CHOOSE {i}',description,kind,choice_index=i,**metadata) for i,kind,description,metadata in entries] if 'choose' in commands else []
        for button in ('confirm','cancel','proceed','leave','skip'):
            if button in commands:
                actions.append(_action(screen,button.upper(),button.title(),button,selection_state=state))
        return actions
    except (KeyError,TypeError,AttributeError,IndexError,ValueError):
        raise UnsupportedState('Malformed native screen state.') from None


def _cards(items):
    return {c['uuid']:c for c in items if c.get('uuid')}


def _selected(state):
    return state.get('selected_cards',state.get('selected',[]))


def _selection_evidence(before,after,cards,state):
    old=_cards(before.get('deck',[])); new=_cards(after.get('deck',[]))
    selected=_cards(_selected(after.get('screen_state',{})))
    combat=after.get('combat_state',{})
    previous_combat=before.get('combat_state',{})
    for card in cards:
        uid=card.get('uuid')
        if not uid: return None
        if uid in selected and uid not in _cards(_selected(before.get('screen_state',{}))): continue
        if state.get('for_upgrade') and uid in old and uid in new and new[uid].get('upgrades',0)>old[uid].get('upgrades',0): continue
        if (state.get('for_purge') or state.get('for_transform')) and uid in old and uid not in new:
            if state.get('for_transform') and not (set(new)-set(old)): return None
            continue
        moved=False
        for group in ('discard_pile','exhaust_pile','draw_pile'):
            if uid in _cards(combat.get(group,[])) and uid not in _cards(previous_combat.get(group,[])): moved=True
        if moved: continue
        # Combat-only upgrades (e.g. Armaments) do not update the master deck.
        # A selected card may also return unchanged from the selection group.
        # Both observations must concern this UUID and follow screen closure.
        closed=before.get('screen_type')!=after.get('screen_type')
        hand=_cards(combat.get('hand',[]))
        if closed and uid in hand:
            if hand[uid].get('upgrades',0)>card.get('upgrades',0): continue
            if 'hand' in previous_combat and uid not in _cards(previous_combat['hand']): continue
        return None
    return 'Observed selected card UUIDs or corresponding deck/card-group changes.' if cards else None


def _copied_selection(before, after, cards):
    # Dual Wield replaces even the original with fresh UUIDs. Require matching
    # new copies in the same turn; an unrelated draw or screen change is insufficient.
    if len(cards) != 1 or not cards[0].get('id') or not cards[0].get('uuid'): return None
    if before.get('screen_type') != 'HAND_SELECT' or after.get('screen_type') != 'NONE': return None
    if before.get('room_phase') != 'COMBAT' or after.get('room_phase') != 'COMBAT': return None
    if any(before.get(k) != after.get(k) for k in ('seed','act','floor')): return None
    old, new = before.get('combat_state',{}), after.get('combat_state',{})
    if old.get('turn') is None or old['turn'] != new.get('turn'): return None
    groups = ('hand','draw_pile','discard_pile','exhaust_pile','limbo')
    old_ids = {c.get('uuid') for group in groups for c in old.get(group,[])} | {cards[0]['uuid']}
    if any(c.get('uuid') == cards[0]['uuid'] for group in groups for c in new.get(group,[])): return None
    copies = {c['uuid'] for group in ('hand','discard_pile') for c in new.get(group,[])
              if c.get('uuid') and c['uuid'] not in old_ids and c.get('id') == cards[0]['id']
              and c.get('upgrades',0) == cards[0].get('upgrades',0)}
    if len(copies) >= 2: return 'Observed selected card replaced by new matching copy UUIDs in the same combat turn.'
    return None


def confirm_screen(before: dict, after: dict, action: Action) -> str | None:
    """Match observations to this action; unrelated raw changes remain unconfirmed."""
    try:
        b=before['game_state']; a=after['game_state']; bs=b.get('screen_state',{}); ast=a.get('screen_state',{})
        kind=action.get('kind',''); changed_screen=b['screen_type']!=a['screen_type']
        if kind in {'screen_grid','screen_hand_select'}:
            if (kind == 'screen_grid' and bs.get('confirm_up') is not True and ast.get('confirm_up') is True
                    and ast.get('pending_card_uuid') == action['card_uuid']):
                return 'Observed requested card UUID in native confirmation preview; effect awaits CONFIRM.'
            return (_selection_evidence(b,a,[action['card']],action['selection_state'])
                    or _copied_selection(b,a,[action['card']]))
        if kind=='screen_confirm' and b['screen_type'] in {'GRID','HAND_SELECT'}:
            cards=_selected(action['selection_state'])
            if not cards and action['selection_state'].get('pending_card_uuid'):
                cards=[c for c in action['selection_state'].get('cards',[]) if c.get('uuid') == action['selection_state']['pending_card_uuid']]
            evidence=_selection_evidence(b,a,cards,action['selection_state'])
            if evidence and (changed_screen or ast!=bs): return evidence
            copied=_copied_selection(b,a,cards)
            if copied: return copied
            if not cards and bs.get('confirm_up') and changed_screen: return 'Observed native confirmation screen closed.'
            if not cards and b['screen_type']=='HAND_SELECT' and bs.get('can_pick_zero') and changed_screen: return 'Observed zero-card selection confirmation closed.'
            return None
        if kind in {'screen_cancel','screen_leave','screen_skip','screen_proceed'}:
            return 'Observed screen/floor transition after native button.' if changed_screen or b.get('floor')!=a.get('floor') or b.get('act')!=a.get('act') else None
        if kind=='screen_shop_room': return 'Observed shop opened.' if a['screen_type']=='SHOP_SCREEN' else None
        if kind=='screen_shop_purge': return 'Observed native purge selection opened.' if a['screen_type']=='GRID' and ast.get('for_purge') is True else None
        if kind in {'screen_shop_card','screen_shop_relic','screen_shop_potion','screen_boss_relic'}:
            item=action['item']; group={'screen_shop_card':'deck','screen_shop_relic':'relics','screen_shop_potion':'potions','screen_boss_relic':'relics'}[kind]
            key='uuid' if group=='deck' else 'id'; identity=item.get(key)
            old=sum(x.get(key)==identity for x in b.get(group,[])); new=sum(x.get(key)==identity for x in a.get(group,[]))
            if identity and new>old: return 'Observed chosen item added to native inventory.'
            # Native acquisition can copy a store card, producing a new UUID.
            # Require its card ID count, removed stock UUID and paid cost together.
            if kind=='screen_shop_card' and item.get('id'):
                card_id=item['id']
                old_count=sum(c.get('id')==card_id for c in b.get('deck',[]))
                new_count=sum(c.get('id')==card_id for c in a.get('deck',[]))
                stock_removed=identity not in _cards(ast.get('cards',[]))
                paid=b.get('gold',0)-a.get('gold',0)==item.get('price')
                if new_count>old_count and stock_removed and paid:
                    return 'Observed matching purchased card, removed stock and native gold cost.'
            return None
        if kind=='screen_chest':
            return 'Observed chest open/reward screen.' if ast.get('chest_open') is True or a['screen_type']=='COMBAT_REWARD' else None
        if kind=='screen_rest':
            if action.get('label')=='smith' and a['screen_type']=='GRID' and ast.get('for_upgrade'): return 'Observed upgrade selection opened.'
            if bs.get('has_rested') is not True and ast.get('has_rested') is True: return 'Observed native rest option completion.'
            if action.get('label') in {'toke'} and a['screen_type']=='GRID' and ast.get('for_purge'): return 'Observed purge selection opened.'
            if action.get('label')=='recall' and a.get('keys')!=b.get('keys') and a.get('keys') is not None: return 'Observed key state change.'
            return None
        if kind=='screen_event':
            event_keys=('event_id','body_text','options')
            if changed_screen or any(bs.get(k)!=ast.get(k) for k in event_keys) or any(b.get(k)!=a.get(k) for k in ('floor','current_hp','deck')):
                return 'Observed event advancement, screen, HP, floor or deck change; effect not inferred.'
        return None
    except (KeyError,TypeError,AttributeError,IndexError):
        return None



def _journey_action(command: str, description: str, **metadata) -> dict:
    """Create a candidate carrying its original native index and evidence metadata."""
    return {'id': command.lower().replace(' ', '_'), 'command': command, 'description': description, 'hand_index': None, 'card_uuid': None, 'target_index': None, **metadata}

def prepare_journey(raw: dict) -> tuple[dict, list[dict]]:
    """Validate native indices and expose supported screens without guessing effects."""
    try:
        _require(raw['in_game'] is True and raw['ready_for_command'] is True, 'State is not ready.')
        game = raw['game_state']
        screen = game['screen_type']
        context = deepcopy({k: game.get(k) for k in ('seed', 'class', 'act', 'floor', 'current_hp', 'max_hp', 'gold', 'deck', 'relics', 'potions', 'map', 'act_boss', 'ascension_level')})
        context.update(screen_type=screen, screen_state=deepcopy(game.get('screen_state', {})))
        if game.get('room_phase') == 'COMBAT' and screen != 'NONE':
            context['combat_context'] = deepcopy(game.get('combat_state', {}))
        if game.get('room_phase') == 'COMBAT' and screen == 'NONE':
            summary, actions = prepare_native_combat(raw)
            summary.update(context)
            return (summary, actions)
        commands = raw['available_commands']
        choices = game.get('choice_list', [])
        state = game.get('screen_state', {})
        _require(isinstance(commands, list) and all((isinstance(c, str) for c in commands)), 'Invalid commands.')
        _require(isinstance(choices, list) and all((isinstance(c, str) for c in choices)), 'Invalid choices.')
        actions = []
        if screen == 'GAME_OVER':
            return (context, actions)
        if screen in SUPPORTED_SCREENS:
            actions = prepare_screen(raw)
        elif screen == 'COMBAT_REWARD':
            rewards = state['rewards']
            _require(len(rewards) == len(choices), 'Reward indices do not align.')
            if 'choose' in commands:
                for i, reward in enumerate(rewards):
                    kind = reward['reward_type']
                    _require(choices[i] == kind.lower(), 'Reward labels do not align.')
                    _require(kind in {'GOLD', 'CARD', 'POTION', 'RELIC', 'STOLEN_GOLD', 'SAPPHIRE_KEY', 'EMERALD_KEY'}, 'Unsupported reward type.')
                    if kind == 'POTION' and (not any((p.get('id') == 'Potion Slot' for p in game.get('potions', [])))):
                        continue
                    actions.append(_journey_action(f'CHOOSE {i}', json.dumps(reward, ensure_ascii=False), kind='reward', choice_index=i, reward=deepcopy(reward)))
        elif screen == 'CARD_REWARD':
            cards = state['cards']
            bowl = state.get('bowl_available') is True
            _require(len(choices) == len(cards) + int(bowl), 'Card indices do not align.')
            if bowl:
                _require(choices[-1] == 'bowl', 'Bowl index does not align.')
            if 'choose' in commands:
                for i, card in enumerate(cards):
                    _require(choices[i] == card['name'].lower(), 'Card labels do not align.')
                    actions.append(_journey_action(f'CHOOSE {i}', json.dumps(card, ensure_ascii=False), kind='card', card=deepcopy(card), choice_index=i))
                if bowl:
                    actions.append(_journey_action(f'CHOOSE {len(cards)}', 'Singing Bowl: increase maximum HP by 2', kind='bowl'))
            if 'skip' in commands and state.get('skip_available') is True:
                actions.append(_journey_action('SKIP', 'Skip card reward', kind='skip'))
        elif screen == 'MAP':
            if choices == ['boss']:
                _require(state.get('boss_available') is True, 'Boss availability does not align.')
                if 'choose' in commands:
                    actions.append(_journey_action('CHOOSE 0', 'Enter boss room', kind='boss'))
            else:
                _require(state.get('boss_available') is not True, 'Boss availability does not align.')
                nodes = state['next_nodes']
                _require(len(nodes) == len(choices), 'Map indices do not align.')
                for i, node in enumerate(nodes):
                    _require(choices[i] == f"x={node['x']}", 'Map labels do not align.')
                    if 'choose' in commands:
                        actions.append(_journey_action(f'CHOOSE {i}', json.dumps(node, ensure_ascii=False), kind='map', node=deepcopy(node)))
        elif screen != 'COMPLETE':
            raise UnsupportedState('Screen is not supported.')
        if screen in {'COMBAT_REWARD', 'COMPLETE'} and 'proceed' in commands:
            actions.append(_journey_action('PROCEED', 'Proceed to map', kind='proceed'))
        if 'potion' in commands and screen not in {'GRID', 'HAND_SELECT'}:
            actions.extend(potion_candidates(raw))
        _require(bool(actions), 'No supported native actions.')
        return (context, actions)
    except (KeyError, TypeError, AttributeError, IndexError):
        raise UnsupportedState('Malformed journey state.') from None
