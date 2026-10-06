from tools.audit_shortlist_identity import witness_matches


def test_unordered_witness_preserves_multiplicity_and_excludes_potions():
    witness=dict(unordered_cards=['A','B','B'],target=1,no_potions=True)
    steps=[dict(kind='play',card_id=c,target_index=1) for c in ['B','A','B']]
    assert witness_matches(dict(sequence=steps),witness)
    assert not witness_matches(dict(sequence=steps[:-1]),witness)
    assert not witness_matches(dict(sequence=steps+[dict(kind='potion')]),witness)
    assert not witness_matches(dict(sequence=steps+[dict(kind='play',card_id='C',target_index=1)]),witness)
    assert not witness_matches(dict(sequence=[dict(s,target_index=0) for s in steps]),witness)
