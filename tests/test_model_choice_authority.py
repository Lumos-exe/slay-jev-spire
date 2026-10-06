from types import SimpleNamespace
import pytest

from slay_jev_spire import selectors


@pytest.mark.parametrize('probabilities,warning', [
    ({'play': .8, 'end': .2}, 'selected_choice_is_not_probability_argmax'),
    ({'play': 1.0}, 'invalid_probability_metadata'),
])
def test_legal_model_choice_is_not_vetoed_by_probability_metadata(monkeypatch, probabilities, warning):
    sdk=pytest.importorskip('typesafe_sdk')
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def system_one(self,**kwargs):
            return SimpleNamespace(model='test',usage=None,answers={
                'action':SimpleNamespace(choice='end',confidence=.5,probabilities=probabilities)})
    monkeypatch.setattr(sdk,'TypeSafeClient',Client)
    monkeypatch.setenv('TYPESAFE_API_KEY','test-only-key')
    actions=[{'id':'play','description':'Play a card'}, {'id':'end','description':'End turn'}]
    result=selectors._choose_jev_once({},actions)
    assert result['action'] is actions[1]
    assert result['metadata_warning']==warning
    if warning=='selected_choice_is_not_probability_argmax':
        assert result['choice_margin']==pytest.approx(-.6)
        assert result['probabilities']==probabilities
    else:
        assert result['probabilities'] is None and result['confidence'] is None


def test_unknown_model_action_still_cannot_execute():
    with pytest.raises(selectors.SelectionError):
        selectors.validate_choice('not-offered',[{'id':'end'}])
