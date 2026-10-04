"""从已校验的摘要生成命令；保留原始索引，不访问文件或网络。"""

from .models import Action


def generate_actions(summary: dict, available_commands: list[str]) -> list[Action]:
    """消费 state.py 的摘要，返回有序候选；无候选时返回空列表。

    只过滤可用性、费用和目标。牌索引加一、目标索引保持零基；
    不修改摘要，也不执行命令。支持范围由状态适配器提前校验。
    """
    targets = [
        enemy for enemy in summary["enemies"]
        if enemy["current_hp"] > 0 and not enemy["is_gone"] and not enemy["half_dead"]
    ]
    actions: list[Action] = []
    if "play" in available_commands:
        for card in summary["hand"]:
            if not card["is_playable"] or card["cost"] > summary["player"]["energy"]:
                continue
            for enemy in targets if card["has_target"] else [None]:
                play_index = card["play_index"]
                command = f"PLAY {play_index}"
                action_id = f"play_{play_index}"
                description = f"手牌 {play_index}：{card['name']}（{card['cost']} 能量；{card['effect']}）"
                target_index = None
                if enemy is not None:
                    target_index = enemy["target_index"]
                    command += f" {target_index}"
                    action_id += f"_{target_index}"
                    description += f" → 怪物 {target_index}：{enemy['name']}"
                    for power in enemy.get('powers', []):
                        if power['id'] == 'Curl Up':
                            description += f"（蜷身：受到攻击后获得 {power['amount']} 格挡，触发一次）"
                actions.append({
                    "id": action_id, "command": command, "description": description,
                    "hand_index": card["hand_index"], "card_uuid": card["card_uuid"],
                    "target_index": target_index,
                })
    if "end" in available_commands:
        actions.append({
            "id": "end", "command": "END", "description": "结束回合",
            "hand_index": None, "card_uuid": None, "target_index": None,
        })
    return actions
