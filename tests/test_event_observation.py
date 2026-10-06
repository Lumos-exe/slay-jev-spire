from copy import deepcopy
import json
import shutil
import subprocess
import pytest

from slay_jev_spire.event_observation import augment_event
from slay_jev_spire.screens import prepare_screen
from slay_jev_spire.session import DecisionMemory
from slay_jev_spire.selectors import action_criteria, instructions_for


def raw_state():
    return {'in_game':True,'ready_for_command':True,'available_commands':['choose','state'],
        'jev_protocol':{'version':1,'epoch':'epoch','revision':7},
        'game_state':{'screen_type':'EVENT','choice_list':['card2','bash'],
            'jev_identity':{'version':1,'run_id':'run','room_id':'room','encounter_id':None},
            'screen_state':{'event_id':'Match and Keep!','options':[
                {'choice_index':0,'text':'card2','label':'card2','disabled':False},
                {'choice_index':1,'text':'Bash','label':'Bash','disabled':False}]}}}


def board():
    return {'kind':'matching_cards','phase':'PLAY','ready_for_choice':True,'attempts_remaining':2,
        'selected_slot':0,'choices':[{'choice_index':0,'slot':2,'known':False},
            {'choice_index':1,'slot':4,'known':True,'card':{'id':'Bash','name':'Bash'}}]}


def test_sidecar_requires_exact_identity_revision_and_choice_order(tmp_path):
    raw=raw_state();view=board()
    envelope={'version':1,'active':True,'epoch':'epoch','revision':7,'run_id':'run',
              'room_id':'room','event_id':'Match and Keep!','choice_labels':['card2','bash'],'view':view}
    path=tmp_path/'native-event-observation.json'
    path.write_text(json.dumps(envelope))
    result=augment_event(raw,tmp_path)
    assert result['game_state']['screen_state']['native_event']==view
    assert 'native_event' not in raw['game_state']['screen_state']
    for field,value in [('epoch','old'),('room_id','old'),('revision',6),('choice_labels',['bash','card2'])]:
        changed={**envelope,field:value};path.write_text(json.dumps(changed))
        waiting=augment_event(raw,tmp_path)
        assert waiting['ready_for_command'] is False and waiting['_native_event_waiting'] is True
        assert 'native_event' not in waiting['game_state']['screen_state']


def test_native_animation_wait_and_attempt_progress_are_not_a_false_loop(tmp_path):
    raw=raw_state();view=board();raw['game_state']['screen_state']['native_event']=view
    view['board']=[{'slot':0,'known':True,'card':{'id':'Bash'}}]
    memory=DecisionMemory()
    for attempts in (3,2,1):
        view['attempts_remaining']=attempts
        ready=augment_event(raw,tmp_path)
        assert ready['game_state']['screen_state']['native_event']['selected_card_id']=='Bash'
        actions=prepare_screen(ready)
        assert memory.visit({'screen_state':ready['game_state']['screen_state']},actions)
    view['ready_for_choice']=False
    assert augment_event(raw,tmp_path)['ready_for_command'] is False


def test_board_choices_are_native_indices_and_unknown_faces_stay_unknown():
    raw=raw_state();raw['game_state']['screen_state']['native_event']=board()
    actions=prepare_screen(raw)
    assert [a['command'] for a in actions]==['CHOOSE 0','CHOOSE 1']
    assert action_criteria(actions[0])['card_id'] is None
    assert action_criteria(actions[1])['slot']==4
    assert '翻牌配对' in instructions_for({'screen_type':'EVENT','screen_state':raw['game_state']['screen_state']})


def test_hidden_native_face_supplier_is_not_called(tmp_path):
    java,javac=shutil.which('java'),shutil.which('javac')
    if not java or not javac or subprocess.run([javac,'-version'],capture_output=True).returncode:
        pytest.skip('Java unavailable')
    source=tmp_path/'VisibleTest.java'
    source.write_text('''
import java.util.*;
import jevstate.VisibleCardSlot;
public class VisibleTest {
    public static void main(String[] args) {
        Map<String,Object> hidden=VisibleCardSlot.describe(2,"opaque",false,false,()-> { throw new AssertionError("Hidden identity accessed"); });
        if (hidden.containsKey("card") || !Boolean.FALSE.equals(hidden.get("known"))) throw new AssertionError(hidden);
        Map<String,Object> seen=VisibleCardSlot.describe(2,"opaque",true,false,()->Collections.singletonMap("id","FutureModCard"));
        if (!seen.containsKey("card")) throw new AssertionError(seen);
    }
}
''',encoding='utf-8')
    subprocess.run([javac,'--release','8','-d',str(tmp_path),'mods/jev-state/src/jevstate/VisibleCardSlot.java',str(source)],check=True,capture_output=True)
    subprocess.run([java,'-cp',str(tmp_path),'VisibleTest'],check=True,capture_output=True)
