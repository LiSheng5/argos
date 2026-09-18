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

### Wave 2 · 让它"更稳"并能量化
| 项 | 内容 |
|---|---|
| **A2** | Memory 三类型（Episodic / Semantic / Procedural），Planner 按当前任务选类型（§9）|
| **B4** | 成功/失败**成对**喂给反思（对比而非只看失败）|
| **B3** | 复核换**折扣/滑窗**（SW-TS 风格），替掉固定周期 |
| **C2** | 场景集补"单次运行救不回来"的类型（治 D8）|
| **C3** | benchmark 重跑 + §4 结论自动更新 |

### Wave 3 · 感知与评估补齐
| 项 | 内容 |
|---|---|
| **A3** | `argos/sensors/`：SimVision / SimBattery / SimPose / SimObstacle（§19）|
| **A4** | 语音层：`TextInputBackend` / `SimulatedSpeechBackend`（§20）|
| **B5** | **Evaluator 独立成模块**（D7）：判分与执行分离 |
| **B6** | 变点检测（ADWIN 简化版）替代固定周期（D3）|
| **C1** | 阈值/周期**扫参** + 敏感度报告（D5）|

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
