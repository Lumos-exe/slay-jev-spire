from copy import deepcopy
from slay_jev_spire.native_choice_text import inline_actions,keyword_glossary


def test_native_effects_stay_attached_to_exact_card_and_target():
    summary={'hand':[{'uuid':'a','id':'FutureCard','name':'New card','type':'SKILL','cost':2,
        'description':'Native effect','native_values':{'cost_for_turn':0},'free_to_play_once':True}],
        'enemies':[{'id':'enemy','name':'Enemy'}]}
    plan={'sequence':[{'kind':'play','card_uuid':'a','target_index':0},{'kind':'end'}]}
    original=deepcopy((summary,plan))
    result=inline_actions(summary,plan,[{'card_uuid':'c3'},{}])
    assert result[0]['card_ref']=='c3' and result[0]['native_text']=='Native effect'
    assert result[0]['cost_now']==0 and result[0]['card_type']=='SKILL'
    assert result[0]['target']['index']==0 and result[1]=={'action':'end'}
    assert (summary,plan)==original


def test_future_registry_terms_and_cross_references_need_no_code_rule():
    registry={'keywords':{'newterm':'Gives ward.','ward':'Blocks damage.','irrelevant':'Unrelated.'},
              'keyword_parents':{'newterm':'newterm','ward':'ward'},'card_keywords':{'NewModCard':['newterm']}}
    result=keyword_glossary({'hand':[{'uuid':'a','id':'NewModCard','description':'A new effect.'}]},registry)
    assert set(result)=={'newterm','ward'}
    assert result['newterm']['native_description']=='Gives ward.'
    assert keyword_glossary({'hand':[{'uuid':'b','id':'Unregistered'}]},registry)=={}


def test_probe_captures_valid_sdk_body_without_network():
    from tools.probe_native_choice_text import capture_body
    body=capture_body({'screen_type':'NONE'},[{'id':'end','kind':'end','command':'END','description':'End'}])
    assert body['questions']['action']['type']=='choice'
    assert set(body['questions']['action']['criteria'])=={'end'}
    assert 'offline-placeholder' not in str(body)


def test_live_registered_description_overrides_stale_prototype():
    registry={'cards':{'NewCard':{'keywords':['new']}},'keywords':{'new':'Old native definition'}}
    summary={'hand':[{'id':'NewCard','uuid':'x','keywords':['new'],
                      'keyword_descriptions':{'new':'Updated native definition'}}]}
    assert keyword_glossary(summary,registry)['new']['native_description']=='Updated native definition'
