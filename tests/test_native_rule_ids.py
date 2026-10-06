import json
from pathlib import Path

from slay_jev_spire import rules
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.screens import prepare_screen
from tools.audit_strategy import fixture,card


def test_declared_supported_ids_resolve_to_native_ids_not_display_names():
    ids=json.loads(Path('samples/native_rule_ids.json').read_text(encoding='utf-8'))
    assert set(rules.CARD_SPECS)<=set(ids['cards'])
    assert rules.PASSIVE_RELICS|rules.TRIGGER_RELICS<=set(ids['relics'])
    normalized=rules.powers([{'id':p,'amount':1} for p in ids['power_ids']])
    assert rules.KNOWN_POWERS<=set(normalized)


def test_paper_frog_native_id_models_vulnerable_and_boot_models_damage_floor():
    case=fixture('frog',[card('Strike_R',1,damage=6)],relics=[{'id':'Paper Frog'}],enemy_powers=[('Vulnerable',1)])
    state=rules.initial(prepare_native_combat(case['raw'])[0])
    state=rules.play(state,rules.legal_steps(state)[0])
    assert state['enemies'][0]['hp']==30 and not state['uncertainties']
    case=fixture('boot',[card('Strike_R',1,damage=1)],relics=[{'id':'Boot'}])
    state=rules.initial(prepare_native_combat(case['raw'])[0]);state=rules.play(state,rules.legal_steps(state)[0])
    assert state['enemies'][0]['hp']==35 and not state['uncertainties']


def test_native_temporary_strength_and_no_block_are_normalized():
    assert rules.powers([{'id':'Flex','amount':2},{'id':'NoBlockPower','amount':1}])=={'LoseStrength':2,'NoBlock':1}
    case=fixture('no block',[card('Defend_R',1,'SKILL',block=5)],powers=[('NoBlockPower',1)])
    state=rules.initial(prepare_native_combat(case['raw'])[0]);state=rules.play(state,rules.legal_steps(state)[0])
    assert state['block']==0 and not state['uncertainties']


def test_rest_uses_native_option_description_instead_of_unknown_effect_label():
    raw={'available_commands':['choose'],'game_state':{'screen_type':'REST','choice_list':['rest'],
         'screen_state':{'rest_options':['rest'],'rest_option_details':{'rest':{'description':'Heal 24 HP (30% of maximum HP).'}}}}}
    action=prepare_screen(raw)[0]
    assert action['description']=='rest: Heal 24 HP (30% of maximum HP).'
