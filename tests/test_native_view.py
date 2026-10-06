from copy import deepcopy
import pytest

from slay_jev_spire.native_view import with_current_board
from slay_jev_spire import selectors


def test_current_view_expands_live_overrides_and_retains_every_reference_fact():
    state={'player':{'current_hp':20,'max_hp':80,'energy':1,'block':0,'powers':[]},
        'card_templates':{'a':{'id':'FutureCard','name':'New card','type':'SKILL','cost':2,
            'description':'Native description','private_field':{'unknown':True},'ethereal':True}},
        'native_value_templates':{'v':{'cost_for_turn':0,'block':8}},
        'hand':[{'$card':'a','uuid':'c1','cost':0,'native_values':{'$native':'v'},'$remove':['ethereal']}],
        'draw_pile':[{'$card':'a','uuid':'c2'}],
        'enemies':[{'id':'Gone','current_hp':0,'is_gone':True},{'id':'Alive','current_hp':8,'intent':'BUFF','powers':[]}],
        'unknown_extension':{'keep':['every','fact']}}
    before=deepcopy(state);body=with_current_board(state)
    assert state==before and body['reference_state']==before
    card=body['current_board']['hand'][0]
    assert card['id']=='FutureCard' and card['cost']==0 and card['native_values']['block']==8
    assert 'ethereal' not in card and len(body['current_board']['hand'])==1
    assert body['current_board']['enemies'][1]['index']==1
    card['native_values']['block']=99
    assert state==before


@pytest.mark.parametrize('count',[2,4])
def test_overflow_removes_duplicate_view_before_splitting_candidates(monkeypatch,count):
    actions=[{'id':str(i)} for i in range(count)];seen=[]
    def provider(summary,candidates):
        seen.append((summary.get('_omit_current_board',False),list(candidates)))
        if not summary.get('_omit_current_board'):
            raise selectors.SelectionError('Provider limit',code='context_limit',attempts=1)
        return {'action':candidates[-1],'model_requests':1,'usage':{}}
    monkeypatch.setattr(selectors,'_request_with_transient_retry',provider)
    result=selectors._choose_with_context_limit({'_combat_view':'native'},actions)
    assert seen==[(False,actions),(True,actions)]
    assert result['action'] is actions[-1] and result['model_requests']==2
    assert result['encoding_retry']['retained_candidates']==count


def test_oversized_reference_alone_still_stops_without_an_infinite_retry(monkeypatch):
    calls=[]
    def provider(summary,actions):
        calls.append(summary.get('_omit_current_board',False))
        raise selectors.SelectionError('Provider limit',code='context_limit',attempts=1)
    monkeypatch.setattr(selectors,'_request_with_transient_retry',provider)
    with pytest.raises(selectors.SelectionError) as caught:
        selectors._choose_with_context_limit({'_combat_view':'native'},[{'id':'a'},{'id':'b'}])
    assert calls==[False,True] and caught.value.attempts==2
