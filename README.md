# ArgOS

> 宇树 Go2 机器狗的 AI 大脑 —— 一句话指挥，安全闸守护。
> An AI brain for Unitree robot dogs: one sentence in, guarded motion out.

ArgOS 把"游戏 NPC 大脑"移植到了机器狗身上：文本指令 → 编译 → 落账 → 安全闸 → 执行 → 到点记账 → 记忆回流。大脑与执行器分离，真机到手只需换执行器，大脑一行不改。

**诚实声明：**
- ✅ 大脑层（编译/落账/安全/记忆/服务）在物理仿真里完整验证，85 项测试全绿
- ✅ 真机执行器（高层 SportClient + 闭环控制器 + 断链看门狗）代码与单测就绪
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
| 语义检索 | recency + 相关度（原词/同义词族 + 真 BM25）+ 重要度 + 一跳关联，加权排序；可选温层向量锚点（chromadb，`ARGOS_VECTOR_ANCHOR=1`）与关键词路 RRF 融合 |
| 反思归纳 | 重要事攒够 → LLM 归纳 1-2 条结论，或提炼三分类记忆（persona/episodic/instruction）；噪音批静默翻篇 |
| 遗忘合并 | 同主题流水账并成一条 consolidated；弱旧记忆按 72h 半衰期淡出 |
| 铁律 | 反思/合并/归档条目永不物理删除；记忆卡 = 可编辑 JSON（改文件即改记忆） |

## 快速开始

```bash
pip install -r requirements.txt
python -m argos.server --executor sim      # 纯逻辑仿真，零硬件依赖
# 或双击 启动ArgOS服务器.bat

curl -X POST http://127.0.0.1:8766/api/command -d "{\"text\":\"去门口\"}"
```

物理仿真（MuJoCo 真物理 + 会真走）需要宇树上游（见 requirements.txt 第 4 节）：

```bash
python -m argos.server --executor dds
```

## 测试

```bash
python -m pytest tests -q -p no:cacheprovider
# 85 passed, 0 skipped
```

## 站在哪些开源肩膀上

| 开源项目 | 出品方 | 角色 |
| --- | --- | --- |
| unitree_mujoco | 宇树官方 | 仿真世界：官方 go2 数字替身 + 官方桥（上游一字未改） |
| unitree_sdk2_python | 宇树官方 | 与真狗同款的通信语言：DDS / LowCmd / SportClient |
| MuJoCo | Google DeepMind | 物理引擎 |
| CycloneDDS | Eclipse 基金会 | DDS 底层传输 |
| OpenClaw Skill 规范 | 开源社区 | 对外技能封装 |

大脑层的"规划—执行—反思—记忆"系统源自作者自己的项目 [NPCSidekick](https://github.com/LiSheng5/npcsidekick) 尚未发布的新改动（AI 游戏 NPC 框架，MIT）。

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

## 硬件门槛

Go2 只有 **X（基础支持）/ EDU（支持）** 开放二次开发，AIR / PRO 官方不开放（宇树官网支持页查证）。买之前先确认型号。

## License

MIT
