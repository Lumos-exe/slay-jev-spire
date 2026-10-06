import json
from copy import deepcopy

from slay_jev_spire.selectors import action_criteria, model_payload


def test_serialized_native_options_preserve_unknown_fields_and_annotation():
    card={'id':'FutureModCard','uuid':'actual-instance','name':'New card',
          'cost':2,'type':'SKILL','unknown_mod_effect':{'counter':7},
          'raw_description':'Keep every field.'}
    action={'id':'choose_0','kind':'card','description':json.dumps(card)+' | Effect: live effect',
            'card':card}
    original=deepcopy(action)
    criteria=action_criteria(action)
    assert criteria=={'details':card,'description':' | Effect: live effect'}
    assert action==original
    state,options,refs=model_payload({'screen_state':{'cards':[card]}},[action])
    ref=options['choose_0']['details']['$card']
    assert state['card_templates'][ref]['unknown_mod_effect']=={'counter':7}
    assert len(state['card_templates'])==1
    assert refs[options['choose_0']['details']['uuid']]=='actual-instance'


def test_ordinary_labels_and_malformed_json_are_unchanged():
    for text in ('[离开]','Gain 12 gold','123 gold','{"broken":','END'):
        assert action_criteria({'description':text})==text


def test_array_descriptions_remain_structured_without_dropping_entries():
    details=[{'id':'one','value':1},{'id':'two','value':None}]
    assert action_criteria({'description':json.dumps(details)})=={'details':details}
