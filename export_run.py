"""从已保存的运行事件导出 Markdown 决策时间线。"""

import argparse
import json
from pathlib import Path

from slay_jev_spire.run_report import render_run_report


def main(argv=None):
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, default=root / 'logs/live/runs.jsonl')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, default=root / 'logs/live/run-report.md')
    args = parser.parse_args(argv)
    try:
        rows = []
        with args.log.open(encoding='utf-8') as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('记录必须是 JSON 对象。')
                if row.get('run_id') == args.run_id:
                    rows.append(row)
        report = render_run_report(rows, args.run_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding='utf-8')
    except (OSError, ValueError):
        parser.exit(1, '导出失败：记录缺失、无效，或无法写入报告。\n')
    print(f'已导出：{args.output.resolve()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
