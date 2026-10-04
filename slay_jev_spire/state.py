"""CommunicationMod 状态适配：校验范围、提取摘要、交给动作模块。

所有函数只操作内存数据；不读取文件，不选择或执行动作。
"""

from .actions import generate_actions
from .models import Action


class UnsupportedState(ValueError):
    """输入无效、状态超出覆盖范围或没有支持的候选动作。"""


CARDS = {
    'Strike_R': (True, '造成 6 点伤害'),
    'Defend_R': (False, '获得 5 点格挡'),
    'Bash': (True, '造成 8 点伤害，施加 2 层易伤'),
}
RELICS = {'Burning Blood', 'NeowsBlessing'}
COMMON_POWERS = {'Strength', 'Dexterity', 'Weakened', 'Vulnerable', 'Frail'}
UPGRADED_EFFECTS = {
    'Strike_R': '基础造成 9 点伤害',
    'Defend_R': '基础获得 8 点格挡',
    'Bash': '基础造成 10 点伤害，施加 3 层易伤',
}


def _require(condition: bool, message: str) -> None:
    """校验一个条件，失败时抛出不包含原始输入的状态错误。"""
    if not condition:
        raise UnsupportedState(message)


def _integer(value: object, minimum: int | None = 0) -> int:
    """读取整数并校验下限；拒绝布尔值，minimum=None 时允许负数。"""
    _require(type(value) is int and (minimum is None or value >= minimum),
             '状态中的数值字段缺失或不受支持。')
    return value


def _string(value: object) -> str:
    """读取非空字符串；无效值统一转换成安全的状态错误。"""
    _require(isinstance(value, str) and bool(value), '状态中的文字字段缺失或无效。')
    return value


def prepare_state(raw: dict) -> tuple[dict, list[Action]]:
    """公共入口：原始协议 JSON → 精简摘要、候选列表。

    校验范围后调用独立的 generate_actions。字段缺失、类型错误
    和空候选统一抛出 UnsupportedState；不修改原始状态。
    """
    try:
        combat, commands = _validate_context(raw)
        summary = {
            'turn': _integer(combat['turn'], 1),
            'player': _summarize_player(combat['player']),
            'hand': _summarize_hand(combat['hand']),
            'enemies': _summarize_enemies(combat['monsters']),
        }
        actions = generate_actions(summary, commands)
        _require(bool(actions), '当前支持范围内没有可选命令。')
        return summary, actions
    except (KeyError, TypeError, IndexError, AttributeError):
        raise UnsupportedState('状态 JSON 缺少必要字段或字段类型错误。') from None


def _validate_context(raw: dict) -> tuple[dict, list[str]]:
    """校验角色、战斗阶段、界面与遗物；返回战斗数据和可用命令。"""
    _require(raw['in_game'] is True and raw['ready_for_command'] is True,
             '仅支持游戏内已准备好接收命令的状态。')
    game = raw['game_state']
    _require(game['class'] == 'IRONCLAD', '仅支持铁甲战士。')
    _require(game['room_phase'] == 'COMBAT' and game['action_phase'] == 'WAITING_ON_USER',
             '仅支持等待玩家操作的稳定战斗阶段。')
    _require(game['screen_type'] == 'NONE' and game['is_screen_up'] is False,
             '不支持选择界面或其他打开的界面。')
    commands = raw['available_commands']
    _require(isinstance(commands, list) and all(isinstance(c, str) for c in commands),
             'available_commands 必须是命令列表。')
    _require(isinstance(game['relics'], list), '遗物字段必须是列表。')
    _require(all(r['id'] in RELICS for r in game['relics']),
             '仅支持燃烧之血和涅奥的悲恸；其他遗物效果尚未覆盖。')
    combat = game['combat_state']
    _require(combat['limbo'] == [], '不支持正在结算的牌。')
    return combat, commands


def _summarize_player(player: dict) -> dict:
    """校验存活、无充能球的玩家，提取数值与已覆盖的能力。"""
    _require(player['orbs'] == [], '不支持充能球。')
    summary = {
        key: _integer(player[key]) for key in ('current_hp', 'max_hp', 'block', 'energy')
    }
    _require(player['current_hp'] > 0, '不支持玩家已死亡的状态。')
    summary['powers'] = _summarize_powers(player['powers'], COMMON_POWERS)
    return summary


def _summarize_powers(powers: list[dict], allowed: set[str]) -> list[dict]:
    """保留已覆盖能力的名称、ID 和层数；力量/敏捷可为负值。"""
    _require(isinstance(powers, list), 'powers 必须是列表。')
    result = []
    for power in powers:
        power_id = _string(power['id'])
        _require(power_id in allowed, '当前能力尚未覆盖。')
        result.append({'id': power_id, 'name': _string(power['name']),
                       'amount': _integer(power['amount'], None if power_id in {'Strength', 'Dexterity'} else 0)})
    return result


def _summarize_enemies(monsters: list[dict]) -> list[dict]:
    """校验怪物能力，保留原始位置；负数伤害/攻击次数表示未知。"""
    _require(isinstance(monsters, list), '怪物必须是列表。')
    enemies = []
    for index, monster in enumerate(monsters):
        powers = _summarize_powers(monster['powers'], COMMON_POWERS | {'Curl Up', 'Ritual'})
        _require(type(monster['is_gone']) is bool and type(monster['half_dead']) is bool,
                 '怪物存活标志必须是布尔值。')
        hp = _integer(monster['current_hp'])
        damage = _integer(monster['move_adjusted_damage'], None)
        hits = _integer(monster['move_hits'], None)
        enemies.append({
            'target_index': index,
            'name': _string(monster['name']),
            'current_hp': hp,
            'max_hp': _integer(monster['max_hp']),
            'block': _integer(monster['block']),
            'is_gone': monster['is_gone'],
            'half_dead': monster['half_dead'],
            'intent': _string(monster['intent']),
            'move_adjusted_damage': damage if damage >= 0 else None,
            'move_hits': hits if hits >= 0 else None,
            'powers': powers,
        })
    _require(any(e['current_hp'] > 0 and not e['is_gone'] and not e['half_dead'] for e in enemies),
             '不支持没有存活目标的战斗状态。')
    return enemies


def _summarize_hand(hand: list[dict]) -> list[dict]:
    """校验基础牌及一次升级，保留当前费用、基础效果、UUID 与位置。"""
    _require(isinstance(hand, list), '手牌必须是列表。')
    cards = []
    for index, card in enumerate(hand):
        card_id = card['id']
        _require(isinstance(card_id, str) and card_id in CARDS,
                 '仅支持 Strike_R、Defend_R 和 Bash 手牌。')
        _require(type(card['upgrades']) is int and card['upgrades'] in (0, 1),
                 '基础牌仅支持未升级或升级一次。')
        has_target, effect = CARDS[card_id]
        effect = UPGRADED_EFFECTS[card_id] if card['upgrades'] else '基础' + effect
        effect += '（实际效果受双方能力影响）'
        _require(card['has_target'] is has_target, '牌的目标类型不符合已覆盖规则。')
        _require(card['exhausts'] is False and card['ethereal'] is False,
                 '不支持修改了消耗或虚无属性的牌。')
        _require(type(card['is_playable']) is bool, '牌的可用标志必须是布尔值。')
        cost = _integer(card['cost'])
        uuid = _string(card['uuid'])
        name = _string(card['name'])
        cards.append({
            'hand_index': index, 'play_index': index + 1, 'card_uuid': uuid,
            'id': card_id, 'name': name, 'cost': cost,
            'is_playable': card['is_playable'], 'has_target': has_target, 'effect': effect,
            'upgrades': card['upgrades'],
        })
    return cards
