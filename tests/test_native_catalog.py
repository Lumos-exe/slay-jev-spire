import json
from slay_jev_spire.native_catalog import NativeCatalogStore
from slay_jev_spire.state import enrich_summary


def test_catalog_is_data_driven_and_live_fields_win(tmp_path):
    path=tmp_path/'catalog.json'
    path.write_text(json.dumps({'schema_version':1,'cards':{'UnknownNewCard':{
        'raw_description':'Base !D! damage','base_cost':3,'base_damage':5,'tags':['NEW_TAG'],
        'native_mechanics':{'overridden_callbacks':['use()']}}},'relics':{}}))
    catalog=NativeCatalogStore(path).refresh()
    assert catalog.lookup('cards','UnknownNewCard')['base_cost']==3
    live={'hand':[{'id':'UnknownNewCard','uuid':'instance','cost':0,'upgrades':0,
        'raw_description':'Current !D! damage','native_values':{'source':'game_card_fields','damage':17}}]}
    enriched=enrich_summary(live,catalog.localization())['hand'][0]
    assert enriched['cost']==0 and enriched['description']=='Current 17 damage'
    assert enriched['tags']==['NEW_TAG'] and enriched['catalog_ref']['version']==catalog.version
    assert 'base_damage' not in enriched  # Prototype values never masquerade as live state.
    assert catalog.lookup('cards','NotYetRegistered') is None


def test_missing_or_updated_catalog_does_not_block_observation(tmp_path):
    path=tmp_path/'catalog.json';store=NativeCatalogStore(path).refresh()
    assert store.version is None
    path.write_text(json.dumps({'schema_version':1,'cards':{'A':{'raw_description':'First'}},'relics':{}}))
    first=store.refresh().version
    path.write_text(json.dumps({'schema_version':1,'cards':{'A':{'raw_description':'Changed, native update'}},'relics':{}}))
    assert store.refresh().version!=first
    assert store.lookup('cards','A')['raw_description']=='Changed, native update'
