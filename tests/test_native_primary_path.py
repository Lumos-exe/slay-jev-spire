from copy import deepcopy
from pathlib import Path
import json,subprocess,sys
from slay_jev_spire.session import RunSession
from slay_jev_spire.selectors import choose_mock,model_payload
from tests.test_policy_quality import battle,card


def test_unregistered_content_uses_same_native_pipeline(tmp_path,monkeypatch):
    from slay_jev_spire import session as module
    monkeypatch.delenv('JEV_PLANNING_MODE',raising=False)
    monkeypatch.setattr(module,'experimental_planner',lambda: (_ for _ in ()).throw(AssertionError('Native path imported the simulator')))
    raw=battle([card('BrandNewModCard',1,damage=17)],relics=[{'id':'BrandNewModRelic','native_description':'A new native effect.'}],
        powers=[{'id':'BrandNewPower','name':'New native power','amount':4}])
    seen=[]
    def select(summary,actions):
        seen.append((summary,actions));return choose_mock(summary,[next(a for a in actions if a['sequence'][0]['kind']=='play' and a['checkpoint'])])
    s=RunSession(tmp_path,mode='mock',selector=select,catalog={})
    assert s.planning_mode=='native'
    assert s.receive(raw)==['STATE'] and s.receive(raw)==['PLAY 1 0']
    assert seen[0][0]['hand'][0]['id']=='BrandNewModCard'
    assert not s.turn_queue


def test_native_entry_does_not_load_handwritten_rules(tmp_path):
    code='''
import sys,json
from pathlib import Path
from slay_jev_spire.transport.communication_mod import main
from slay_jev_spire.selectors import model_payload
model_payload({'screen_type':'CARD_REWARD','deck':[{'id':'FutureCard','type':'SKILL','cost':1}]},[])
assert 'slay_jev_spire.rules' not in sys.modules
assert 'slay_jev_spire.turn_planner' not in sys.modules
'''
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_default_combat_and_shortlist_do_not_load_handwritten_rules(tmp_path):
    code='''
import sys,json
from pathlib import Path
from slay_jev_spire.session import RunSession
raw=json.loads(Path('samples/communication_mod_combat.json').read_text())
raw['game_state']['combat_state']['monsters'][0]['intent']='ATTACK'
session=RunSession(Path(sys.argv[1]),mode='mock',catalog={},planning_mode='native')
assert session.receive(raw)==['STATE']
assert 'slay_jev_spire.rules' not in sys.modules
assert 'slay_jev_spire.turn_planner' not in sys.modules
'''
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_native_card_context_does_not_classify_unknown_names_as_bad():
    summary={'screen_type':'CARD_REWARD','deck':[{'id':'NeverRegistered','type':'SKILL','cost':1,'rarity':'RARE','native_description':'Native effect'}]}
    state,_,_=model_payload(summary,[])
    assert 'unclassified_effects' not in state['strategy_context']['deck']
    assert state['strategy_context']['deck']['cards'][0]['id']=='NeverRegistered'
