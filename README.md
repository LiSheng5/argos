# ArgOS

> 宇树 Go2 机器狗的 AI 大脑 —— 一句话指挥，安全闸守护。
> An AI brain for Unitree robot dogs: one sentence in, guarded motion out.

ArgOS 把"游戏 NPC 大脑"移植到了机器狗身上：文本指令 → 编译 → 落账 → 安全闸 → 执行 → 到点记账 → 记忆回流。大脑与执行器分离，真机到手只需换执行器，大脑一行不改。

**诚实声明：**
- ✅ 大脑层（编译/落账/安全/记忆/服务）在物理仿真里完整验证，148 项测试通过 + 3 项跳过（裸环境实测 2026-09-10；DDS 三例需宇树上游 SDK，装好后 151 全绿）
- ✅ 真机执行器（高层 SportClient + 闭环控制器 + 断链看门狗）代码与单测就绪
- ✅ Web Console（观察 + 控制层）可用，只观测与下发指令、不决策
- ❌ **尚未在真机上运行**——真机联调清单见 `文档/真机安全清单.md`
- 部分代码与文档由 AI 工具辅助编写，实测数据全部来自真实运行

## 系统长什么样

```
用户说话 / OpenClaw
      ↓
  server.py（127.0.0.1:8766）
      ↓
  RobotBrain：编译 → 落账口 → 记忆/反思
      ↓
  RobotBackend：过 SafetyGate（白名单/禁触/急停/电量/边界）
      ↓
  ┌─────────┬──────────┬──────────┬──────────────┐
  │  stub   │  mujoco  │   dds    │ real（高层） │
  │ 瞬移    │ 有物理   │ 会真走   │ SportClient  │
  │ 跑测试  │ 不会走   │ 只走直线 │ 等真机验证   │
  └─────────┴──────────┴──────────┴──────────────┘
```

核心设计哲学：**LLM 只提议、代码决定执行**——所有动作必须命中运动原语白名单并过安全闸，LLM 零关节/零文件直控。

## 性格（可选 LLM）

无 key 时狗按规则话术回话；配好 key 后，回复与反思自动带上性格（`argos/persona.json` 直接编辑）：

```bash
set ARGOS_API_KEY=sk-xxx        # 或放仓库根 api_key.txt（已 gitignore）
python -m argos.server --executor dds
```

| 层 | LLM 化 | 规则兜底 |
|---|---|---|
| 接单/拒绝/听不懂的回复 | 带 persona 性格 | 原版话术 |
| 反思归纳 | 按 persona 风格归纳 | 规则事实摘要 |
| 编译/落账/安全闸 | **永不 LLM 化**（铁律） | —— |

LLM 断网/超时/无 key → 自动回退规则话术，狗永远不会哑巴。

## 记忆系统（大脑的核心）

| 能力 | 做法 |
|---|---|
| 语义检索 | recency + 相关度（原词/同义词族 + 真 BM25）+ 重要度 + 一跳关联，加权排序 |
| 向量检索（可选） | 温层向量锚点（chromadb）：语义路与关键词路 RRF 倒数秩融合，模糊查询也能捞起相关记忆；`ARGOS_VECTOR_ANCHOR=1` 开启，不装 chromadb 自动降级关键词路 |
| 反思归纳 | 重要事攒够 → LLM 归纳 1-2 条结论，或提炼三分类记忆（persona/episodic/instruction）；噪音批静默翻篇 |
| 遗忘合并 | 同主题流水账并成一条 consolidated；弱旧记忆按 72h 半衰期淡出 |
| 铁律 | 反思/合并/归档条目永不物理删除；记忆卡 = 可编辑 JSON（改文件即改记忆） |

## 快速开始

```bash
pip install -r requirements.txt
pip install chromadb jieba                  # 可选：向量检索 + 中文切词增强
python -m argos.server --executor sim      # 纯逻辑仿真，零硬件依赖
# 或双击 启动ArgOS服务器.bat

curl -X POST http://127.0.0.1:8766/api/command -d "{\"text\":\"去门口\"}"
```

物理仿真（MuJoCo 真物理 + 会真走）需要宇树上游（见 requirements.txt 第 4 节）：

```bash
python -m argos.server --executor dds
```

## Web Console（可选）

Web 观察 + 控制层：看机器人状态 / 发起指令 / 翻记忆 / 传外观图。**它只观测与下发指令，不决策**——编译、落账、安全判定仍在 ArgOS，Web 一行都不复制。两个进程：

```bash
python -m argos.web.gateway --executor sim     # 后端 127.0.0.1:8766
cd console && npm install && npm run dev       # 前端 localhost:5173
```

用法与设计见 `文档/Console_使用说明.md`，数据来源盘点见 `文档/Console_数据源清单.md`。

## 测试

```bash
python -m pytest tests -q -p no:cacheprovider
# 148 passed, 3 skipped          ← 裸环境实测（2026-09-10）
# 装了宇树上游 SDK（unitree_sdk2py，见 requirements.txt 第 4 节）后为 151 passed, 0 skipped
# 注：test_dds_sim / test_dds_walk / test_dds_closed_loop 三例跑真实物理仿真 + DDS 闭环，
#     对机器负载敏感（走位与关节收敛有随机性），负载高时会失败 —— 与大脑层改动无关，
#     排查记录见 文档/反思层有效性探测_20260905.md §5.5
```

## 本项目的部分代码/思路来源于以下开源项目，感谢开源社区的贡献，让我们能够站在巨人的肩膀上。

| 开源项目 | 出品方 | 在本项目中的角色 |
| --- | --- | --- |
| [unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco) | 宇树官方 | 仿真世界：官方 go2 数字替身 + 官方桥。**上游一字未改** |
| [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python) | 宇树官方 | 与真狗同款的通信语言：DDS 频道、LowCmd/LowState、SportClient。真机阶段直接复用 |
| [MuJoCo](https://github.com/google-deepmind/mujoco) | Google DeepMind | 物理引擎——替身背后的牛顿定律计算器 |
| [CycloneDDS](https://github.com/eclipse-cyclonedds/cyclonedds) | Eclipse 基金会 | DDS 通信的底层传输 |
| [OpenClaw Skill 规范](https://github.com/openclaw/openclaw) | 开源社区 | 把"狗大脑"封装成对外技能 |
| [NPCSidekick](https://github.com/LiSheng5/npcsidekick) | 我自己的开源项目 | 记忆系统的出处：语义检索 / 反思归纳 / 遗忘合并，完整移植自它 |

## 致谢

- **宇树科技**：开源 unitree_mujoco 仿真世界与 unitree_sdk2_python——没有官方开放的仿真与 SDK，这个项目无从起步
- **Google DeepMind**：MuJoCo 物理引擎
- **Eclipse Foundation**：CycloneDDS
- **OpenClaw 社区**：技能规范

## 文档

| 想看什么 | 读哪份 |
|---|---|
| 顶层架构 / 复用接缝 / 安全设计 | `文档/架构.md` |
| 可行性调研 | `文档/ai搜索后相关项目后做的可行性调研.md` |
| 上狗前必读 | `文档/真机安全清单.md` |
| 开发小结与实测数据 | `文档/小结_20260829.md` |
| Web Console 用法与设计 | `文档/Console_使用说明.md` |
| Web Console 数据来源盘点 | `文档/Console_数据源清单.md` |
| 反思层有效性探测（触发/编造/可检索/可消费 四维实测） | `文档/反思层有效性探测_20260905.md` |

## 硬件门槛

Go2 只有 **X（基础支持）/ EDU（支持）** 开放二次开发，AIR / PRO 官方不开放（宇树官网支持页查证）。买之前先确认型号。

## License

MIT
