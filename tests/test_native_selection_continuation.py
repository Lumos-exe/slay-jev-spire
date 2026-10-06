from copy import deepcopy
import pytest

from slay_jev_spire.session import RunSession
from slay_jev_spire.selectors import choose_mock
from tests.test_policy_quality import battle,card


@pytest.mark.parametrize('screen',['GRID','HAND_SELECT'])
@pytest.mark.parametrize('cost_changed',[False,True])
def test_model_plan_survives_selection_but_replans_on_actual_cost_change(tmp_path,screen,cost_changed):
    raw=battle([card('Armaments',1,'SKILL',block=5,target=False),
                card('Flame Barrier',2,'SKILL',block=12,target=False)])
    calls=[]
    def select(summary,actions):
        calls.append(deepcopy(summary))
        if 'player' in summary:
            if len(calls)==1:
                selected=next(a for a in actions if [s.get('card_id',s['kind']) for s in a['sequence']]
                              ==['Armaments','Flame Barrier','end'])
            else:
                selected=next(a for a in actions if a['sequence']==[{'kind':'end'}])
        else:
            tail=summary['selected_combat_continuation']['remaining_actions']
            assert [s.get('card_id',s['kind']) for s in tail]==['Flame Barrier','end']
            selected=next(a for a in actions if a.get('card_uuid')=='Flame Barrier')
        return choose_mock(summary,[selected])
    session=RunSession(tmp_path,mode='mock',selector=select,catalog={},planning_mode='native')
    assert session.receive(raw)==['STATE']
    assert session.receive(raw)==['PLAY 1'];session.command_sent('PLAY 1')
    selecting=deepcopy(raw);game=selecting['game_state'];combat=game['combat_state']
    combat['discard_pile'].append(combat['hand'].pop(0))
    combat['player'].update(energy=2,block=5)
    game.update(screen_type=screen,is_screen_up=True,choice_list=['flame barrier'])
    game['screen_state']=dict(for_upgrade=True,num_cards=1,max_cards=1,selected=[],selected_cards=[],
                              **{'cards' if screen=='GRID' else 'hand':deepcopy(combat['hand'])})
    selecting['available_commands']=['choose']
    assert session.receive(selecting)==['STATE']
    assert len(session.turn_queue)==2
    assert session.receive(selecting)==['CHOOSE 0'];session.command_sent('CHOOSE 0')
    resumed=deepcopy(selecting);game=resumed['game_state'];combat=game['combat_state']
    game.update(screen_type='NONE',is_screen_up=False);game.pop('screen_state');game.pop('choice_list')
    resumed['available_commands']=['play','end']
    combat['hand'][0]['upgrades']=1
    combat['hand'][0]['native_values']['block']=16
    if cost_changed:combat['hand'][0]['native_values']['cost_for_turn']=1
    assert session.receive(resumed)==['STATE']
    assert session.receive(resumed)==(['END'] if cost_changed else ['PLAY 1'])
    assert len(calls)==(3 if cost_changed else 2)
    assert not session.stopped
