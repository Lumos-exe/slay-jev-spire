import json
from zipfile import ZipFile

from slay_jev_spire.catalog import load_catalog, enrich_summary


def test_optional_catalog_and_pure_unknown_enrichment(tmp_path):
    assert load_catalog(None) == {'cards': {}, 'powers': {}, 'relics': {}}
    assert load_catalog(tmp_path / 'missing.jar') == load_catalog(None)
    summary = {'hand': [{'id': 'Other', 'cost': 1}], 'relics': [{'id': 'Other'}]}
    enriched = enrich_summary(summary, load_catalog(None))
    assert enriched['hand'][0]['description'] == 'unknown'
    assert 'description' not in summary['hand'][0]


def test_jar_descriptions_and_nested_metadata(tmp_path):
    path = tmp_path / 'game.jar'
    with ZipFile(path, 'w') as jar:
        jar.writestr('localization/eng/cards.json', json.dumps({'Feel No Pain': {'NAME': 'Feel No Pain', 'DESCRIPTION': 'Gain !B! Block.', 'UPGRADE_DESCRIPTION': 'Gain !M! Block.'}}))
        jar.writestr('localization/eng/powers.json', json.dumps({'Strength': {'NAME': 'Strength', 'DESCRIPTIONS': ['Adds %d damage.']}}))
        jar.writestr('localization/eng/relics.json', json.dumps({'Relic': {'NAME': 'Relic', 'DESCRIPTIONS': ['A description.']}}))
    summary = {'deck': [{'id': 'Feel No Pain', 'upgrades': 1}], 'screen_state': {'cards': [{'id': 'Feel No Pain'}]}, 'player': {'powers': [{'id': 'Strength', 'amount': 3}]}, 'relics': [{'id': 'Relic'}]}
    enriched = enrich_summary(summary, load_catalog(path))
    assert enriched['deck'][0]['description'] == 'Gain !M! Block.'
    assert enriched['deck'][0]['dynamic_values_unknown'] is True
    assert enriched['player']['powers'][0]['dynamic_values_unknown'] is True
    assert enriched['relics'][0]['description'] == 'A description.'
    assert enriched['screen_state']['cards'][0]['description'] == 'Gain !B! Block.'


def test_all_dynamic_templates_stay_unknown():
    for template in ('Gain !Custom! Block.', 'Deal %1$d damage.', 'Adds {0} damage.'):
        result = enrich_summary({'powers': [{'id': 'Any'}]}, {'powers': {'Any': {'DESCRIPTION': template}}})
        assert result['powers'][0]['description'] == template
        assert result['powers'][0]['dynamic_values_unknown'] is True
def test_native_values_resolve_only_verified_template_fields():
    from slay_jev_spire.catalog import enrich_summary
    summary = {'hand': [{'id': 'Flame Barrier', 'upgrades': 0,
                          'native_values': {'block': 12, 'magic_number': 4, 'damage': -1,
                                            'source': 'game_card_fields'},
                          'raw_description': 'Gain !B! Block. Return !M! damage. !OTHER!'}]}
    result = enrich_summary(summary, {})['hand'][0]
    assert result['description'] == 'Gain 12 Block. Return 4 damage. !OTHER!'
    assert result['dynamic_values_unknown']
    assert result['value_scope'] == 'game_card_fields_not_target_prediction'
    assert summary['hand'][0]['raw_description'].startswith('Gain !B!')


def test_negative_or_unverified_native_numbers_stay_unknown():
    from slay_jev_spire.catalog import enrich_summary
    catalog = {'cards': {'Test': {'DESCRIPTION': 'Deal !D! damage.'}}}
    for native in ({'damage': 50}, {'source': 'game_card_fields', 'damage': -1},
                   {'source': 'game_card_fields', 'damage': True}):
        card = {'id': 'Test', 'native_values': native}
        assert enrich_summary({'hand': [card]}, catalog)['hand'][0]['description'] == 'Deal !D! damage.'


def test_native_power_and_relic_descriptions_are_not_replaced_by_templates():
    from slay_jev_spire.catalog import enrich_summary
    summary = {'player': {'powers': [{'id': 'Strength', 'amount': -2, 'native_description': 'Attacks deal 2 less damage.'}]},
               'relics': [{'id': 'Pen Nib', 'counter': 9, 'native_description': 'Next attack deals double damage.'}]}
    result = enrich_summary(summary, {'powers': {'Strength': {'DESCRIPTIONS': ['Attacks deal %d damage.']}}})
    assert result['player']['powers'][0]['description'] == 'Attacks deal 2 less damage.'
    assert result['relics'][0]['description'] == 'Next attack deals double damage.'
