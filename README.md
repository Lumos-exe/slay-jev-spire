# Slay Jev Spire

让 Jev 对《杀戮尖塔》一代的 CommunicationMod 状态快照做一次离线动作选择。
程序只显示命令并记录，不连接、启动或操作游戏。

目录职责、共享数据结构、调用流程和每个函数的说明见 [架构说明](docs/architecture.md)。
新增代码前可直接查阅其中的 [未来功能放置位置](docs/architecture.md#6-后续功能应该放在哪里)
和 [现有函数归属与依赖规则](docs/architecture.md#7-现有函数的固定放置位置)。

## 当前实际验证到哪一步

2026-10-03，在 WSL2 / Ubuntu 24.04 / Python 3.12.3 验证：

| 项目 | 状态 |
| --- | --- |
| `.venv` 和依赖安装 | 已完成；Jev SDK 0.7.2、pytest 9.1.1 |
| 官方样本 → 摘要 → 候选 → 模拟选择 → JSONL | 已通过，样本有 6 个候选，模拟选择 `PLAY 1 0` |
| 牌/目标索引、返回值校验 | 自动化测试已通过 |
| 模拟模式不联网 | 已通过：独立进程禁止 socket 操作及 SDK 导入，移除两个密钥仍完整运行 |
| Jev SDK 请求构造、响应解析 | 本地伪造 HTTP 响应验证通过，不代表真实 API 已验证 |
| Jev 真实请求 | **尚未验证**：当前执行进程没有 `TYPESAFE_API_KEY`，未向 Jev 发出真实请求 |
| 游戏命令执行、Windows → `wsl.exe` → Python 标准输入输出 | 尚未验证 |
| DeepSeek、整局运行、复盘与策略评估 | 尚未实现 |

真实选择成功也只证明离线接口链路可用，不证明命令已在游戏执行或策略有效。

## 安装与运行

### Windows 原生开发

后续开发使用 Windows 本机的 VS Code、Python 和 PowerShell。
按 [Windows 迁移指南](docs/windows.md) 克隆仓库、重新创建虚拟环境并设置密钥。
Windows 本机安装和运行尚未实测；下面的 WSL 说明保留作为已有环境的使用方法。

### 已有 WSL 环境

在 VS Code 的 **WSL 终端**，进入本项目目录。已创建的环境可直接激活：

```bash
source .venv/bin/activate
python main.py --mode mock
```

重新安装时（无需 Windows Python、Docker 或系统级 pip 安装）：

```bash
python3 --version
python3 -m venv --without-pip .venv
python3 -m pip --python .venv/bin/python install pip
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

这里使用现有系统 pip 引导虚拟环境，适用于当前缺少 `ensurepip` 的 WSL。
安装依赖需要联网；安装之后模拟 CLI 只使用 Python 标准库，不需要密钥或网络。
VS Code 中执行 **Python: Select Interpreter**，选择本项目 `.venv/bin/python`。

### 模拟一次

```bash
python main.py --mode mock
# 也可以指定文件：
python main.py --mode mock --state samples/communication_mod_combat.json --log logs/mock.jsonl
```

输出包含精简局面、候选 ID、实际命令、展示说明、选择及记录路径。
默认模式是 `mock`，固定选第一个候选，仅验证程序链路，不代表任何智能策略。
官方样本的候选命令如下：

```text
PLAY 1 0
PLAY 2 0
PLAY 3
PLAY 4
PLAY 5 0
END
```

### Jev 真实选择一次

在运行程序的同一个 WSL 终端用 Bash 隐藏输入密钥，避免密钥进入命令历史：

```bash
read -r -s -p 'TYPESAFE_API_KEY: ' TYPESAFE_API_KEY
printf '\n'
export TYPESAFE_API_KEY
python main.py --mode jev --log logs/jev.jsonl
unset TYPESAFE_API_KEY
```

无需将密钥粘贴进聊天、代码或文件；不要用 `echo` 输出密钥。已经 export 的密钥无需再次输入。
在另一个终端 export 不会更新已运行进程的环境。

每次 Jev 运行使用 `jev-latest` 发出一次 `Choice` 请求，HTTP 操作超时 30 秒，SDK 自动重试关闭。
服务地址固定为 `https://api.typesafe.ai`，不读取环境中的自定义地址。
候选 ID 必须精确匹配；未知、缺失或错误类型的返回不会转为命令，也不会静默回退至模拟。
API 失败时给出简短错误，不保存原始异常或成功记录。密钥缺失也明确报错。
DeepSeek 尚未接入，不需要设置 `DEEPSEEK_API_KEY`。

## 样本、索引和覆盖范围

`samples/communication_mod_combat.json` 来自 [CommunicationMod 官方 README](https://github.com/ForgottenArbiter/CommunicationMod/blob/master/README.md) 的 JSON 示例（2026-10-03 下载，仅重新排版）。
保留完整嵌套结构和字段；**不是从你的游戏现场采集的状态**。
样本敌人的 `intent` 是 `DEBUG`，`move_adjusted_damage` 是 `-1`；摘要保留意图，并将未知伤害表示为 `null`，不猜成 0 或基础伤害。

当前只接受以下明确覆盖的状态，超出范围就拒绝：

- `in_game`、`ready_for_command` 为真；铁甲战士，`COMBAT`、`WAITING_ON_USER` 阶段；`screen_type=NONE`，无打开界面、无 limbo 中的牌。
- 玩家、敌人没有 powers，玩家没有充能球；遗物仅允许燃烧之血和涅奥的悲恸，也可没有遗物。
- 手牌仅有未升级的 `Strike_R`、`Defend_R`、`Bash`，目标类型正确，没有被修改的消耗/虚无属性；不支持 X 费或负费用牌。
- 根据 `available_commands`、牌的 `is_playable`、当前费用与能量生成候选。不重建完整游戏规则，也不执行伤害或回合模拟。

牌的 `hand_index` 是原始 `hand` 数组的 **0 基位置**，`PLAY` 的牌参数是它加一；目标使用原始 `monsters` 数组的 **0 基位置**。
先保留位置，再过滤牌和死亡、`is_gone`、`half_dead` 目标，绝不重新编号。
例如手牌第 2 张不可用时，第 3 张仍是 `PLAY 3`；怪物 1 不可选时，怪物 2 仍是目标 `2`。
重复牌用原始位置与 UUID 区分；无目标牌不追加目标参数；只有 `end` 可用时才生成 `END`。
候选是这一受限快照下的候选，未经过游戏端执行验证。

## 复查记录

默认追加到 `logs/decisions.jsonl`，每次成功选择占一行 UTF-8 JSON：

- `timestamp`（UTC）、`mode`。
- `raw_state`：输入的完整状态；`summary`：提供给选择器的精简摘要。
- `instructions`：Jev 选择指令，模拟模式也保留同一份指令供复查。
- `candidates`：每项包含 `id`、`command`、`description`、`hand_index`、`card_uuid`、`target_index`。
- `decision`：选中的原候选、请求模型、返回模型和可用置信度；模拟的模型与置信度字段为 `null`。

不会记录请求头、密钥、原始 HTTP 响应或完整异常；已配置密钥若意外出现在文本中会脱敏。
Jev 仅收到摘要及候选描述，不会收到记录中的完整地图或牌堆顺序。
记录与密钥文件都在 `.gitignore` 中。复查最后一条：

```bash
tail -n 1 logs/decisions.jsonl | python -m json.tool
python -m pytest -q
```

记录文件无法写入时命令返回失败；若真实请求已发送，修复路径后再次运行会产生新的 API 调用。

## 模块边界和下一步

| 模块 | 职责 |
| --- | --- |
| `models.py` | 明确定义候选、选择结果和记录的共享类型 |
| `state.py` | 校验 CommunicationMod 状态并提取摘要；委托动作模块完成准备 |
| `actions.py` | 根据已校验摘要生成候选 ID、命令和说明，保留原始索引 |
| `selectors.py` | 模拟/Jev 选择与返回值校验 |
| `records.py` | 构造记录、脱敏和追加 JSONL |
| `cli.py` | 读取样本、协调流程、终端展示和错误提示 |
| `main.py` | 启动入口与退出码 |

各业务函数附有中文说明；完整函数表和后续扩展位置见 [架构说明](docs/architecture.md)。

下一小步接入 DeepSeek 分析；实时游戏接入单独增加传输层。后续在 Windows 原生开发，届时需安装 ModTheSpire、BaseMod、CommunicationMod，并实测用 Windows 虚拟环境的 Python 启动协议进程、`ready` 握手、逐行 JSON 与刷新行为。此前设想的 `wsl.exe` 转接不再是默认路线。
当前 CLI 的 stdout 是人类可读输出，**不能直接作为 CommunicationMod 的协议进程使用**。

未来用固定种子对照局、独立评估局和版本化策略检验改进；调用模型 API 本身不会让模型自动学习。
Jev 接口参考：[Python SDK](https://docs.typesafe.ai/sdk/python)、[快速入门](https://docs.typesafe.ai/introduction/quickstart)。
