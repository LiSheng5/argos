# ROADMAP —— 后续路线（2026-09-18 重排）

> 依据：① 用户 2026-09-17 那份长指令（26 节 + Phase 0–10）里**尚未完成**的部分；
> ② `文档/经验学习_相关方案调研.md` 里**有据可查**的可借方案；
> ③ 本仓库 benchmark 实测暴露的**已知缺陷**。
> 排序原则：**真实闭环 > 功能数量**；能被执行验证的 > 只是听起来对的；文档跟着既定代码写。

---

## 1. 盘点：指令做完了多少（逐节核对，非凭记忆）

| 节 | 内容 | 状态 | 证据 |
|---|---|---|---|
| §1–§8 | 目标 / 审计 / 架构 / Simulator / World Model / 失败注入 / 反思闭环 / Benchmark | ✅ | `文档/SIM_FIRST_AUDIT.md`、`argos/agent/`、`文档/BENCHMARK.md` |
| §10–§14 | EmbodimentCapabilities / 安全层 / Watchdog / 延迟剖面 / 确定性 | ✅ | `gate.py`、`watchdog.py`、`latency.py`、同 seed 可复现测试 |
| §15–§17 | Mini World / 完整 Demo / Trace | ✅ | `mini_world.py`、`文档/demo_trace.md`、`examples/sim_trace/` |
| §18 | 暂时不要做（真机 / ROS2 / 复杂 GUI…） | ✅ | 全程遵守，真机代码冻结 |
| §23 | benchmark 数据表 | ✅ | 22 场景 × 5 臂 × 3 seed = 330 组 |
| §28 | correctness > complexity | ✅ | 旧代码零改、零回归守住 |
| **§9** | **Memory 三类型（Episodic / Semantic / Procedural）** | ❌ | 现在只有一个 `LessonStore` |
| **§19** | **感知 SensorBackend（SimVision/Battery/Pose/Obstacle）** | ❌ | 无 `argos/sensors/` |
| **§20** | **语音 TextInputBackend / SimulatedSpeechBackend** | ❌ | goal 直接传字符串，没有 backend 抽象 |
| **§21** | **统一入口 `python -m argos.run --backend simulator`** | ❌ | 只有 `demo.py` / `benchmark`，没有 `run.py` |
| §22 | 三层测试（Unit / Integration / Scenario） | ⚠️ | 用例都在，但**没有分层结构**，靠文件名约定 |
| §24 | 未来真机只作 Backend | ⚠️ | 协议在，**缺规范文档** |
| §25-9 | 验收「可替换」 | ⚠️ | 接口具备，但**没有第二个 backend 证明** |
| §26 | Phase 6 / 9 / 10 | ❌ | 见下 |
| §27 | 八篇文档 | ⚠️ **2/8** | 有 SIM_FIRST_AUDIT / BENCHMARK；缺 ARCHITECTURE / SIMULATION / WORLD_MODEL / REFLECTION_LOOP / SAFETY_MODEL / FUTURE_ROBOT_BACKEND |

## 2. 现有缺陷（本仓库实测 + 文献对照）

| # | 缺陷 | 文献里的解法 | 来源 |
|---|---|---|---|
| D1 | 教训只强化不证伪 → 永久绕路 | 已补 `weaken()`，但规则粗糙 | — |
| D2 | 反证只会"降级/删除" | **EDIT**：把教训改准（信息量更大） | ExpeL ✅ |
| D3 | 复核是固定周期（拍的） | 折扣/滑窗（被动遗忘）或变点检测（主动遗忘） | NS-MAB ✅ |
| D4 | 归因粒度粗、且归因本身不可靠 | 教训**可撤销 + 可审计 + 干预验证** | Who&When ✅ / DoVer ⚠️ |
| D5 | 阈值全是拍的值 | 扫参 + 报告敏感度 | — |
| D6 | 教训归零即删、只在内存 | **invalidate 不 discard** + 留痕 | Zep ⚠️ |
| D7 | 没有独立 Evaluator | 三角色拆分（Actor/Evaluator/Reflector） | Reflexion ✅ |
| D8 | 场景集区分不出成功率 | 补"单次运行救不回来"的场景 | — |

---

## 3. 三波推进（每波都可独立验收）

### Wave 1 · 补上最硬的缺口 + P0 改进
| 项 | 内容 | 验收 |
|---|---|---|
| **A1** | `argos/run.py`：统一入口 `python -m argos.run --backend simulator`；`--backend go2` 要**如实报"未实现"**，不许伪造 | 测试：能跑通、未知 backend 明确报错、同 seed 可复现 |
| **B1** | 教训 **invalidate 不删** + 记 `created/counter_evidence/验证历史` | 审计轨迹可查；旧测试零回归 |
| **B2** | **EDIT 操作**：把教训改准（而不只是降级） | 测试：编辑后 `avoid/prefer` 变化，计数上升 |
| **D-ref** | `文档/REFLECTION_LOOP.md`（跟着代码写，避免二次漂移） | 与 `reflection.py` 逐条对得上 |

### Wave 2 · 让它"更稳"并能量化 —— ✅ 已完成（2026-09-18）
| 项 | 内容 | 结果 |
|---|---|---|
| **A2** | Memory 三类型（Episodic / Semantic / Procedural）| ✅ `memory_agent.py::AgentMemory`，Planner 同时吃硬策略与软降权 |
| **B4** | 成功/失败**成对**记 | ✅ `EpisodeEvent` 区分 `route_ok` / `episode_ok`；有分母才算得出失败率 |
| **B3** | 复核换**滑窗** | ✅ Semantic 用最近 `window=3` 次；**但滑窗不能替代主动试探**（不去走就不会有新观测）—— 结论写进复盘 |
| **C2** | 补"单次运行救不回来"场景 | ✅ 新增 `learn_to_survive`（预算只够走一趟）→ **成功率从区分不出变成 81.9%~87.7%** |
| **C3** | benchmark 重跑 | ✅ 24 场景 × **6 臂** × 3 seed = 432 组 |

Wave 2 得到的两条新结论（都进了 `文档/BENCHMARK.md` §4 自动推导）：
1. **软降权 ≈ 硬策略**（`semantic_only` 与 `memory_reflection` 都是 85.6%）——
   在这个世界规模下，把"避开"升级成硬策略并没有额外收益。
2. **复核的收益取决于预算**：宽裕时 10.80→9.20 动作（赚），紧时成功率 50%→25%（亏）。

### Wave 3 · 感知与评估补齐 —— ✅ 已完成（2026-09-18）
| 项 | 内容 | 状态 |
|---|---|---|
| **C1** | 阈值/周期**扫参** + 敏感度报告（D5）| ✅ `argos/benchmark/sweep.py` + `文档/SWEEP.md` |
| **A3** | 感知层 `argos/sensors/`：SimPose / SimBattery / SimObstacle / SimVision（§19）| ✅ |
| **A4** | 输入层 `argos/input/`：`TextInputBackend` / `SimulatedSpeechBackend`（§20）| ✅ |
| **B6** | 变点检测（ADWIN 简化版）替代固定周期（D3）| ⬜ 待做（见下方判断）|
| **B5** | Evaluator 独立成模块（D7）| ⏸ **本轮主动推迟**（见下方判断）|

#### C1 扫参结果（`文档/SWEEP.md`）
- **只有 `revalidate_every` 敏感**（成功率极差 **4.2 个百分点**）：0 → 85.6%、1 → 81.5%、2/3 → 83.6%；
- 其余五个阈值参数**都不敏感**（极差 ≤0.5 个百分点，落在噪声量级）→ 当初"拍的值"风险基本解除；
- ⚠️ **不要因为"0 最高"就把复核关掉**：全局平均最优 ≠ 每个场景最优。
  `two_strikes_then_clear` 族里复核是赚的（10.80→9.20 动作），`learn_to_survive` 族里是亏的（50%→25%）。
  **结论是"按预算决定"，不是"关掉最好"。**

#### A3 感知层要点（`argos/sensors/`）
- **感知是投影，不是写入**：`observe()` 在世界状态之上打一层传感器滤镜；
  不配传感器 = 上帝视角直读（与从前逐字一致 → 432 组 benchmark 数字**逐位未变**）。
- **传感器失灵 → 闸门 fail-closed**：拿不到定位/电量就拒绝移动（STOP/WAIT 仍放行，不能把自己锁死）。
  闸门看的是**感知到的世界**，不是真值 —— 拿不到就该拒绝，而不是凭真值放行。
- **探测半径**：看不见远处障碍时 agent **只能撞了才知道** —— 这正是"只能靠试错学"的成立条件。
- ⚠️ 踩坑记录：先把传感器读到的 tuple 直接写进 WorldState（而 `view()` 要 dict）→ 一读就炸；
  改成"感知做投影"后统一了形状转换（`state.as_dict`）。另外 dataclass 属性**不能叫 `field`**，
  会遮蔽 `dataclasses.field`。

#### A4 输入层要点（`argos/input/`）
- `text` 直通 / `speech` 口语规则抽取（去客套词 → 找"去/到/前往"后的地点短语 → 交给 resolver 校验）。
- ⚠️ **这不是语音识别**（不接 ASR、不接 LLM），只是口语模拟；**听不懂返回 `None`，绝不猜**。
- CLI：`python -m argos.run --input speech --say "麻烦帮我去一下充电站吧"`；
  听不懂 → 退出码 2 + 明确报"没听懂"，**不执行任何猜测**。

#### 两个"暂时不做"的判断（写下来，免得被当成忘了）
- **B5（Evaluator 独立）⏸**：现在"判分"就等于 `ActionResult`，把它抽成接口**在当前世界里
  没有任何可观测差异**（不存在"计划跑完但没到目标"的情况：路线终点就是目标）。
  做了只有抽象、没有可验证收益 —— 指令 §28 说的是 correctness > complexity，不是抽象越多越好。
  **触发条件**：等世界变复杂（多目标 / 带前置条件的任务）再做。
- **B6（变点检测）⬜**：文献里的"主动遗忘"作用于**你仍在使用的臂**。
  而我们这里要复核的是**已经被避开、不再去走的路线** —— 没有新观测，变点检测**根本不会触发**。
  所以它只能替代"固定周期"，**替代不了主动试探**。要做就该做在"当前路线的行为变了"这个信号上，
  和 `revalidate_every` 并存而不是替换（这是它的正确形态，也才值得做）。

### Wave 4 · 文档收口（Phase 9 + 10）
`文档/ARCHITECTURE.md`、`SIMULATION.md`、`WORLD_MODEL.md`、`SAFETY_MODEL.md`、
`FUTURE_ROBOT_BACKEND.md` + `argos/backends/go2/` 规范（**只写规范，不写真机代码**）。

---

## 4. 红线（每波都必须守）

- **旧运行时零改动**：`brain.py` / `executor.py` / `backend.py` / `safety.py` / `real_sport.py` /
  `dds_entity.py` / `mujoco.py` 一行不改；测试基线**只增不减**（当前 265 passed + 3 skipped）。
- **不伪造硬件**：`--backend go2` 必须明确报"未实现"，禁止用假真机代码冒充完成。
- **能做实验验证的才上**：文献方案必须先在本仓库 benchmark 里跑出数字才算"借到了"
  （参考已实测的负结果：反思只写不读 = 零价值）。
- **门槛类参数读写同一个来源**；**空元组 ≠ 没配置**（这两条都实测踩过）。
- 删文件用 Python `os.remove`（走回收站），**永不 `git rm`**。

## 5. 明确不做（指令 §18 原话照守）

Go2 真机适配、伪造 real executor、真实 DDS 性能指标、真实传感器驱动、硬件参数优化、
大规模多机器人、ROS2 全家桶迁移、复杂 GUI、几十种传感器。

## 6. 当前待办（与本文件无关但别忘）

⚠️ 本地提交 `941eb64` **尚未 push**（`git push` 报连接被重置）—— 等网络恢复后推。
