"""Ironclad turn transitions. Random information ends a deterministic prefix.

Values come from game fields; the catalogue supplies identities and semantics,
not legality. Unknown triggers are reported, never certified as a lethal line.
"""
from copy import deepcopy
from collections import Counter
from math import floor
from .native_context import observed_fields

VERSION = 'ironclad-8'
# Verified phase-specific callbacks do not react to each played card. Pending
# effects outside the current segment are reported separately in position facts.
RELIC_TRIGGER_PHASES = {'Incense Burner': 'turn_start', 'Sling': 'battle_start',
                        'Pantograph': 'battle_start', 'Meat on the Bone': 'battle_end'}
# Verified native power callbacks, scoped to the player. Confusion changes a
# newly drawn card, not the already observed hand; Hex resolves after card.use.
PLAYER_POWER_PHASES = {'Confusion': 'on_card_draw', 'Hex': 'after_non_attack_use'}
# id: type, normal cost, base damage, base block, magic. Live fields override values.
CARD_SPECS = {
    'Strike_R': ('ATTACK', 1, 6, 0, 0), 'Defend_R': ('SKILL', 1, 0, 5, 0),
    'Bash': ('ATTACK', 2, 8, 0, 2), 'Anger': ('ATTACK', 0, 6, 0, 0),
    'Armaments': ('SKILL', 1, 0, 5, 0), 'Body Slam': ('ATTACK', 1, 0, 0, 0),
    'Clash': ('ATTACK', 0, 14, 0, 0), 'Cleave': ('ATTACK', 1, 8, 0, 0),
    'Clothesline': ('ATTACK', 2, 12, 0, 2), 'Flex': ('SKILL', 0, 0, 0, 2),
    'Havoc': ('SKILL', 1, 0, 0, 0), 'Headbutt': ('ATTACK', 1, 9, 0, 0),
    'Heavy Blade': ('ATTACK', 2, 14, 0, 3), 'Iron Wave': ('ATTACK', 1, 5, 5, 0),
    'Perfected Strike': ('ATTACK', 2, 6, 0, 2), 'Pommel Strike': ('ATTACK', 1, 9, 0, 1),
    'Shrug It Off': ('SKILL', 1, 0, 8, 1), 'Sword Boomerang': ('ATTACK', 1, 3, 0, 3),
    'Thunderclap': ('ATTACK', 1, 4, 0, 1), 'True Grit': ('SKILL', 1, 0, 7, 0),
    'Twin Strike': ('ATTACK', 1, 5, 0, 2), 'Warcry': ('SKILL', 0, 0, 0, 1),
    'Wild Strike': ('ATTACK', 1, 12, 0, 0),
    'Battle Trance': ('SKILL', 0, 0, 0, 3), 'Blood for Blood': ('ATTACK', 4, 18, 0, 0),
    'Bloodletting': ('SKILL', 0, 0, 0, 2), 'Burning Pact': ('SKILL', 1, 0, 0, 2),
    'Carnage': ('ATTACK', 2, 20, 0, 0), 'Combust': ('POWER', 1, 0, 0, 5),
    'Dark Embrace': ('POWER', 2, 0, 0, 1), 'Disarm': ('SKILL', 1, 0, 0, 2),
    'Dropkick': ('ATTACK', 1, 5, 0, 0), 'Dual Wield': ('SKILL', 1, 0, 0, 1),
    'Entrench': ('SKILL', 2, 0, 0, 0), 'Evolve': ('POWER', 1, 0, 0, 1),
    'Feel No Pain': ('POWER', 1, 0, 0, 3), 'Fire Breathing': ('POWER', 1, 0, 0, 6),
    'Flame Barrier': ('SKILL', 2, 0, 12, 4), 'Ghostly Armor': ('SKILL', 1, 0, 10, 0),
    'Hemokinesis': ('ATTACK', 1, 15, 0, 2), 'Infernal Blade': ('SKILL', 1, 0, 0, 0),
    'Inflame': ('POWER', 1, 0, 0, 2), 'Intimidate': ('SKILL', 0, 0, 0, 1),
    'Metallicize': ('POWER', 1, 0, 0, 3), 'Power Through': ('SKILL', 1, 0, 15, 0),
    'Pummel': ('ATTACK', 1, 2, 0, 4), 'Rage': ('SKILL', 0, 0, 0, 3),
    'Rampage': ('ATTACK', 1, 8, 0, 5), 'Reckless Charge': ('ATTACK', 0, 7, 0, 0),
    'Rupture': ('POWER', 1, 0, 0, 1), 'Searing Blow': ('ATTACK', 2, 12, 0, 0),
    'Second Wind': ('SKILL', 1, 0, 5, 0), 'Seeing Red': ('SKILL', 1, 0, 0, 2),
    'Sentinel': ('SKILL', 1, 0, 5, 2), 'Sever Soul': ('ATTACK', 2, 16, 0, 0),
    'Shockwave': ('SKILL', 2, 0, 0, 3), 'Spot Weakness': ('SKILL', 1, 0, 0, 3),
    'Uppercut': ('ATTACK', 2, 13, 0, 1), 'Whirlwind': ('ATTACK', -1, 5, 0, 0),
    'Barricade': ('POWER', 3, 0, 0, 1), 'Berserk': ('POWER', 0, 0, 0, 2),
    'Bludgeon': ('ATTACK', 3, 32, 0, 0), 'Brutality': ('POWER', 0, 0, 0, 1),
    'Corruption': ('POWER', 3, 0, 0, 1), 'Demon Form': ('POWER', 3, 0, 0, 2),
    'Double Tap': ('SKILL', 1, 0, 0, 1), 'Exhume': ('SKILL', 1, 0, 0, 0),
    'Feed': ('ATTACK', 1, 10, 0, 3), 'Fiend Fire': ('ATTACK', 2, 7, 0, 0),
    'Immolate': ('ATTACK', 2, 21, 0, 0), 'Impervious': ('SKILL', 2, 0, 30, 0),
    'Juggernaut': ('POWER', 2, 0, 0, 5), 'Limit Break': ('SKILL', 1, 0, 0, 0),
    'Offering': ('SKILL', 0, 0, 0, 3), 'Reaper': ('ATTACK', 2, 4, 0, 0),
    # Colorless card acquired in normal Ironclad runs (e.g. Neow).
    'Deep Breath': ('SKILL', 0, 0, 0, 1),
    'Good Instincts': ('SKILL', 0, 0, 6, 0),
    'Discovery': ('SKILL', 1, 0, 0, 0),
}
EXHAUST = {'Disarm', 'Infernal Blade', 'Intimidate', 'Pummel', 'Seeing Red', 'Shockwave',
           'Exhume', 'Feed', 'Fiend Fire', 'Impervious', 'Offering', 'Reaper', 'Warcry'}
AOE = {'Cleave', 'Thunderclap', 'Whirlwind', 'Immolate', 'Reaper'}
SELECT = {'Armaments', 'Headbutt', 'True Grit', 'Burning Pact', 'Dual Wield', 'Exhume'}
POWER_IDS = {'Demon Form': 'Demon Form', 'Feel No Pain': 'Feel No Pain',
             'Dark Embrace': 'Dark Embrace', 'Fire Breathing': 'Fire Breathing'}
# These relics have no additional intra-turn trigger (their native modifiers are
# already in powers/energy). Everything else is explicitly marked as uncertain.
PASSIVE_RELICS = set(('Burning Blood|Black Blood|Vajra|Oddly Smooth Stone|Anchor|Bag of Marbles|'
    'Bag of Preparation|Lantern|Happy Flower|Ancient Tea Set|Bottled Flame|Bottled Lightning|'
    'Bottled Tornado|Regal Pillow|Dream Catcher|War Paint|Whetstone|Pear|Mango|Strawberry|'
    'Old Coin|Tiny Chest|Darkstone Periapt|Singing Bowl|Question Card|Prayer Wheel|Matryoshka|'
    'Shovel|Peace Pipe|Girya|Omamori|Juzu Bracelet|White Beast Statue|Potion Belt|Eternal Feather|'
    'Membership Card|Smiling Mask|The Courier|MealTicket|Molten Egg 2|Toxic Egg 2|Frozen Egg 2|'
    'SlaversCollar|Cursed Key|Coffee Dripper|Fusion Hammer|Sozu|Ectoplasm|Busted Crown|'
    'Runic Dome|Philosopher\'s Stone|Black Star|Calling Bell|Tiny House|Empty Cage|Pandora\'s Box|'
    'Astrolabe|Snecko Eye|Mark of Pain|Runic Pyramid|PreservedInsect|Red Skull|Necronomicon').split('|'))
TRIGGER_RELICS = {'Pen Nib', 'Nunchaku', 'Shuriken', 'Kunai', 'Ornamental Fan', 'Letter Opener',
    'Sundial', 'Chemical X', 'Akabeko', 'Boot', 'Paper Frog', 'Paper Crane', 'Champion Belt',
    'Charon\'s Ashes', 'Dead Branch', 'Medical Kit', 'Blue Candle', 'Orichalcum', 'Calipers',
    'Torii', 'TungstenRod', 'Bronze Scales', 'Ice Cream', 'Velvet Choker', 'Art of War',
    'Bird Faced Urn', 'Mummified Hand', 'Strange Spoon', 'Unceasing Top', 'Runic Cube',
    'Centennial Puzzle', 'Self Forming Clay', 'Red Skull', 'FossilizedHelix', 'Lizard Tail',
    'Magic Flower', 'NeowsBlessing'}
KNOWN_POWERS = set(('Strength|Dexterity|Weak|Vulnerable|Frail|Artifact|Rage|Plated Armor|Metallicize|'
    'Feel No Pain|Dark Embrace|Corruption|Barricade|Berserk|Brutality|Demon Form|Evolve|'
    'Fire Breathing|Flame Barrier|Combust|Rupture|Juggernaut|Double Tap|No Draw|'
    'Ritual|Thievery|Curl Up|Thorns|Sharp Hide|Angry|Anger|Mode Shift|Spore Cloud|'
    'Intangible|IntangiblePlayer|Invincible|Buffer|Entangled|NoBlock|'
    'Minion|Shackled|Draw Reduction|BeatOfDeath|Time Warp|Flight|Split|'
    'DuplicationPower|Pen Nib|FreeAttackPower|Double Damage|Vigor|LoseStrength').split('|'))


def powers(values):
    aliases = {'Weakened': 'Weak', 'NoDraw': 'No Draw', 'DarkEmbrace': 'Dark Embrace',
               'Flex':'LoseStrength','NoBlockPower':'NoBlock',
               'FeelNoPain': 'Feel No Pain', 'DemonForm': 'Demon Form', 'DoubleTap': 'Double Tap',
               'FlameBarrier': 'Flame Barrier', 'FireBreathing': 'Fire Breathing'}
    return {aliases.get(p['id'], p['id']): p['amount'] for p in values if p['amount'] != 0 or p['id'] in {'Invincible', 'Time Warp'}}


def card_state(card):
    result = deepcopy(card)
    result['uuid'] = card.get('uuid', card.get('card_uuid'))
    result['upgrades'] = card.get('upgrades', 0)
    spec = CARD_SPECS.get(card['id'], (card.get('type', 'STATUS'), card.get('cost', -2), 0, 0, 0))
    native = card.get('native_values', {})
    result['type'] = card.get('type', spec[0])
    result['cost'] = native.get('cost_for_turn', card.get('cost', spec[1]))
    for field, index in [('base_damage', 2), ('base_block', 3), ('magic_number', 4)]:
        value = native.get(field, native.get(field.removeprefix('base_'), spec[index]))
        result[field] = max(0, value) if type(value) is int else spec[index]
    # Body Slam rewrites baseDamage from current block in applyPowers.
    # Its damage is derived from state['block'], not a persistent card stat.
    if card['id'] == 'Body Slam': result['base_damage'] = 0
    return result


def clone_state(state):
    """Copy mutable simulation fields, share read-only native card metadata.

    Card mutations in this module replace top-level fields (cost, upgrades,
    UUID, flags) and never mutate native_values/upgrade_preview/descriptions.
    Re-copying those immutable snapshots at every edge dominated the budget.
    All other nested state, including powers, counters and effect records,
    remains independently owned by the new branch.
    """
    piles={'hand','draw_pile','discard_pile','exhaust_pile'}
    return {k:[dict(c) for c in v] if k in piles else deepcopy(v) for k,v in state.items()}


def initial(summary):
    player = summary['player']
    state = dict(identity=deepcopy(summary.get('identity')), turn=summary['turn'], hp=player['current_hp'], max_hp=player['max_hp'],
                 block=player['block'], energy=player['energy'], powers=powers(player['powers']),
                 hand=[card_state(c) for c in summary['hand']],
                 relics={{'Paper Phrog':'Paper Frog','The Boot':'Boot'}.get(r['id'],r['id']): r.get('counter', -1)
                         for r in summary.get('relics', [])},
                 enemies=[dict(id=e.get('id'), entity_id=e.get('entity_id'), hp=e['current_hp'], max_hp=e['max_hp'], block=e['block'],
                   powers=powers(e.get('powers', [])), intent=e['intent'],
                   damage=e.get('move_adjusted_damage'), base_damage=e.get('move_base_damage'), hits=e.get('move_hits'),
                   gone=e.get('is_gone', False), half_dead=e.get('half_dead', False),
                   move_id=e.get('move_id'),monster_state=deepcopy(observed_fields(e)),
                   damage_catalog=deepcopy(e.get('damage_catalog',{}))) for e in summary['enemies']],
                 energy_per_turn=summary.get('energy_per_turn'), draw_per_turn=summary.get('draw_per_turn'),
                 gold=summary.get('gold'),interruptions=[],
                 checkpoint=None, uncertainties=[], notes=[], draws=0, generated=0, draw_prospects=[],
                 generated_card_counts={}, generated_card_types={}, created_card_ids=[],
                 blocked_total=0, potions_used=[],
                 potions=[dict(potion_index=i, id=p['id'], potency=0 if p['id']=='Potion Slot' else p.get('potency'))
                          for i, p in enumerate(summary.get('potions', []))],
                 plays=summary.get('turn_counters', {}).get('cards_played', 0),
                 attacks=summary.get('turn_counters', {}).get('attacks_played', 0),
                 skills=summary.get('turn_counters', {}).get('skills_played', 0),
                 hp_spent=0, healing=0, known_top=[],
                 attacks_this_combat=summary.get('turn_counters', {}).get('attacks_this_combat', 0))
    for pile in ('draw_pile', 'discard_pile', 'exhaust_pile'):
        state[pile] = [card_state(c) for c in summary.get(pile, [])]
    state['initial_exhaust_ids'] = {c['uuid'] for c in state['exhaust_pile']}
    for card in summary['hand']:
        if card.get('native_values', {}).get('source') != 'game_card_fields':
            state['uncertainties'].append('missing_native_values:' + card['id'])
    combust = next((p for p in player['powers'] if p['id'] == 'Combust'), None)
    state['combust_hp_loss'] = combust.get('native_fields',{}).get('instance_fields',{}).get('hpLoss',combust.get('hp_loss')) if combust else 0
    if combust and type(state['combust_hp_loss']) is not int:
        state['uncertainties'].append('missing_combust_hp_loss')
    state['outside_turn_relics'] = [dict(id=r['id'], phase=RELIC_TRIGGER_PHASES[r['id']],
        counter=r.get('counter'), description=r.get('native_description',r.get('description')))
        for r in summary.get('relics',[]) if r['id'] in RELIC_TRIGGER_PHASES]
    unknown = set(state['relics']) - PASSIVE_RELICS - TRIGGER_RELICS - RELIC_TRIGGER_PHASES.keys()
    state['uncertainties'] += ['unmodeled_relic:' + r for r in sorted(unknown)]
    for owner in [state] + state['enemies']:
        supported=(KNOWN_POWERS-{'Sharp Hide'}) | PLAYER_POWER_PHASES.keys() if owner is state else KNOWN_POWERS
        state['uncertainties'] += ['unmodeled_power:' + p for p in sorted(set(owner['powers']) - supported)]
    for enemy in state['enemies']:
        if enemy['id']=='GremlinWizard' and enemy['move_id']==1 and enemy['damage'] is None:
            entries=enemy['damage_catalog'].get('entries',[])
            enemy['damage']=entries[0].get('adjusted') if entries else enemy['monster_state'].get('blast_adjusted_damage')
            enemy['base_damage']=entries[0].get('base') if entries else enemy['monster_state'].get('blast_base_damage')
        # With no initial modifiers, the native adjusted value is also the base.
        if enemy['base_damage'] is None and not any(enemy['powers'].get(p) for p in ('Strength', 'Weak')) and not state['powers'].get('Vulnerable'):
            enemy['base_damage'] = enemy['damage']
    return state


def refresh_intents(state, before):
    for enemy, old in zip(state['enemies'], before['enemies']):
        if enemy['id']=='GremlinWizard' and enemy['move_id']==2:
            continue  # Native CHARGE may carry an ATTACK icon after its blast.
        changed = any(enemy['powers'].get(p, 0) != old['powers'].get(p, 0) for p in ('Strength', 'Weak'))
        changed |= state['powers'].get('Vulnerable', 0) != before['powers'].get('Vulnerable', 0)
        if not changed or not enemy['intent'].startswith('ATTACK') or enemy['hp'] <= 0:
            continue
        base = enemy['base_damage']
        if type(base) is not int or base < 0:
            checkpoint(state, 'enemy_intent_recalculation')
            state['uncertainties'].append('missing_base_intent')
            enemy['damage'] = None
            continue
        amount = max(0, base + enemy['powers'].get('Strength', 0))
        if enemy['powers'].get('Weak', 0) > 0:
            amount *= 0.6 if 'Paper Crane' in state['relics'] else 0.75
        if state['powers'].get('Vulnerable', 0) > 0:
            amount *= 1.25 if 'Odd Mushroom' in state['relics'] else 1.5
        if state['powers'].get('IntangiblePlayer', 0) > 0:
            amount = min(amount, 1)
        enemy['damage'] = floor(amount)


def live(state):
    return [i for i, e in enumerate(state['enemies']) if e['hp'] > 0 and not e['gone'] and not e['half_dead']]


POTION_EFFECTS = {'Block Potion': 'block', 'Weak Potion': 'weak',
                 'Strength Potion': 'strength', 'Dexterity Potion': 'dexterity',
                 'Energy Potion': 'energy', 'Fire Potion': 'fire',
                 'Explosive Potion': 'explosive', 'BlessingOfTheForge': 'upgrade_hand'}


def potion_steps(state, summary, actions):
    """Only native legal uses with an observed potency can prefix a plan."""
    result = []
    for action in actions:
        if action.get('kind') != 'potion' or action.get('subaction') != 'use': continue
        index = action.get('potion_index')
        if type(index) is not int or not 0 <= index < len(state['potions']): continue
        potion = summary['potions'][index]
        ident, potency = potion['id'], potion.get('potency')
        if ident not in POTION_EFFECTS or action.get('potion_id') != ident: continue
        if not potion.get('can_use') or type(potency) is not int or potency < 0: continue
        target = action.get('target_index')
        targeted = ident in {'Weak Potion', 'Fire Potion'}
        if targeted != bool(potion.get('requires_target')): continue
        if (targeted and target not in live(state)) or (not targeted and target is not None): continue
        result.append(dict(kind='potion', potion_index=index, potion_id=ident,
                           subaction='use', target_index=target, potency=potency,
                           source_action_id=action['id']))
    return result


def use_potion(before, step):
    state = clone_state(before)
    index, ident, amount = step['potion_index'], step['potion_id'], step['potency']
    if state['potions'][index]['id'] != ident:
        raise ValueError('Each observed potion slot can be consumed only once.')
    state['potions'][index] = dict(potion_index=index, id='Potion Slot', potency=0)
    state['potions_used'].append({k: step[k] for k in ('potion_index', 'potion_id', 'target_index', 'potency')})
    effect = POTION_EFFECTS[ident]
    if effect == 'block': gain_block(state, amount, False)
    elif effect == 'energy': state['energy'] += amount
    elif effect in {'strength', 'dexterity'}: apply_power(state, None, effect.title(), amount)
    elif effect == 'weak': apply_power(state, step['target_index'], 'Weak', amount, True)
    elif effect == 'fire': damage_enemy(state, step['target_index'], amount, False)
    elif effect == 'explosive':
        for target in live(state): damage_enemy(state, target, amount, False)
    elif effect == 'upgrade_hand':
        # Native BlessingOfTheForge.use queues ArmamentsAction(true), with
        # potency 0. It upgrades eligible cards; it is not a played Skill.
        for card in state['hand']: upgrade_from_preview(state, card)
    refresh_intents(state, before)
    # Unknown relics may react to potion use (e.g. Toy Ornithopter). Observe
    # their real result before following cards; never certify an assumed result.
    if any(u.startswith('unmodeled_relic:') for u in state['uncertainties']):
        checkpoint(state, 'unmodeled_potion_trigger')
    return state


def record_generation(state, ident, kind, count=1, uuid=None):
    state['generated'] += count
    for key, value in [('generated_card_counts', ident), ('generated_card_types', kind)]:
        state[key][value] = state[key].get(value, 0) + count
    if uuid is not None: state['created_card_ids'].append(uuid)


def add_status_cards(state, ident, count, pile, source_card):
    for n in range(count):
        destination=state['discard_pile'] if pile=='hand' and len(state['hand'])>=10 else state[pile]
        generated=card_state(dict(id=ident,uuid=f'@generated:{state["plays"]}:{ident}:{n}',
            type='STATUS',cost=-2,has_target=False,exhausts=False,ethereal=ident=='Dazed'))
        if 'can_upgrade' in source_card: generated['can_upgrade']=False
        for flag in ('free_to_play_once','exhaust_on_use_once','retain','self_retain','purge_on_use'):
            if flag in source_card: generated[flag]=False
        if 'target_type' in source_card: generated['target_type']='NONE'
        destination.append(generated)
        record_generation(state,ident,'STATUS',uuid=generated['uuid'])
    if pile=='draw_pile' and count: state['known_top']=[]


def checkpoint(state, reason):
    state['checkpoint'] = state['checkpoint'] or reason


def upgrade_from_preview(state, card):
    """Consume one observed upgrade, never extrapolate the next upgrade."""
    if card.get('can_upgrade') is False:
        return
    preview = card.get('upgrade_preview')
    fields = ('cost', 'base_damage', 'base_block', 'magic_number', 'upgrades')
    # Native previews are emitted only for canUpgrade() cards. In particular,
    # timesUpgraded alone cannot establish eligibility (e.g. Searing Blow).
    if (not isinstance(preview, dict) or any(type(preview.get(k)) is not int for k in fields)
            or preview['cost'] < -2 or preview['upgrades'] <= card.get('upgrades', 0)):
        checkpoint(state, 'upgrade_values_unavailable')
        return
    card.update({k: max(0, preview[k]) if k in {'base_damage', 'base_block', 'magic_number'}
                 else preview[k] for k in fields})
    if card['id'] == 'Body Slam': card['base_damage'] = 0
    # Eligibility after this upgrade is not supplied by the original snapshot.
    # A later attempted upgrade must observe fresh values instead of reusing it.
    card.pop('upgrade_preview', None)


def draw(state, count):
    if count > 0 and not state['powers'].get('No Draw'):
        if 'Confusion' in state['powers'] and len(state['hand'])<10 and (state['draw_pile'] or state['discard_pile']):
            # Even a known next card receives a fresh unknown cost (0..3).
            state['draws']+=min(count,10-len(state['hand']))
            checkpoint(state,'confusion_draw_cost')
            return
        while count and state['known_top'] and len(state['hand']) < 10:
            uid = state['known_top'].pop(0)
            card = next((c for c in state['draw_pile'] if c['uuid'] == uid), None)
            if card is None: break
            state['draw_pile'].remove(card); state['hand'].append(card); count -= 1
            if card['id'] == 'Void': state['energy'] = max(0, state['energy'] - 1)
            if card['type'] in {'STATUS', 'CURSE'}:
                for i in live(state): damage_enemy(state, i, state['powers'].get('Fire Breathing', 0), False)
            if card['type'] == 'STATUS': count += state['powers'].get('Evolve', 0)
        count = min(count, 10 - len(state['hand']), len(state['draw_pile']) + len(state['discard_pile']))
        if count:
            pool = state['draw_pile'] + state['discard_pile']
            def affordable(c):
                cost = c['cost']
                if 'Corruption' in state['powers'] and c['type'] == 'SKILL': cost = 0
                if c['type']=='ATTACK' and state['powers'].get('FreeAttackPower',0)>0: cost = 0
                if c.get('free_to_play_once'): cost = 0
                return c['type'] in {'ATTACK','SKILL','POWER'} and ((cost >= 0 and cost <= state['energy'])
                    or (cost == -1 and (state['energy'] > 0 or 'Chemical X' in state['relics'])))
            playable = sum(affordable(c) for c in pool)
            state['draw_prospects'].append({'count':count,'pool_size':len(pool),'affordable_cards':playable,
                'expected_affordable_draws':count * playable / len(pool),
                'has_on_draw_risks':any(c['type'] in {'STATUS','CURSE'} for c in pool),
                'basis':'unordered pool estimate; excludes cards still resolving'})
            state['draws'] += count
            checkpoint(state, 'draw_cards')


def gain_block(state, amount, modified=True):
    if modified and state['powers'].get('NoBlock'):
        return
    if modified:
        amount = floor(max(0, amount + state['powers'].get('Dexterity', 0)) *
                       (0.75 if state['powers'].get('Frail', 0) > 0 else 1))
    if amount <= 0:
        return
    state['block'] = min(999, state['block'] + amount)
    if state['powers'].get('Juggernaut'):
        if len(live(state)) == 1:
            damage_enemy(state, live(state)[0], state['powers']['Juggernaut'], attack=False)
        elif live(state):
            checkpoint(state, 'juggernaut_random_target')


def heal(state, amount):
    if 'Magic Flower' in state['relics']:
        amount = floor(amount * 1.5)
    amount = min(amount, state['max_hp'] - state['hp'])
    state['hp'] += amount
    state['healing'] += amount


def lose_hp(state, amount, card=False, attack=False, blockable=False):
    if attack or blockable:
        blocked = min(amount, state['block']); state['block'] -= blocked; amount -= blocked
        state['blocked_total'] += blocked
        if attack and 0 < amount <= 5 and 'Torii' in state['relics']:
            amount = 1
    if amount > 0 and 'TungstenRod' in state['relics']:
        amount -= 1
    if amount <= 0:
        return
    if state['powers'].get('Buffer', 0) > 0:
        state['powers']['Buffer'] -= 1
        return
    state['hp'] = max(0, state['hp'] - amount)
    state['hp_spent'] += amount
    for c in state['hand'] + state['draw_pile'] + state['discard_pile']:
        if c['id'] == 'Blood for Blood':
            c['cost'] = max(0, c['cost'] - 1)
    if card:
        state['powers']['Strength'] = state['powers'].get('Strength', 0) + state['powers'].get('Rupture', 0)
    if 'Runic Cube' in state['relics']:
        draw(state, 1)
    if 'Centennial Puzzle' in state['relics'] and state['relics']['Centennial Puzzle'] != -2:
        state['relics']['Centennial Puzzle'] = -2; draw(state, 3)
    if state['hp'] == 0 and ('Lizard Tail' in state['relics'] or any(p.get('id') == 'FairyPotion' for p in state.get('potions', []))):
        checkpoint(state, 'revival')
    if 'Red Skull' in state['relics']:
        checkpoint(state, 'red_skull_threshold')


def apply_power(state, target, power, amount, debuff=False):
    owner = state if target is None else state['enemies'][target]
    if debuff and owner['powers'].get('Artifact', 0) > 0:
        owner['powers']['Artifact'] -= 1
        if owner['powers']['Artifact'] == 0: del owner['powers']['Artifact']
        return
    owner['powers'][power] = owner['powers'].get(power, 0) + amount
    if power == 'Vulnerable' and target is not None and 'Champion Belt' in state['relics']:
        apply_power(state, target, 'Weak', 1, True)


def damage_enemy(state, index, amount, attack=True):
    enemy = state['enemies'][index]
    splitting_slime = enemy['id'] in {'SlimeBoss', 'AcidSlime_L', 'SpikeSlime_L'}
    if enemy['hp'] <= 0:
        return 0
    if enemy['powers'].get('Intangible', 0) > 0:
        amount = min(amount, 1)
    if enemy['powers'].get('Flight', 0) > 0 and attack:
        amount = floor(amount / 2)
    if 'Invincible' in enemy['powers']:
        amount = min(amount, enemy['powers']['Invincible'])
    absorbed = min(enemy['block'], amount); enemy['block'] -= absorbed
    loss = max(0, amount - absorbed)
    if attack and 0 < loss < 5 and 'Boot' in state['relics']:
        loss = 5
    dealt = min(enemy['hp'], loss); enemy['hp'] -= dealt
    if dealt > 0 and enemy['id'] == 'Lagavulin' and enemy['intent'] == 'SLEEP':
        # The observed wake transition changes intent and removes Metallicize.
        # Do not continue a segment using the pre-hit sleeping state.
        checkpoint(state, 'lagavulin_wake')
    if 'Invincible' in enemy['powers']:
        enemy['powers']['Invincible'] = max(0, enemy['powers']['Invincible'] - dealt)
    if attack:
        lose_hp(state, enemy['powers'].get('Thorns', 0), blockable=True)
    # Guardian counts actual HP loss from every damage source. Attacks below
    # the remaining threshold do not change its intent or interrupt the plan.
    if enemy['hp'] > 0 and enemy['id'] == 'TheGuardian' and 'Mode Shift' in enemy['powers']:
        enemy['powers']['Mode Shift'] = max(0, enemy['powers']['Mode Shift'] - dealt)
        if enemy['powers']['Mode Shift'] == 0:
            from .monsters import cancel_attack
            cancel_attack(state,index,'guardian_mode_shift','BUFF',1,pending_block=20)
            checkpoint(state, 'enemy_reaction')
    # Native slime damage handlers interrupt the intent only at half HP,
    # including HP lost to non-attack damage. Above it, keep planning the turn.
    if splitting_slime and 0 < enemy['hp'] <= enemy['max_hp'] / 2 and enemy.get('move_id')!=3:
        from .monsters import cancel_attack
        cancel_attack(state,index,'slime_split','UNKNOWN',3,child_hp_each=enemy['hp'])
        checkpoint(state, 'slime_split_intent')
    if enemy['hp'] <= 0:
        if enemy['powers'].get('Spore Cloud'):
            apply_power(state, None, 'Vulnerable', enemy['powers']['Spore Cloud'], True)
        if enemy['half_dead'] or enemy['id'] in {'Darkling', 'AwakenedOne'}:
            checkpoint(state, 'enemy_revives')
        enemy['powers'] = {}
    elif attack:
        if dealt > 0:
            enemy['block'] += enemy['powers'].pop('Curl Up', 0)
            if 'Angry' in enemy['powers']:
                apply_power(state, index, 'Strength', enemy['powers']['Angry'])
                # This deterministic power change is resolved by refresh_intents
                # after the card. Only missing native base damage needs an
                # observation boundary; otherwise keep searching the same turn.
        if amount > 0 and enemy['powers'].get('Malleable', 0) > 0:
            enemy['block'] += enemy['powers']['Malleable']; enemy['powers']['Malleable'] += 1
        if ('Flight' in enemy['powers'] or ('Split' in enemy['powers'] and not splitting_slime)
                or ('Mode Shift' in enemy['powers'] and enemy['id'] != 'TheGuardian')):
            checkpoint(state, 'enemy_reaction')
    return dealt


def attack_damage(state, card, target):
    strength = state['powers'].get('Strength', 0)
    if card['id'] == 'Heavy Blade': strength *= card['magic_number']
    base = state['block'] if card['id'] == 'Body Slam' else card['base_damage']
    if card['id'] == 'Perfected Strike':
        base += card['magic_number'] * sum('Strike' in c['id'] for pile in ('hand', 'draw_pile', 'discard_pile') for c in state[pile])
        base += card['magic_number']  # The playing card is already in limbo.
    amount = max(0, base + strength + state['powers'].get('Vigor', 0))
    if state['powers'].get('Weak', 0) > 0: amount *= 0.75
    if state['enemies'][target]['powers'].get('Vulnerable', 0) > 0:
        amount *= 1.75 if 'Paper Frog' in state['relics'] else 1.5
    if state['powers'].get('Pen Nib', 0) > 0 or state['relics'].get('Pen Nib') == 9:
        amount *= 2
    if state['powers'].get('Double Damage', 0) > 0:
        amount *= 2
    return floor(amount)


def exhaust(state, card, trigger=True):
    state['exhaust_pile'].append(card)
    if trigger: exhaust_effects(state, card)


def exhaust_effects(state, card):
    if card['id'] == 'Sentinel':
        state['energy'] += card['magic_number']
    gain_block(state, state['powers'].get('Feel No Pain', 0), False)
    draw(state, state['powers'].get('Dark Embrace', 0))
    if 'Charon\'s Ashes' in state['relics']:
        for i in live(state): damage_enemy(state, i, 3, False)
    if 'Dead Branch' in state['relics']:
        record_generation(state, 'UNKNOWN', 'UNKNOWN'); checkpoint(state, 'dead_branch')
    if card['id'] == 'Necronomicurse': checkpoint(state, 'curse_returns_to_hand')


def legal_steps(state):
    if state['checkpoint'] or state['hp'] <= 0 or not live(state):
        return []
    if 'Velvet Choker' in state['relics'] and state['plays'] >= 6:
        return []
    if state['plays'] >= 3 and any(c['id'] == 'Normality' for c in state['hand']):
        return []
    result = []
    for card in state['hand']:
        ident = card['id']; kind = card['type']
        if state['powers'].get('Entangled', 0) > 0 and kind == 'ATTACK': continue
        if ident == 'Clash' and any(c['type'] != 'ATTACK' for c in state['hand']): continue
        if kind == 'STATUS' and ident != 'Slimed' and 'Medical Kit' not in state['relics']: continue
        if kind == 'CURSE' and 'Blue Candle' not in state['relics']: continue
        cost = card['cost']
        if 'Corruption' in state['powers'] and kind == 'SKILL': cost = 0
        if card.get('free_to_play_once') or (kind == 'ATTACK' and state['powers'].get('FreeAttackPower', 0) > 0): cost = 0
        if cost > state['energy'] or (cost < -1 and kind not in {'STATUS', 'CURSE'}): continue
        targets = live(state) if card.get('has_target') else [None]
        if ident in AOE: targets = [None]
        for target in targets:
            choices = [None]
            if ident in SELECT:
                pool = state['discard_pile'] if ident == 'Headbutt' else state['exhaust_pile'] if ident == 'Exhume' else state['hand']
                pool = [c for c in pool if c['uuid'] != card['uuid']]
                if ident == 'Dual Wield': pool = [c for c in pool if c['type'] in {'ATTACK', 'POWER'}]
                if ident == 'Exhume': pool = [c for c in pool if c['id'] != 'Exhume']
                if ident == 'Armaments': pool = [c for c in pool if c.get('can_upgrade', c.get('upgrades', 0) == 0) and c['id'] in CARD_SPECS]
                if (ident == 'Armaments' and card.get('upgrades', 0)) or (ident == 'True Grit' and not card.get('upgrades', 0)):
                    pool = []
                choices = [c['uuid'] for c in pool] or [None]
            result.extend(dict(kind='play', card_uuid=card['uuid'], target_index=target, selection_uuid=choice) for choice in choices)
    return result


def play(before, step):
    state = clone_state(before)
    card = next(c for c in state['hand'] if c['uuid'] == step['card_uuid'])
    state['hand'].remove(card)
    ident, kind, target = card['id'], card['type'], step.get('target_index')
    sharp_hide=[(i,before['enemies'][i]['powers']['Sharp Hide']) for i in live(before)
                if kind=='ATTACK' and before['enemies'][i]['powers'].get('Sharp Hide')]
    magic = card['magic_number']; upgraded = bool(card.get('upgrades'))
    cost = card['cost']; x = state['energy'] + (2 if 'Chemical X' in state['relics'] else 0)
    free = card.get('free_to_play_once') or ('Corruption' in state['powers'] and kind == 'SKILL')
    if kind == 'ATTACK' and state['powers'].get('FreeAttackPower', 0) > 0:
        free = True; state['powers']['FreeAttackPower'] -= 1
    if not free: state['energy'] -= state['energy'] if cost == -1 else max(0, cost)
    selected = step.get('selection_uuid')
    for held in state['hand']:
        if held['id'] == 'Pain': lose_hp(state, 1, card=True)
    if kind == 'CURSE': lose_hp(state, 1, card=True)
    if ident not in CARD_SPECS and kind not in {'STATUS', 'CURSE'}:
        state['uncertainties'].append('unmodeled_card:' + ident)
        checkpoint(state, 'unmodeled_card')
    if kind == 'SKILL':
        # AngerPower.onUseCard adds Strength via addToTop before card effects.
        # This is Nob's Skill trigger, distinct from Angry's attack reaction.
        for i in live(state):
            amount = state['enemies'][i]['powers'].get('Anger', 0)
            if amount: apply_power(state, i, 'Strength', amount)
    # Effects that precede damage.
    if ident == 'Hemokinesis': lose_hp(state, magic, card=True)
    if ident in {'Sever Soul', 'Second Wind', 'Fiend Fire'}:
        victims = [c for c in state['hand'] if ident == 'Fiend Fire' or c['type'] != 'ATTACK']
        for victim in victims:
            state['hand'].remove(victim); exhaust(state, victim, trigger=ident != 'Fiend Fire')
            if ident == 'Second Wind': gain_block(state, card['base_block'])
    else: victims = []
    if card['base_block'] and ident != 'Second Wind': gain_block(state, card['base_block'])
    was_vulnerable = target is not None and state['enemies'][target]['powers'].get('Vulnerable', 0) > 0
    if kind == 'ATTACK':
        gain_block(state, state['powers'].get('Rage', 0), False)
        hits = 2 if ident == 'Twin Strike' else magic if ident in {'Pummel', 'Sword Boomerang'} else x if ident == 'Whirlwind' else len(victims) if ident == 'Fiend Fire' else 1
        repeats = 1
        for power in ('Double Tap', 'DuplicationPower'):
            if state['powers'].get(power, 0) > 0:
                state['powers'][power] -= 1; repeats += 1
                checkpoint(state, 'duplicated_card_resolution')
                state['uncertainties'].append('duplicate_non_damage_effects')
        if 'Necronomicon' in state['relics'] and cost >= 2:
            checkpoint(state, 'necronomicon_trigger')
        if ident == 'Sword Boomerang' and len(live(state)) > 1:
            checkpoint(state, 'random_attack_targets')
            state['notes'].append(dict(random_hits=hits, damage_per_hit=card['base_damage']))
        else:
            total_loss = 0
            for _ in range(hits * repeats):
                targets = live(state) if ident in AOE else live(state)[:1] if ident == 'Sword Boomerang' else [target]
                for i in targets:
                    if i is not None and state['enemies'][i]['hp'] > 0:
                        total_loss += damage_enemy(state, i, attack_damage(state, card, i))
                if state['hp'] <= 0: break
            if ident == 'Reaper': heal(state, total_loss)
        state['attacks'] += 1
        state['attacks_this_combat'] += 1
        state['powers'].pop('Vigor', None)
        state['powers'].pop('Pen Nib', None)
        for relic, divisor in [('Pen Nib', 10), ('Nunchaku', 10), ('Shuriken', 3), ('Kunai', 3), ('Ornamental Fan', 3)]:
            if relic not in state['relics']: continue
            state['relics'][relic] = (max(0, state['relics'][relic]) + 1) % divisor
            if state['relics'][relic] == 0:
                if relic == 'Nunchaku': state['energy'] += 1
                if relic == 'Shuriken': apply_power(state, None, 'Strength', 1)
                if relic == 'Kunai': apply_power(state, None, 'Dexterity', 1)
                if relic == 'Ornamental Fan': gain_block(state, 4, False)
        # FiendFireAction pushes exhaust actions before its damage actions, but
        # onExhaust callbacks enqueue their block/draw at the bottom, after hits.
        if ident == 'Fiend Fire' and state['hp'] > 0:
            for victim in victims: exhaust_effects(state, victim)
    if target is not None and state['enemies'][target]['hp'] > 0:
        if ident in {'Bash', 'Uppercut'}: apply_power(state, target, 'Vulnerable', magic, True)
        if ident in {'Clothesline', 'Uppercut'}: apply_power(state, target, 'Weak', magic, True)
        if ident == 'Disarm':
            apply_power(state, target, 'Strength', -magic, True)
    if ident in {'Thunderclap', 'Shockwave', 'Intimidate'}:
        for i in live(state):
            # Native ThunderClap.use uses literal 1; magicNumber is -1 (N/A).
            # An unused field must not override this verified fixed effect.
            if ident != 'Intimidate': apply_power(state, i, 'Vulnerable', 1 if ident == 'Thunderclap' else magic, True)
            if ident != 'Thunderclap': apply_power(state, i, 'Weak', magic, True)
    if ident in {'Inflame', 'Flex', 'Spot Weakness'}:
        if ident != 'Spot Weakness' or (target is not None and state['enemies'][target]['intent'].startswith('ATTACK')):
            apply_power(state, None, 'Strength', magic)
            if ident == 'Flex': apply_power(state, None, 'LoseStrength', magic, True)
    elif ident == 'Limit Break': apply_power(state, None, 'Strength', state['powers'].get('Strength', 0))
    elif ident == 'Entrench': gain_block(state, state['block'], False)
    elif ident in {'Seeing Red', 'Bloodletting', 'Offering'}:
        if ident == 'Bloodletting': lose_hp(state, 3, card=True)
        if ident == 'Offering': lose_hp(state, 6, card=True)
        state['energy'] += magic if ident == 'Bloodletting' else 2
    elif ident == 'Rage': apply_power(state, None, 'Rage', magic)
    elif ident == 'Double Tap': apply_power(state, None, 'Double Tap', magic)
    elif ident == 'Flame Barrier': apply_power(state, None, 'Flame Barrier', magic)
    if kind == 'POWER':
        if ident == 'Berserk':
            apply_power(state, None, 'Vulnerable', magic, True); apply_power(state, None, 'Berserk', 1)
        elif ident in {'Corruption', 'Barricade'}:
            state['powers'][ident] = -1
        elif ident not in {'Inflame'}:
            apply_power(state, None, POWER_IDS.get(ident, ident), magic or 1)
        if 'Bird Faced Urn' in state['relics']: heal(state, 2)
        if 'Mummified Hand' in state['relics']: checkpoint(state, 'random_cost_change')
        if ident == 'Combust' and state['combust_hp_loss'] is not None:
            state['combust_hp_loss'] += 1
    if ident == 'Feed' and target is not None and state['enemies'][target]['hp'] == 0 and not before['enemies'][target]['powers'].get('Minion'):
        state['max_hp'] += magic; heal(state, magic)
    if ident == 'Rampage': card['base_damage'] += magic
    if ident == 'Anger':
        copy = deepcopy(card); copy['uuid'] = f'@generated:{state["plays"]}:Anger:0'; state['discard_pile'].append(copy)
        record_generation(state, 'Anger', 'ATTACK', uuid=copy['uuid'])
    for name, pile, count in [('Wild Strike', 'draw_pile', 1), ('Reckless Charge', 'draw_pile', 1), ('Power Through', 'hand', 2), ('Immolate', 'discard_pile', 1)]:
        if ident == name:
            generated_id = 'Dazed' if ident == 'Reckless Charge' else 'Burn' if ident == 'Immolate' else 'Wound'
            add_status_cards(state,generated_id,count,pile,card)
    if ident in {'Pommel Strike', 'Warcry', 'Battle Trance', 'Offering'}: draw(state, magic)
    if ident == 'Deep Breath':
        shuffled = len(state['discard_pile'])
        if shuffled:
            state['draw_pile'].extend(state['discard_pile'])
            state['discard_pile'] = []
            state['known_top'] = []
            if 'Sundial' in state['relics']:
                state['relics']['Sundial'] = (max(0,state['relics']['Sundial']) + 1) % 3
                if state['relics']['Sundial'] == 0: state['energy'] += 2
        draw(state, magic)
        state['notes'].append({'effect':'shuffle_discard_into_draw_then_draw','cards_shuffled':shuffled,
                               'requested_draw':magic,'pending_draw':state['draws'],
                               'continuation':'Observe the actual cards, then plan the remaining energy. This is not END.'})
    if ident == 'Shrug It Off': draw(state, 1)
    if ident == 'Battle Trance': apply_power(state, None, 'No Draw', -1, True)
    if ident == 'Dropkick' and was_vulnerable:
        state['energy'] += 1; draw(state, 1)
    if ident == 'Infernal Blade':
        record_generation(state, 'UNKNOWN', 'ATTACK'); checkpoint(state, 'unknown_card')
    if ident == 'Discovery':
        record_generation(state, 'UNKNOWN', 'UNKNOWN'); checkpoint(state, 'card_choice')
        state['notes'].append({'effect':'choose_one_of_three_random_cards','cost_this_turn':0})
    if ident == 'Havoc' and (state['draw_pile'] or state['discard_pile']):
        checkpoint(state, 'autoplay_top_card')
    if ident in SELECT:
        if ident == 'Armaments':
            for candidate in state['hand']:
                if upgraded or candidate['uuid'] == selected:
                    upgrade_from_preview(state, candidate)
        elif ident in {'Headbutt', 'Exhume'}:
            source = state['discard_pile'] if ident == 'Headbutt' else state['exhaust_pile']
            chosen = next((c for c in source if c['uuid'] == selected), None)
            if chosen:
                source.remove(chosen)
                destination = state['draw_pile'] if ident == 'Headbutt' else state['hand'] if len(state['hand']) < 10 else state['discard_pile']
                destination.append(chosen)
                if ident == 'Headbutt': state['known_top'].insert(0, chosen['uuid'])
        elif ident == 'Dual Wield':
            chosen = next((c for c in state['hand'] if c['uuid'] == selected), None)
            if chosen:
                # Native Dual Wield replaces the selected original with a copy too.
                chosen['uuid'] = f'@generated:{state["plays"]}:{chosen["id"]}:original'
                for n in range(magic):
                    copy = deepcopy(chosen); copy['uuid'] = f'@generated:{state["plays"]}:{copy["id"]}:{n}'
                    (state['hand'] if len(state['hand']) < 10 else state['discard_pile']).append(copy)
                    record_generation(state, copy['id'], copy['type'], uuid=copy['uuid'])
        if ident in {'True Grit', 'Burning Pact'}:
            if ident == 'True Grit' and not upgraded and len(state['hand']) > 1:
                checkpoint(state, 'random_exhaust')
            else:
                victim = next((c for c in state['hand'] if c['uuid'] == selected), state['hand'][0] if len(state['hand']) == 1 else None)
                if victim: state['hand'].remove(victim); exhaust(state, victim)
            if ident == 'Burning Pact': draw(state, magic)
    if kind == 'SKILL':
        state['skills'] += 1
        if 'Letter Opener' in state['relics']:
            state['relics']['Letter Opener'] = (max(0, state['relics']['Letter Opener']) + 1) % 3
            if state['relics']['Letter Opener'] == 0:
                for i in live(state): damage_enemy(state, i, 5, False)
    # Native SharpHidePower.onUseCard queues one retaliation AFTER card.use's
    # effects, BEFORE UseCardAction disposes/exhausts the played card. It is not
    # Thorns and does not trigger once per hit or only on the attacked target.
    for index,amount in sharp_hide:
        if state['enemies'][index]['hp']<=0:
            checkpoint(state,'sharp_hide_on_kill')
        else:
            lose_hp(state,amount,blockable=True)
    should_exhaust = (card.get('exhausts') or card.get('exhaust_on_use_once') or ident in EXHAUST or (ident == 'Limit Break' and not upgraded)
                      or (kind == 'SKILL' and 'Corruption' in state['powers']) or kind in {'STATUS', 'CURSE'})
    if kind!='ATTACK' and state['powers'].get('Hex',0)>0:
        add_status_cards(state,'Dazed',state['powers']['Hex'],'draw_pile',card)
    if should_exhaust:
        if 'Strange Spoon' in state['relics']: checkpoint(state, 'strange_spoon')
        exhaust(state, card)
    elif kind != 'POWER': state['discard_pile'].append(card)
    state['plays'] += 1
    for enemy in state['enemies']:
        lose_hp(state, enemy['powers'].get('BeatOfDeath', 0), blockable=True)
        # Counter zero still has the power: the very first play advances it.
        # Its forced-end ordering is not modeled, so observe after each play.
        if 'Time Warp' in enemy['powers']: checkpoint(state, 'time_warp')
    if not state['hand'] and 'Unceasing Top' in state['relics']: draw(state, 1)
    refresh_intents(state, before)
    if state['uncertainties']: checkpoint(state, 'unmodeled_effect')
    return state


def outcome(state, *, include_position=False):
    """Conservative end-turn estimate; unknown intent remains unknown."""
    ended = clone_state(state)
    pp = ended['powers']
    # GameActionManager.callEndOfTurnActions invokes relics before card/power
    # end-turn effects; Orichalcum observes block before those gains resolve.
    if ended['block'] == 0 and 'Orichalcum' in ended['relics']: gain_block(ended, 6, False)
    for card in list(ended['hand']):
        if card.get('ethereal'):
            ended['hand'].remove(card); exhaust(ended, card)
    gain_block(ended, pp.get('Metallicize', 0), False)
    gain_block(ended, pp.get('Plated Armor', 0), False)
    if pp.get('Combust'):
        if ended['combust_hp_loss'] is None:
            checkpoint(ended, 'missing_combust_hp_loss')
        else:
            lose_hp(ended, ended['combust_hp_loss'], card=True)
        for i in live(ended): damage_enemy(ended, i, pp['Combust'], False)
    for card in ended['hand']:
        if card['id'] == 'Burn': lose_hp(ended, 4 if card.get('upgrades') else 2, blockable=True)
        if card['id'] == 'Decay': lose_hp(ended, 2, blockable=True)
        if card['id'] == 'Regret': lose_hp(ended, len(ended['hand']), card=True)
    thief_start=deepcopy(ended['enemies']) if any(e['id'] in {'Looter','Mugger'} for e in ended['enemies']) else None
    incoming = 0; known = True
    for i in live(ended):
        enemy = ended['enemies'][i]
        if enemy['id']=='GremlinWizard' and enemy['move_id']==2:
            continue  # CHARGE increments currentCharge; it deals no damage.
        if enemy['intent'].startswith('ATTACK'):
            damage, hits = enemy['damage'], enemy['hits']
            if type(damage) is not int or type(hits) is not int or damage < 0 or hits < 1:
                known = False; continue
            for _ in range(hits):
                amount = damage
                # Native adjusted damage normally includes player's vulnerability.
                # Changed defensive powers require an observation before certification.
                incoming += amount
                lose_hp(ended, amount, attack=True)
                if pp.get('Flame Barrier'): damage_enemy(ended, i, pp['Flame Barrier'], False)
                if 'Bronze Scales' in ended['relics']: damage_enemy(ended, i, 3, False)
                if ended['enemies'][i]['hp'] <= 0: break
        elif enemy['id'] in {'SlimeBoss','AcidSlime_L','SpikeSlime_L'} and enemy.get('move_id')==3:
            pass  # Native SPLIT spawns children; the cancelled attack does not execute.
        elif enemy['intent'] not in {'BUFF', 'DEFEND', 'DEFEND_BUFF', 'SLEEP', 'DEBUFF', 'STRONG_DEBUFF', 'ESCAPE', 'STUN', 'NONE'}:
            known = False
    enemy_hp = [max(0, e['hp']) for e in state['enemies']]
    won = not live(state) and not any(e['half_dead'] for e in state['enemies'])
    reliable = not state['checkpoint'] and not state['uncertainties'] and (won or not ended['checkpoint'])
    if won:
        ended = clone_state(state)
        known = True
    standing_loss = max(0, state['hp'] - ended['hp']) if known else None
    if not reliable:
        known = False
    remaining = ended['block'] if reliable and known else None
    retained = (remaining if pp.get('Barricade') else max(0, remaining - 15)
                if 'Calipers' in ended['relics'] else 0) if remaining is not None else None
    created_ids = set(state['created_card_ids'])
    pollution = Counter(c['type'] for pile in ('hand', 'draw_pile', 'discard_pile')
                        for c in ended[pile] if c['uuid'] in created_ids and c['type'] in {'STATUS', 'CURSE'})
    exhausted = Counter(c['id'] for c in ended['exhaust_pile'] if c['uuid'] not in state['initial_exhaust_ids'])
    result = dict(enemy_hp=sum(enemy_hp), enemy_hp_by_target=enemy_hp,
                enemy_hp_after_turn_by_target=[max(0,e['hp']) for e in ended['enemies']] if reliable and known else None,
                incoming_hp_loss=max(0, state['hp'] - ended['hp']) if known else None,
                player_hp_after_turn=ended['hp'] if known else None,
                standing_hp_loss_estimate=standing_loss,
                standing_estimate_scope='current known state only; excludes unresolved draws and effects',
                self_damage=state['hp_spent'], healing=state['healing'], remaining_energy=state['energy'],
                block=state['block'], powers=deepcopy(state['powers']), draw_count=state['draws'],
                effective_block=ended['blocked_total'] if reliable and known else None,
                wasted_block=remaining-retained if remaining is not None else None,
                remaining_block_after_turn=remaining, retained_block=retained,
                generated_card_counts=deepcopy(state['generated_card_counts']),
                generated_card_types=deepcopy(state['generated_card_types']),
                new_status_cards=state['generated_card_types'].get('STATUS', 0),
                new_curse_cards=state['generated_card_types'].get('CURSE', 0),
                unexhausted_status_cards=pollution['STATUS'], unexhausted_curse_cards=pollution['CURSE'],
                exhausted_card_counts=dict(exhausted), potions_used=deepcopy(state['potions_used']),
                draw_prospects=deepcopy(state['draw_prospects']),
                generated_cards=state['generated'], exhaust_count=len(state['exhaust_pile']),
                combat_won=won and state['hp'] > 0 and reliable,
                forecast_scope='deterministic' if reliable and known else 'partial',
                continuation=state['checkpoint'] or ended['checkpoint'])
    result['interruptions']=deepcopy(state['interruptions'])
    for interrupted in result['interruptions']:
        if interrupted['reason']=='slime_split':
            interrupted['child_hp_each']=state['enemies'][interrupted['target_index']]['hp']
    from .monsters import economy_forecast
    result['economy']=economy_forecast(state,thief_start,ended['enemies'])
    if include_position:
        from .position import position_context
        result['position']=position_context(state,ended,result)
    return result
