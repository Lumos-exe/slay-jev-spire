# Windows 实时状态采集

2026-10-04 已增加 CommunicationMod 专用入口 `capture_game.py`。
默认入口只发送 `ready` 和一次 `STATE`，保存游戏推送的状态，不调用模型、不执行出牌。
可选 `--execute-once mock` 或 `--execute-once jev` 在首次受支持的稳定战斗状态
执行一个候选，随后仅采集。
协议来源：[CommunicationMod 官方文档](https://github.com/ForgottenArbiter/CommunicationMod)。

## 本机配置

游戏目录：`C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire`。
Workshop 目录：`C:\Program Files (x86)\Steam\steamapps\workshop\content\646570`。
已找到 BaseMod 和 CommunicationMod 1.2.1，ModTheSpire 的默认列表包含这两个 Mod。

在项目 PowerShell 中执行配置脚本：

```powershell
& .\tools\setup_communication_mod.ps1
```

脚本先将原配置备份到 `logs/config-backups/`，保留其他配置，设置 Windows 虚拟环境
Python 的绝对路径及 `runAtGameStart=true`。配置位于
`%LOCALAPPDATA%\ModTheSpire\CommunicationMod\config.properties`。
CommunicationMod 按空白拆分参数，所以项目与解释器路径不能包含空格；Java Properties 中
冒号和反斜杠必须转义，脚本会处理这些字符。

配置后正常退出并通过 Steam 的 Mod 模式重新启动游戏，保持 BaseMod 和 CommunicationMod 勾选。
进入主菜单或对局后，查看项目下的：

- `logs/live/latest_state.json`：最近一次状态或 Mod 错误消息。
- `logs/live/states.jsonl`：带 UTC 时间的完整状态，跨重启追加。

这些文件在项目目录生成，与游戏启动时的工作目录无关。
游戏手动操作并非每次都会触发状态推送；需要刷新时可以在 CommunicationMod 设置面板
使用 `(Re)start external process`，程序会再请求一次 `STATE`。
退出游戏会关闭采集管道。初始化或 JSON 解析出错时程序退出，错误写入游戏目录下
`communication_mod_errors.log`，不会将诊断文字写入协议 stdout。

本机游戏自带 Java 8 的 `file.encoding` 实测为 GBK，Mod 用 Java 默认编码发送
JSON 字节。启动配置已加入 `--input-encoding gbk`，仅协议输入使用 GBK，
输出日志继续使用 UTF-8。切换英文不是必需的，也无需更换 CommunicationMod。
若以后更换 Java 并改用 UTF-8，应将该参数同步改成 `--input-encoding utf-8`。

恢复配置时，关闭游戏，将 `logs/config-backups/` 中对应备份复制回原配置路径。

## 验证边界

本地自动化测试已验证管道握手即时刷新、不同工作目录启动、多个状态和中文保存、
错误消息保存、无效 JSON 拒绝及输出目录不可写时不握手。
2026-10-04 用户重启 Mod 模式游戏后，已实测收到两条真实状态：加载期间
`ready_for_command=false`，进入主菜单后 `ready_for_command=true`，
`in_game=false`，`available_commands=["start", "state"]`。这确认游戏启动
Windows Python、握手及状态采集成功，记录位于 `logs/live/`。
首次进入中文对局时发现 UTF-8/GBK 不匹配，采集进程退出；已修复并增加真实
GBK 字节输入的回归测试已通过；之后已采集到真实中文战斗，支持蜷身并生成 11 个候选。
单步模拟执行已实现，45 项测试通过；现场 `PLAY 1 0` 已验证：能量 3→2，
手牌 5→4，出牌 UUID 在弃牌堆，目标生命 12→6，蜷身触发获得 5 格挡。
单次验证后启动配置已恢复默认只采集模式，无需为此再次重启。
离线 `main.py` 保持原有行为。实时 Jev 单步入口已实现，本地测试、真实 API
请求与游戏执行均通过。DeepSeek 分析仍未实现。

## 单次模拟出牌验证

配置脚本 `tools/setup_communication_mod.ps1 -ExecuteOnce` 可启用此入口。重新启动
Mod 模式游戏后，在首次支持的战斗状态执行第一个候选，每个进程最多一次，
不会连续出牌。重新启动该模式的进程会重新获得一次执行机会，所以完成验证后
应不带 `-ExecuteOnce` 再运行配置脚本，恢复仅采集配置。

`logs/live/decisions.jsonl` 在发送前保存决策；`executions.jsonl` 记录 `sent` 及
下一条稳定响应 `response_received` 或 `error`。收到响应并不单独证明出牌成功，
应对比前后手牌 UUID、能量与目标状态；游戏初始推送和 STATE 响应可能重复。
记录失败会退出，不会重试游戏命令。未支持的状态继续采集，不发送动作。

## Jev 实时单步决策

运行时不依赖 1Password。密钥可以来自 `TYPESAFE_API_KEY` 环境变量，或使用
本机配置入口隐藏输入并保存：

```powershell
.\.venv\Scripts\python.exe -X utf8 configure_key.py
```

当前开发版保存到 `config/jev-key.dpapi`，使用 Windows 当前用户的 DPAPI 加密，
临时文件也只包含密文，并已排除 Git。启动时解密到进程环境，优先使用已有的
`TYPESAFE_API_KEY`。Windows 加密文件通常不能跨电脑或 Windows 用户复用，迁移时
需要重新输入密钥。发布版可复用此密钥接口，并把配置目录放到用户应用数据目录。
参考：[Microsoft DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)。

```powershell
& .\tools\setup_communication_mod.ps1 -ExecuteOnce -Mode jev
```

重启 Mod 模式游戏后，在第一个支持的稳定战斗状态，从环境或本机加密配置读取
密钥。读取失败会退出，密钥不进入协议 stdout 或记录，不需要保险库授权窗口。

首个支持的战斗状态到达时先发出 STATE 刷新；若怪物意图仍为加载占位 DEBUG，
每 0.2 秒请求一次 STATE，最多等待 15 秒，超时不调用模型。
Jev 使用现有 SDK 向 `https://api.typesafe.ai/v1/systemone` 发送一次摘要与候选，
不发送完整地图、牌堆顺序或原始快照。SDK 请求超时 30 秒，无自动重试。
成功返回后保存决策，再发出 `STATE`。下一条状态必须与决策输入完整相同，
否则记录 `cancelled_state_changed`，不执行、不重新请求；验证窗口中请勿手动出牌。
Mod 协议没有请求 ID，收到后续响应还需要结合手牌、能量及敌人变化确认执行。

API 失败或无效候选退出，不回退到模拟。每个进程最多一次 Jev 请求和一次游戏动作。
主菜单和未支持状态仅采集，不调用 Jev。完成测试后运行不带参数的配置脚本恢复
仅采集；处于单步模式的进程在重启后会重新获得一次执行机会。

本地集成测试使用真实 SDK 和本地 HTTP transport，覆盖返回模型、精确候选映射、
状态变化取消、401 和无效候选，并实测 DPAPI 加密/解密及损坏配置拒绝。
当前 51 项测试通过。2026-10-04 真实请求返回 `jev-1.13.0`，选择 `PLAY 5 0`，
最初返回后 STATE 检查发现怪物意图由 DEBUG 改为 ATTACK，正确取消执行。
增加请求前刷新及等待 DEBUG 意图更新的条件后，2026-10-04 再次现场验证成功：
模型 `jev-1.13.0` 选择 `PLAY 5 0`，置信度 0.55，能量 3→1，手牌 5→4，
痛击 UUID 进入弃牌堆，目标生命 12→4、蜷身获得 5 格挡，并获得 2 层易伤。
测试完成后已恢复只采集配置，无需再次重启。之后已扩展常见能力和升级基础牌，
并实测自动完成一场战斗，见 [战斗循环指南](combat-loop.md)。整局流程仍未实现。
