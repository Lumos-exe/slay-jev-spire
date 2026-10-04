# Slay Jev Spire

Windows + Steam《杀戮尖塔》一代，需要已安装 ModTheSpire、BaseMod、CommunicationMod 和 JDK。

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe main.py configure
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_jev_state.ps1 -Install
```

先启动 Steam，正常退出已有游戏，再运行：

```powershell
# 启动后在游戏主菜单继续存档
.venv\Scripts\python.exe main.py play
# 指定种子开始新局，第一场战斗后停止；默认 beam 宽度 32
.venv\Scripts\python.exe main.py play --new --combat-only --seed 12345 --beam-width 32
.venv\Scripts\python.exe main.py pause
.venv\Scripts\python.exe main.py resume --budget 100
.venv\Scripts\python.exe main.py status
.venv\Scripts\python.exe main.py report --expected 10
.venv\Scripts\python.exe main.py review
```

密钥使用当前 Windows 用户的 DPAPI 加密保存，或设置 `TYPESAFE_API_KEY` 环境变量。
`JEV_MODEL` 可固定模型；每次请求记录服务端实际返回的版本。

离线回放与测试：

```powershell
.venv\Scripts\python.exe main.py replay --state samples/quality_bash.json --mode mock
.venv\Scripts\python.exe main.py replay --state samples/quality_bash.json --mode jev --log logs/judge.jsonl
.venv\Scripts\python.exe -m pytest -q
# 在 Windows 桌面终端运行；先关闭游戏。新旧版本各跑 10 个相同种子。
.venv\Scripts\python.exe main.py benchmark --count 10
```

CommunicationMod 配置由启动脚本生成。协议入口是 `capture_game.py`，也可使用
`main.py agent --combat jev`；这些入口由游戏启动，不能把普通终端输出当协议输入。

运行事件和概率分布保存在 `logs/live/runs.jsonl`，状态快照保存在 `states.jsonl`。
`review` 为最近一局生成 JSON 复盘包，也可用 `--run-id` 或 `--log` 指定日志。
复盘包包含真实节点覆盖、未查看的卡牌奖励、未领取遗物、牌的使用情况、预测偏差及组件版本。
修改组件后先运行对应回归，再用相同条件重跑；单次输赢不直接证明改动有效。
报告中的中断不算胜利；未跑满 10 场会显示缺失数量。确定牌序逐步校验执行，抽牌、随机结果
及明确标记的未建模效果会产生观测点。真实模型概率及全卡池结算须以实际验证结果为准。

基准运行独立保存到 `logs/benchmarks/<时间>/manifest.json`。基准专用 JVM 开关在第 1 层战斗前
固定 80 血、初始牌组、燃烧之血和空药水栏；普通游戏不启用。运行前备份存档与偏好，结束时恢复。
基准跳过涅奥奖励并开启游戏快速模式，两版使用相同条件；这些改动只在基准 JVM 开关下生效。
