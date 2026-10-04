"""显示最近的游戏采集和运行事件，不发 API 请求或游戏命令。"""

from datetime import datetime
import json
from pathlib import Path

from slay_jev_spire.records import safe_text
from slay_jev_spire.run_metrics import run_metrics


ROOT = Path(__file__).resolve().parent
REASONS = {
    'decision_limit': '达到本次请求预算；可用 resume_jev.cmd 继续',
    'unsupported_state': '游戏状态字段或界面尚未支持',
    'paused': '已暂停；可用 resume_jev.cmd 继续',
    'state_changed': '请求期间局面改变，候选已取消',
    'state_timeout': '等待状态或执行结果超时',
    'game_over': '本局已结束',
    'selection_error': '模型选择或请求失败',
    'game_error': '游戏拒绝了命令',
    'decision_loop': '相同局面反复出现；已在下一次 API 请求前停止',
    'no_unvisited_actions': '没有剩余可选动作；已阻止重复选择',
    'action_limit': '达到本局动作上限',
    'time_limit': '达到本局时间上限',
}


def main():
    live = ROOT / 'logs/live'
    print('Jev 最近采集状态（快照不代表进程仍在运行）')
    try:
        path = live / 'latest_state.json'
        raw = json.loads(path.read_text(encoding='utf-8'))
        game = raw.get('game_state', {})
        print('采集时间：', datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds'))
        print('楼层：', game.get('floor', '—'), '界面：', game.get('screen_type', '主菜单'))
        print('生命：', game.get('current_hp', '—'), '/', game.get('max_hp', '—'))
    except (OSError, ValueError, AttributeError):
        print('还没有可读取的游戏快照。')
    last = None
    rows = []
    try:
        with (live / 'runs.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        last = row
                        rows.append(row)
                except ValueError:
                    continue
    except OSError:
        pass
    if last:
        print('运行 ID：', safe_text(str(last.get('run_id', '—'))))
        print('最后事件：', last.get('status'), '时间：', last.get('timestamp'))
        print('请求数：', last.get('calls'), '动作数：', last.get('actions'))
        metrics = run_metrics([r for r in rows if r.get('run_id') == last.get('run_id')])
        print('已确认动作：', metrics['confirmed_actions'], '请求失败：', metrics['failed_requests'])
        print('重复局面请求：', metrics['duplicate_requests'], '无返回记录的请求：', metrics['pending_requests'])
        print('重复局面不一定意味着浪费；无返回记录也可能是中途退出。')
        if last.get('reason'):
            reason = str(last['reason'])
            print('停止原因：', safe_text(REASONS.get(reason, reason)), f'({reason})')
        if last.get('message'):
            print('说明：', safe_text(str(last['message'])))
    else:
        print('还没有新版整局运行记录。')
    print('暂停标志：', '已暂停' if (live / 'pause.flag').exists() else '未设置')
    print('双击 play_jev.cmd 启动；pause_combat.cmd 暂停；resume_jev.cmd 恢复。')
    if (live / 'run-report.md').exists():
        print('决策时间线：', live / 'run-report.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
