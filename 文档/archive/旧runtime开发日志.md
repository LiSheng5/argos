# 旧 runtime 开发日志（2026-08-28 → 2026-09-13）—— ⚠️ 已归档

> ⚠️ **已归档到 `文档/archive/`（2026-10-16）。历史流水账，不随代码更新。**
> 2026-09-21 从 `文档/archive/架构.md` 的 §9 / §9.1 / §9.2 整体迁出，
> 目的是让架构文档只回答"现在是什么样"，不再兼任 changelog。
>
> - 这里的**数字都是当时快照**（测试数、trot 步态参数、航向漂移实测、假狗收敛时间）；
>   现基线一律以 **`文档/测试基线.md`** 为准，别从这里抄数。
> - 旧 runtime（`brain.py` / `executor.py` / `backend.py` …）已**冻结维护**，现状见 `文档/ARCHITECTURE.md` §6。
> - 未完成项（转弯调参 / 位姿闭环 / ASR / 真机联调）**全部卡在"没有硬件"**，
>   统一记在 `待办/待办清单.md`（本地，不入库）的 **E-01 真机 backend**，不在这里重复维护。
>
> 以下为原文迁移，节号沿用原 `架构.md` 的编号（便于对照历史引用）。

---

## 9. 当前状态 / 待办
- [x] 可行性调研（ai搜索后相关项目后做的可行性调研.md）
- [x] 顶层架构（本文件）
- [x] argos/ 包骨架：primitives.py + safety.py + executor.py(stub)
- [x] 最小闭环：文本指令 → B2 编译 → 预审+落账 → stub/仿真执行 → 记忆+反思回流
      （brain.py::RobotBrain，2026-08-28，自主日常=巡逻/待命/低电量回桩，test_brain 19 passed）
- [x] unitree_mujoco 物理仿真接入（argos/sim/mujoco.py::MujocoEntity + build_executor('mujoco')）
- [x] server.py：/api/command 复用 npc.server 模式（POST 接单 / GET 状态与记忆 / POST 急停；
      急停中自主循环停摆不刷失败；lifespan 每 3s 推一帧；中文 GBK 请求体兜底，test_server 6 passed）
- [x] OpenClaw Skill 封装（openclaw_skill/SKILL.md，2026-08-29）：照 go2-openclaw-skill 格式，
      核心铁律 = 狗的 reply 原话转述不许编造（落账口语义对外输出）；四类动词对照表 +
      故障处理；全部 curl 指令对真服务逐条实测通过
- [x] DDS 电机级控制（2026-08-28）：cyclonedds 11.0.1 + unitree_sdk2py（pip install -e
      --no-deps 跳过钉死的 0.10.2，API 兼容）在 Py3.13/Windows 直装可用，"需源码编译"已不成立。
      argos/sim/dds_sim.py = 无头 DDS 仿真（官方桥；timerfd 用纯线程垫片替换，上游零改动），
      rt/lowcmd 站立序列 → 物理起立 → rt/lowstate 校验（--selftest；test_dds_sim 以子进程
      跑，因 cyclonedds 原生库退出时段错误，不污染 pytest 退出码）
- [x] 指令 → 走 v1（2026-08-29，直线巡逻员）：trot 步态参数实测调出（freq 2.0Hz /
      摆幅 0.25/0.8 / Kp80Kd4，~0.7m/s 稳定不摔），DdsEntity 分段自适应走到即停。
      全链路已焊死：一句话"去桌边" → 落账 → DDS → 物理仿真真走 2m → 到点记账
      （test_dds_walk）。v1 限制（诚实拒绝并记"没做成"）：不会转弯（左右差动会摔、
      差频只单向有效，待调）、没装手臂(grab/release=False)、y 向漂移 ~10% 不闭环。
      ⚠ 已知副作用（2026-08-29 评审发现，**暂不处理，等转弯调出来**）：狗只沿世界
      -x 走，而 DEFAULT_PLACES 里桌边(2,0)、门口(4,4) 都不在这条轴上 →
      `--executor dds` 开箱即"去哪都失败"。test_dds_walk 是靠自己传
      places={"桌边": (-2.0, 0.0)} 绕开的，所以测试绿 ≠ 默认配置能跑。
      把地点全摆到 -x 轴上（0 / -2 / -4）时，**巡逻一圈能在物理仿真里真的走完**
      （3 帧逐点推进，终点 x=-3.92，见 test_dds_closed_loop）。
- [x] 物理仿真完整闭环（2026-08-29，test_dds_closed_loop）：一句话 → 落账 →
      DDS 电机级 → 真走 → 记账，四类结局都过一遍 —— 巡逻成功 / 没手臂诚实失败 /
      要掉头诚实失败 / 急停拒绝接单。顺手修了 DdsEntity 一个 bug：
      **目标就是当前位置时**原来会被判成"方向不对"而失败（"回充电桩"而狗已在桩边
      会记一条冤枉的"没做成"），现在先判"已到达"。
- [x] 评审后加固（2026-08-29）：
      P0-1 急停到达执行器（原 /api/estop 只置闸门，正在跑的那一段要走完）；
      P0-2 tick 挪出事件循环（原来会卡死 loop，期间急停按不进去）；
      P0-3 补 requirements.txt + .gitignore + git 纳入版本控制；
      P1 navigate 逐点推进 / 禁触字段递归扫描 / 电量未知 fail-closed /
      坏记忆卡改名留证 / test_dds_walk 改确定性断言（原来约 50% 随机误报）。
      基线：**45 passed, 0 skipped**（耗时约 33s）。
      2026-08-29 晚装齐 mujoco 3.12.0 / pygame / cyclonedds 11.0.1 / unitree_sdk2py 后
      复验通过 —— DDS 站立闭环、以及"一句话 → 物理仿真真走 2m"均已复现，
      评审时"无法复现"的那三条不再存疑。
- [x] LLM 可选接入（2026-08-30，argos/llm.py + argos/persona.py + persona.json）：
      无 key 纯规则（行为与旧版一致）；配好 ARGOS_API_KEY（或根目录
      api_key.txt）后，接单/拒绝/听不懂的回复与反思归纳走 LLM（带 persona 性格）。
      编译/落账/安全闸永不 LLM 化；LLM 断网/超时 → 自动回退规则话术。
      /api/command 已 to_thread（LLM 延迟不阻塞事件循环与急停）。
- [x] 记忆系统全搬（2026-08-30，argos/memory.py，119 passed）：之前只有
      "事件卡+反思简版+归档"，架构宣称的"三阶段"名不副实。现已移植坐实：
      ① 检索 = recency×0.5 + relevance×3（原词/同义词族 + 真 BM25）+ importance×2
      + 一跳关联加分；毫不相关返回空（诚实，不塞无关条目）；archived 退出检索。
      ② 反思全家桶 = 噪音闸（候选唯一内容 <3 静默翻篇）+ typed 三分类
      （persona/episodic/instruction，解析失败无痕落回）+ LLM 归纳 1-2 条结论
      + 规则摘要兜底 + 同文不重写。
      ③ 遗忘合并 consolidate = 同主题合并（≥3 条并成一条 consolidated）+
      弱旧修剪（半衰期 72h；反思/合并/归档/重要度 ≥8 免疫）；超限时先合并再归档。
- [x] 温层向量锚点（2026-08-30，VectorAnchor + RRF 融合，126 passed）：chromadb
      可选（ARGOS_VECTOR_ANCHOR=1 开启，默认关零接触零开销）；语义路与关键词路
      RRF 倒数秩融合（k=60），模糊查询捞起关键词召不动的记忆；旧卡空索引自动
      回填；合并/修剪的条目同步出索引；未装 chromadb 优雅降级关键词路。
- [x] **反思层护栏 + 闭环接入**（2026-09-05/06，126 → 133 passed）：
      护栏三层（typed evidence 逐字溯源 / 世界实体 / importance 夹取，校验全不过则
      fail-closed 落规则摘要）；候选窗口改按 importance 取、噪音闸新增"重复模式"判据；
      `recall()` 接进决策（话术层 `_recall_context` + 行为层 instruction 权重 ×3）。
      探测报告见 `商议/反思层有效性探测_20260905.md`（本地，不入库）。
- [x] **Web Console（观察 + 控制层，不决策）**（2026-09-06，`argos/web/` + `console/`）：
      Event Bus + Run Store(SQLite) + `/api/ws` 分频推送 + 统一 RobotState +
      机器人图上传 + MJPEG 相机流；前端 React/Vite 七页。
      **未改动 brain / safety / executor 任何逻辑**（只在 server.py 加了可选
      `tick_sink` 回调，None 时与旧版逐字等价）。详见 §10。
- [x] **健康门 + 读端点隔离**（2026-09-13，149 → 168 passed）：借鉴 Microduck 板端设计，
      `TickTracker` 健康门（idle/ok/degraded/stalled + `/api/system/health` 报真状态 + WS 1Hz）、
      读端点吃 last-value 快照（同一次请求不再读到两帧）、只读端点超时降级（HTTP 仍 200）。
      **急停路径不受影响**（回归钉）。详见 §10.3。

## 9.1 待办
- [ ] **转弯 / 弧线调参**（v1 最大的限制）：原地转向、弧线行走、位姿航向闭环。
      调出来之后 §9 里"--executor dds 开箱即失败"的问题自动消失，
      所以地点表改造押后，不单独做。
- [x] **位姿判据闭环**（2026-08-29）：`DdsEntity` 原来**只看 x 轴**判到点，
      侧向漂多少都不管 —— 判据太松比没有判据更危险，它会让上层以为一切正常。
      现在改成三层判据（都是纯函数，有单测，见 `tests/test_pose_loop.py`）：

      | 判据 | 默认值 | 说明 |
      |---|---|---|
      | `arrived()` 纵向 | 0.25m | 行走轴，分段自适应能控住 |
      | `arrived()` 横向 | 0.8m | **v1 不会转向，这个轴控不了** → 这是能力上限，不是目标 |
      | `drifted()` 横向预算 | 1.0m | 偏出就停下，别越走越远 |
      | `heading_drifted()` 航向预算 | 30° | **最早**的失控信号，见下 |

- [ ] **真正的位姿闭环（要等能转向）** —— 上面只是"判据诚实"，不是"闭环纠偏"。
      实测根因（走 1m，4 次）：

      | 次 | 航向漂 | 结果 |
      |---|---|---|
      | 1 | 1.4° | 走 1.06m，横向偏 0.08m ✅ |
      | 2 | 19.9° | 走 1.07m，横向偏 0.08m ✅ |
      | 3 | **163.2°** | 狗几乎掉头，横向偏 1.07m ❌ |
      | 4 | **85.3°** | 狗横着走，跑了 3.61m ❌ |

      **trot 步态是开环的**，航向一偏就一路偏下去 —— 不是"漂移"，是"打转"。
      等横向位移超预算才发现时它已经跑出 3.6m 了，所以单独加了航向预算。
      但**检测到也纠不回来**（v1 不会转向），只能停下。
      → 真机接高层（小脑自带航向闭环）后：横向容差收严回 0.25、加航向纠偏、
      这三条预算转成"异常保护"而不是"主要判据"。
- [ ] 语音入（ASR）：§6 写了方案，代码零实现。可选 faster-whisper（本地离线），
      /api/command 接 {audio} 或 {text} 两种入参；语音出可复用 npc/tts.py。
- [x] 真机执行器骨架 RealSportEntity（2026-08-29）：高层 SportClient 路线，
      闭环逻辑 `plan_drive()` + 超时/卡住/急停 全部有单测（喂假狗，14 个用例）。
      剩下"连接真机"那几行（connect_sport / sportmode_pose_source）标了未验证。
- [ ] 真机联调（M3，需实物 + X/EDU 型号）：真机到手后按顺序核
      ① 网口连通与 ChannelFactoryInitialize 参数；
      ② sportmodestate 的 position / rpy 字段与单位（这是闭环的位姿来源）；
      ③ 接 BMS 真实电量（没有它就一直"电量未知"，巡逻会被拒）；
      ④ 按实测重调 k_v / k_yaw / max_speed 这几个增益。
      然后跑 tests/test_real_sport.py 的假狗用例做对照，再上真狗。
- [ ] 真机化后补测试：现在 P0-1/P0-2/P1-6 只由假执行器覆盖，真机上还要
      验一次"急停到电机"的端到端延迟。

## 9.2 实测演示记录（2026-08-30，live 实况）

在物理仿真里跑了完整服务（--executor dds，地点表摆 -x 轴），对话→真走全链路
实况验证。**结果有成功也有失败，都写在这里：**

| 环节 | 结果 |
|---|---|
| 对话编译/落账/诚实拒绝 | ✅ "去门口"→"好，我去门口。"；"写文件"→"我不认识" |
| 自主循环 | ✅ 服务起来第一帧就自己选了巡逻开始走 |
| 物理仿真真动 | ✅ MuJoCo 里位姿真实移动（原点 → x=-1.86 → -2.16） |
| 记忆/反思 | ✅ 失败记账 + "我最近做了这些事…"反思条目均落卡 |
| 走位 | ❌ 巡逻与"去门口"均失败，狗只走了 0.2~1.9m 就停 |

**失败根因（现场复现 §9.1 的"开环打转"结论）**：服务起来第一轮自主巡逻
就漂（走到 x=-1.86 时 yaw 已 21.7°、y=-0.43）并触发航向预算停下；紧接着
我发"去门口"，起步位姿就是歪的（yaw≈19° 且在漂），走 0.22m 航向相对漂出
30° 预算 → `heading_drifted` 触发 → 立刻停下诚实记账（dds_entity.move_to
L129-130）。**不是新 bug**：v1 低层 trot 开环，检测到失控也纠不回来，只能停
——这正是等真机高层 SportClient（小脑自带航向闭环）的原因。演示的失败路径
同样证明了安全闸与诚实记账在真实运行中工作正常。
