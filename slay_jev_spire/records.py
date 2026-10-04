"""构造与追加单步记录，并提供终端和 JSONL 共用的密钥脱敏。"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from .models import Action, Decision, DecisionRecord




def safe_text(text: str) -> str:
    """替换文本中的已配置密钥及其 JSON 转义形式；不修改环境。"""
    secrets = set()
    for variable in ("TYPESAFE_API_KEY", "DEEPSEEK_API_KEY"):
        secret = os.environ.get(variable, "").strip()
        if secret:
            secrets.update((secret, json.dumps(secret, ensure_ascii=False)[1:-1]))
    # 先替换长密钥，避免一个密钥恰好包含另一个时只被部分遮盖。
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def build_record(
    raw_state: dict,
    summary: dict,
    candidates: list[Action],
    decision: Decision,
    mode: str,
    instructions: str,
) -> DecisionRecord:
    """组合单步输入输出并添加 UTC 时间；不写文件、不拷贝或修改输入。"""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(), "mode": mode,
        "raw_state": raw_state, "summary": summary, "instructions": instructions,
        "candidates": candidates, "decision": decision,
    }


def append_record(path: Path, record: DecisionRecord) -> None:
    """创建父目录并追加一行脱敏 JSON；序列化或文件错误由调用者处理。"""
    line = safe_text(json.dumps(record, ensure_ascii=False, allow_nan=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")



def run_metrics(rows):
    requests = {r['step_id']: r for r in rows if r.get('status') == 'request_started'}
    decisions = {r['step_id'] for r in rows if r.get('status') == 'decision' and r['step_id'] in requests}
    failed = {r['step_id'] for r in rows if r.get('status') == 'stopped' and r.get('reason') == 'selection_error'} & requests.keys()
    seen = set()
    duplicates = 0
    for r in requests.values():
        summary = {k: v for k, v in r.get('summary', {}).items() if k not in {'decision_context', 'experience_context'}}
        key = json.dumps([summary, r.get('candidates', [])], sort_keys=True, ensure_ascii=False)
        duplicates += key in seen
        seen.add(key)
    return {'api_requests': len(requests), 'valid_decisions': len(decisions),
            'confirmed_actions': len({r['step_id'] for r in rows if r.get('status') == 'action_confirmed'}),
            'duplicate_requests': duplicates, 'failed_requests': len(failed),
            'pending_requests': len(requests.keys() - decisions - failed)}


def battle_metrics(rows, expected=10):
    """Report all completed battles, with deaths zeroed and interruptions visible."""
    battles = {}
    for row in rows:
        if row.get('status') == 'battle_complete':
            battles[(row.get('run_id'), str(row.get('battle_id')))] = row
    results = [r['result'] for r in battles.values()]
    wins = sum(r['victory'] is True for r in results)
    hp = sum(r.get('end_hp', 0) if r['victory'] else 0 for r in results)
    stops = [r for r in rows if r.get('status') == 'stopped' and r.get('reason') not in {'battle_finished','game_over'}]
    decisions = [r for r in rows if r.get('status') == 'plan_selected']
    return dict(expected_battles=expected, completed_battles=len(results), wins=wins,
                win_rate_completed=wins / len(results) if results else None,
                win_rate_scheduled=wins / expected if expected else None,
                mean_remaining_hp=hp / len(results) if results else None,
                incomplete=max(0, expected-len(results)), technical_stops=[r.get('reason') for r in stops],
                api_requests=sum(r.get('status') == 'request_started' for r in rows),
                mean_confidence=sum(r['decision']['confidence'] for r in decisions if r['decision'].get('confidence') is not None) / len(decisions) if decisions and all(r['decision'].get('confidence') is not None for r in decisions) else None,
                battles=[dict(run_id=r.get('run_id'), battle_id=r.get('battle_id'), **r['result']) for r in battles.values()])






def _cell(value) -> str:
    return str(value if value is not None else '—').replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def _game(raw) -> dict:
    return raw.get('game_state', {}) if isinstance(raw, dict) else {}


def _delta(before, after, key):
    a, b = before.get(key), after.get(key)
    return f'{b - a:+d}' if type(a) is int and type(b) is int else '—'


def render_run_report(rows: list[dict], run_id: str) -> str:
    """只汇总指定运行的证据，未确认的命令和中断不会写成成功。"""
    events = [row for row in rows if row.get('run_id') == run_id]
    if not events:
        raise ValueError('找不到指定运行的记录。')
    lifecycle = next((r for r in reversed(events) if r.get('status') in {'stopped', 'complete', 'resumed'}), None)
    terminal = lifecycle if lifecycle and lifecycle['status'] != 'resumed' else None
    outcome = '进行中；未确认整局结束'
    if terminal:
        game = _game(terminal.get('after'))
        result = game.get('screen_state', {})
        if terminal['status'] == 'complete' and game.get('screen_type') == 'GAME_OVER' and type(result.get('victory')) is bool:
            outcome = ('胜利' if result['victory'] else '死亡') + '；分数 ' + _cell(result.get('score'))
        elif terminal['status'] == 'stopped':
            outcome = '中断；原因 ' + _cell(terminal.get('reason'))
        else:
            outcome = '未确认整局结束'
    mode = next((r.get('mode') for r in events if r.get('mode')), '未知')
    metrics = run_metrics(events)
    lines = ['# 对局决策记录', '', f'运行：`{_cell(run_id)}`', '', f'选择模式：{_cell(mode)}', '', f'结果：{outcome}', '',
             '下表记录观察到的状态变化。血量、金币变化属于本次动作到确认之间的观测，不代表已证明因果或策略优劣。', '']
    lines += [f"请求尝试 {metrics['api_requests']}；合法选择 {metrics['valid_decisions']}；已确认动作 {metrics['confirmed_actions']}；失败请求 {metrics['failed_requests']}；重复局面请求 {metrics['duplicate_requests']}；无返回记录 {metrics['pending_requests']}。", '',
              '重复局面需结合动作判断是否浪费；请求尝试数不是服务商账单或 token 使用量。', '']
    decisions = [r for r in events if r.get('status') == 'decision']
    if not decisions:
        lines.append('尚无决策记录。')
    else:
        lines += ['| 步骤 | 楼层 / 界面 | 选择与命令 | 置信度 | 执行状态 | 血量变化 | 金币变化 | 结果证据 |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- |']
        by_step = {}
        for event in events:
            by_step.setdefault(event.get('step_id'), []).append(event)
        for row in decisions:
            step = row.get('step_id')
            following = by_step.get(step, [])
            confirmation = next((r for r in following if r.get('status') == 'action_confirmed'), None)
            sent = any(r.get('status') == 'command_sent' for r in following)
            status = '已确认' if confirmation else ('已发送，未确认' if sent else '未发送')
            before = _game(row.get('before'))
            after = _game(confirmation.get('after')) if confirmation else {}
            decision = row.get('decision', {})
            action = decision.get('action', {})
            values = [step, f"{before.get('floor', '—')} / {before.get('screen_type', '—')}",
                      f"{action.get('description', '—')} ({action.get('command', '—')})",
                      decision.get('confidence'), status, _delta(before, after, 'current_hp'),
                      _delta(before, after, 'gold'), confirmation.get('evidence') if confirmation else None]
            lines.append('| ' + ' | '.join(_cell(v) for v in values) + ' |')
    return safe_text('\n'.join(lines) + '\n')
