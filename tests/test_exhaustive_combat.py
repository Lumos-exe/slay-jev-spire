from copy import deepcopy
from itertools import combinations

from tools.audit_strategy import fixture, card
from slay_jev_spire import rules
from slay_jev_spire.session import RunSession
from slay_jev_spire.selectors import choose_mock
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans, SearchConfig


def test_three_energy_five_one_cost_cards_keep_every_playable_subset():
    case = fixture('five', [card('Strike_R', 1, damage=d) for d in range(2, 7)], enemy_hp=100)
    summary, actions = prepare_native_combat(case['raw'])
    plans, stats = generate_plans(summary, actions, SearchConfig(beam_width=1))
    expected = {frozenset(c['uuid'] for c in subset)
                for count in range(4) for subset in combinations(summary['hand'], count)}
    actual = {frozenset(s['card_uuid'] for s in p['sequence'] if s['kind']=='play') for p in plans}
    assert actual == expected and len(actual) == 26
    assert stats['complete_enumeration'] and stats['candidate_cap_pruned'] == 0


def test_all_three_potions_can_chain_and_attack_can_precede_them():
    case = fixture('potions', [card('Strike_R', 1, damage=6)], enemy_hp=100)
    raw = case['raw']; raw['available_commands'].append('potion')
    raw['game_state']['potions'] = [dict(id=cid, name=cid, potency=n,
        can_use=True, can_discard=True, requires_target=False)
        for cid, n in [('Block Potion',12), ('Strength Potion',2), ('Dexterity Potion',2)]]
    plans, stats = generate_plans(*prepare_native_combat(raw))
    assert stats['complete_enumeration']
    full = [p for p in plans if len(p['outcome']['potions_used']) == 3]
    assert full
    assert any(p['sequence'][0]['kind']=='play' for p in full)
    assert any(p['outcome']['enemy_hp']==92 for p in full)
    assert any(p['outcome']['enemy_hp']==94 for p in full)
    for p in plans:
        slots = [s['potion_index'] for s in p['sequence'] if s['kind']=='potion']
        assert len(slots) == len(set(slots))


def test_computation_guard_keeps_plans_and_all_native_starts(tmp_path):
    raw = fixture('fallback', [card('Strike_R',1,damage=6), card('Defend_R',1,'SKILL',block=5)])['raw']
    _, native = prepare_native_combat(raw)
    plans, stats = generate_plans(*prepare_native_combat(raw), SearchConfig(max_nodes=1))
    assert plans and stats['truncated'] and not stats['fallback_required']
    seen = []
    def select(summary, actions):
        seen.append(actions)
        assert all(a['kind']=='turn_plan' for a in actions)
        assert {a['sequence'][0].get('card_uuid') for a in actions} == {a.get('card_uuid') for a in native}
        return choose_mock(summary, actions)
    session = RunSession(tmp_path, mode='mock', selector=select, search_config=SearchConfig(max_nodes=1),planning_mode='enumerate')
    assert session.receive(raw)==['STATE']
    assert len(seen)==1 and not session.stopped


def test_unknown_draw_requeries_model_after_observed_hand_change(tmp_path):
    raw = fixture('draw', [card('Pommel Strike',1,damage=9,magic=1)])['raw']
    combat = raw['game_state']['combat_state']
    added = card('Bash',2,damage=8,magic=2)
    added['uuid']='drawn-bash'; combat['draw_pile']=[added]
    seen=[]
    def select(summary, actions):
        seen.append(summary)
        if len(seen)==1:
            choice=next(p for p in actions if p.get('checkpoint')=='draw_cards')
            assert len(choice['sequence'])==1
        else:
            assert any(c['uuid']=='drawn-bash' for c in summary['hand'])
            choice=next(p for p in actions if p['sequence'][0].get('card_id')=='Bash')
        return choose_mock(summary,[choice])
    session=RunSession(tmp_path,mode='mock',selector=select,planning_mode='enumerate')
    assert session.receive(raw)==['STATE']
    command=session.receive(raw)[0];session.command_sent(command)
    after=deepcopy(raw); c=after['game_state']['combat_state']
    c['discard_pile'].append(c['hand'].pop());c['hand'].append(c['draw_pile'].pop())
    c['player']['energy']=2;c['monsters'][0]['current_hp']-=9
    assert session.receive(after)==['STATE']
    assert len(seen)==2 and not session.stopped


def test_unmodeled_starting_state_keeps_sequences_without_partial_forecasts(tmp_path):
    raw=fixture('coverage',[card('Strike_R',1,damage=6)],relics=[{'id':'UnknownModRelic'}])['raw']
    plans,stats=generate_plans(*prepare_native_combat(raw))
    assert plans and not stats['fallback_required']
    assert stats['coverage_unknowns']==['unmodeled_relic:UnknownModRelic']
    seen=[]
    def choose(summary,actions):
        seen.append(actions)
        assert summary['combat_choice_mode']=='native_conditional_sequences'
        assert all('outcome' not in a and 'steps' in a for a in actions)
        assert {a['kind'] for a in actions}=={'turn_plan'}
        return choose_mock(summary,actions)
    session=RunSession(tmp_path,mode='mock',selector=choose)
    assert session.receive(raw)==['STATE'] and seen and not session.stopped


def test_start_of_turn_relic_does_not_force_a_request_after_each_card():
    raw=fixture('incense',[card('Strike_R',1,damage=6) for _ in range(3)],
                relics=[{'id':'Incense Burner','counter':5},{'id':'Sling','counter':-1}])['raw']
    plans,stats=generate_plans(*prepare_native_combat(raw))
    assert stats['complete_enumeration'] and not stats['fallback_required']
    full=next(p for p in plans if len(p['sequence'])==4)
    assert full['checkpoint'] is None
    assert 'next_start_relic_effect:Incense Burner' in full['outcome']['position']['uncertainties']
    assert any(e['source']=='Incense Burner' for e in full['outcome']['position']['future_resources']['delayed_effects'])
