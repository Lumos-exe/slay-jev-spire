"""Optional local game text; no assets are persisted or values simulated."""
from copy import deepcopy
import json
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile


def load_catalog(game_jar: Path | None = None) -> dict:
    result = {'cards': {}, 'powers': {}, 'relics': {}}
    if game_jar is None:
        return result
    try:
        with ZipFile(game_jar) as jar:
            for kind in result:
                try:
                    value = json.loads(jar.read(f'localization/eng/{kind}.json').decode('utf-8-sig'))
                    if isinstance(value, dict):
                        result[kind] = {key: entry for key, entry in value.items() if isinstance(key, str) and isinstance(entry, dict)}
                except (KeyError, UnicodeError, ValueError):
                    pass
    except (OSError, BadZipFile, TypeError):
        pass
    return result


def enrich_summary(summary: dict, catalog: dict) -> dict:
    """Recursively annotate identifiable metadata, keeping templates unresolved."""
    result = deepcopy(summary)

    def visit(value, category=None):
        if isinstance(value, list):
            for item in value:
                visit(item, category)
        elif isinstance(value, dict):
            identifier = value.get('id')
            if isinstance(identifier, str) and category in ('cards', 'powers', 'relics'):
                entry = catalog.get(category, {}).get(identifier, {})
                description = entry.get('UPGRADE_DESCRIPTION') if category == 'cards' and type(value.get('upgrades')) is int and value['upgrades'] > 0 else None
                description = description or entry.get('DESCRIPTION') or entry.get('DESCRIPTIONS')
                if isinstance(value.get('native_description'), str) and value['native_description']:
                    description = value['native_description']
                native = value.get('native_values')
                if category == 'cards' and isinstance(native, dict) and native.get('source') == 'game_card_fields':
                    if isinstance(value.get('raw_description'), str) and value['raw_description']:
                        description = value['raw_description']
                    if isinstance(description, str):
                        for token, field in (('!D!', 'damage'), ('!B!', 'block'), ('!M!', 'magic_number')):
                            number = native.get(field)
                            if type(number) is int and number >= 0:
                                description = description.replace(token, str(number))
                    value['value_scope'] = 'game_card_fields_not_target_prediction'
                if isinstance(description, list) and all(isinstance(s, str) for s in description):
                    description = ' '.join(description)
                value['description'] = description if isinstance(description, str) else 'unknown'
                value['dynamic_values_unknown'] = bool(re.search(r'![^!]+!|%(?:\d+\$)?[-+ #0]*\d*(?:\.\d+)?[a-zA-Z]|\{\d+(?:[^}]*)\}', value['description']))
            for key, child in list(value.items()):
                kind = 'powers' if key == 'powers' else 'relics' if key in ('relics', 'relic') else 'cards' if key in ('hand', 'deck', 'cards', 'card', 'draw_pile', 'discard_pile', 'exhaust_pile', 'selected_cards') else category
                visit(child, kind)
    visit(result)
    return result
