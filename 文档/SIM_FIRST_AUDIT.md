# SIM_FIRST_AUDIT —— ArgOS 转向「Embodied Agent Runtime」前的现状审计

> 审计日期：2026-09-17 · 方式：**只读**（未修改任何代码）· 结论均实测可复现
> 被审对象：`D:\ArgOS`（github.com/LiSheng5/argos）
> 前提：**当前没有任何真实机器人硬件。** 本文件回答"哪些能直接用、哪些错误假设了真机、缺口在哪"。
> 后续路线见 `目录/.workbuddy/plans/` 的实施方案；本轮范围 Phase 0–4。

---

## 0. 一句话结论

**大脑层（编译 / 落账 / 安全闸 / 记忆 / 服务 / Web）已经完全不依赖硬件，可以原样成为新 Runtime 的一部分；
但"规划—世界模型—失败—反思—重规划"这条闭环在代码里根本不存在** —— 这是本轮要新建的部分，不是要修的部分。

| 维度 | 结论 |
|---|---|
| 能否不买机器人跑通 | ✅ 大脑层可以（审计当时裸环境 **168 passed + 3 skipped**；现基线见 小结 §1） |
| 能否不装宇树上游跑通 | ⚠️ 物理/DDS 3 例会跳过（`importorskip("unitree_sdk2py")`），需按 `requirements.txt:35-42` clone 两个上游 |
| 是否存在 Planner | ❌ 不存在 |
| 是否存在 WorldState | ❌ 不存在（状态散在 4 处） |
| 是否存在 ActionResult | ❌ 不存在（只有裸 bool） |
| SafetyGate 是否在所有动作出口之前 | ✅ 是，无绕过 |
| Reflection 是否影响下次 planning | ❌ 否 |
| Memory 是否被 Planner 消费 | ❌ 否（只用来说话） |
| 能否模拟执行失败 | ❌ 无统一机制 |
| 能否靠 simulator 复现"感知→规划→行动→失败→修正" | ❌ 不能 |

---

## 1. 哪些模块完全不依赖硬件（可直接复用）

| 模块 | 依赖 | 证据 |
|---|---|---|
| `argos/brain.py` 的编译与落账 | 纯规则（正则词表）+ 内部账本 | `brain.py:103` `compile_command`、`brain.py:205` `book` |
| `argos/safety.py` SafetyGate | 纯逻辑，只吃 `pose()` 字典 | `safety.py:63` `check` |
| `argos/memory.py` 检索 / 反思 / 合并 | 纯 Python（chromadb 为可选增强） | `memory.py`（`ARGOS_VECTOR_ANCHOR=1` 才启用向量路） |
| `argos/sim/stub.py` | 瞬移假执行器，零硬件 | `stub.py:24` |
| `argos/web/`（Console 观测层） | FastAPI + SQLite，零硬件 | `web/gateway.py` |
| `argos/server.py` | FastAPI | `server.py` |

**结论**：这些模块一只脚已经踩在"与机器人无关"上了。

## 2. 哪些模块错误地假设了真实机器人（本轮冻结，不改不删）

| 模块 | 假设了什么 | 证据 |
|---|---|---|
| `argos/real_sport.py` | 宇树高层 `SportClient`、真狗网口、`ChannelFactoryInitialize` | `real_sport.py:136` |
| `argos/sim/dds_entity.py` | 真 DDS 频道 `rt/lowcmd` + 官方桥；**只能走世界 -x 直线、不会转向** | `dds_entity.py:24`、`:119` |
| `argos/sim/mujoco.py` | 需要上游 `unitree_mujoco` 场景文件（缺失是 `FileNotFoundError` 而非 skip） | `mujoco.py:22-24` |
| `argos/watchdog.py` | 只活在 `RealSportEntity` 内部，与 SafetyGate **无联动** | `watchdog.py:36`、`real_sport.py:158` |

> 用户决策：这四块**冻结保留**，标注为"未来 RobotBackend 素材"；本阶段不发展、不改写、不删除（14 个真机单测继续跑）。

## 3. 当前 Simulator 能模拟什么

| 执行器 | 能模拟 | 不能模拟 |
|---|---|---|
| `sim/stub.py` | 坐标瞬移 | 时间、物理、碰撞、转向（**`navigate` 直接跳到最后一点，中间点全跳过**，`stub.py:30-38`） |
| `sim/mujoco.py` | 真实物理步进 | 不会走（`move_to` 只 `return not self._estop`，`mujoco.py:42-47`） |
| `sim/dds_entity.py` | 会真走（trot 步态） | 只走 -x 直线、**不转向**（差动会摔）、航向实测漂到 **163°**、`grab/release` 恒 False（`dds_entity.py:24/119/149`） |
| 全部 | 位置、estop、（恒 100% 不耗电的）电量 | **无障碍物、无可抓物体、无人、无传感器噪声、无通信延迟、无电量消耗**（`stub.py:16`） |

## 4. 当前 World State 在哪里维护

**不存在集中对象。** 真源散在四处，且无快照、无版本号：

1. `executor.pose()` → `x/y/yaw/battery_pct/estop/gripper`（`sim/stub.py:19`、`mujoco.py:39`、`dds_entity.py:98`、`real_sport.py:168`）
2. `RobotBrain` 运行时：`state/activity/pending_task/_blocked/_blocked_desc/_tick`（`brain.py:176-181`）
3. `SafetyGate.estop` / `boundaries`（`safety.py:57-58`）
4. 记忆卡 `brain.memory`（`brain.py:162`）

另有一个**展示层**模型 `web/models.py:65` 的 `RobotState`，由 `web/telemetry.py:28` 现场拼装——它不是真相源。

## 5. ActionResult 如何返回

**不存在。** 返回是二元组 `Tuple[bool, str]`（`backend.py:56`），只有 `ok` + 中文 `reason` 字符串。

更糟的是**失败原因在内部就被丢弃**：`real_sport.py` 明明区分了超时（`:212`）、卡住/被挡（`:204-207`）、断链（`:193`）、无手臂（`:224`），
但对外统统 `return False`。上层拿到的是一个无法分类的"执行失败"。

## 6. SafetyGate 是否位于所有动作出口之前

**✅ 是，且无绕过。** `gate.check()` 生产调用点 3 处：

- `argos/backend.py:39` —— **真正的闸**，唯一动作出口（`brain.py:346` → `backend.apply`）
- `argos/brain.py:216` —— `book()` 落账预审
- `argos/web/bridge.py:164` —— Console 只读预审（注释明说"真正那道在 backend.apply 里"）

server / API 均只到 Brain（`server.py:144/163`、`web/api.py:185/261/312`），没有直接捅执行器的路径。

**但闸门本身不完整**（对照指令第十一条）：

| 要求 | 现状 | 证据 |
|---|---|---|
| 动作白名单 | ✅ | `safety.py:65` |
| 禁触字段（递归） | ✅ | `safety.py:68` + `_scan_forbidden:40-52` |
| 急停状态 | ✅ | `safety.py:71` |
| 电量门限 | ✅（三级 10%/20%/未知 fail-closed） | `safety.py:74-82` |
| 工作空间边界 | ✅ | `safety.py:84-91` |
| **速度上限** | ❌ 无 | — |
| **超时** | ❌ 无 | — |
| **参数范围/类型校验** | ❌ 无 | — |
| **缺字段 fail-closed** | ❌ 靠 `backend.py:54` 的 `KeyError` 兜底，**不在闸内** | `safety.py:88` `pt.get("x", 0.0)` 默认补 0 |

## 7. Reflection 是否真正影响下一次 planning

**❌ 否。** 三重断裂：

1. 反思产物分两种：结构化 typed 条目 `{mtype, content, importance, evidence}`（`brain.py:638-645`）+ 单条纯文本（`brain.py:650/656`）。
2. 但 `_reflect_candidates` **显式排除** `kind == "reflection"`（`brain.py:674`）→ 反思条目不参与后续反思。
3. 更关键：**没有任何"上次撞墙 → 换路线 / 改参数"的通路**。无结构化 `Lesson` 字段，无 planner 可读取的接口。

反思当前只流向三处：措辞、instruction 权重放大（用于 `_choose_routine` 选日常，`brain.py:418`）、`/api/memory` 给人看。

## 8. Memory 是否被 Planner 消费

**❌ 否。**

- `recall()` 定义 `brain.py:573`；**唯一生产调用点** `brain.py:272`（`_recall_context`），只被 `try_command` 调用，结果拼进 LLM 提示词 → **仅供措辞**（`brain.py:244/254/262`）。
- `recent()`（`brain.py:568`）→ `server.py:149`，**仅展示**。
- 行为层唯一消费 `_instruction_hints`（`brain.py:444`）**不走 `recall()`**，直接遍历 `self.memory` 过滤 `mtype == "instruction"`，用于"选日常活动"的加权随机 —— 不是规划。

## 9. 是否能模拟执行失败

**❌ 无统一机制。** 现有零散手段：

| 手段 | 位置 |
|---|---|
| 急停 | `stub.py:50`、`dds_entity.py:154`、`safety.py:60` |
| 调小横漂预算逼失败 | `tests/test_dds_closed_loop.py:79` |
| 给偏离行走轴的目标制造确定性失败 | `tests/test_dds_walk.py:33` |
| 耗时假执行器（测 tick 阻塞） | `tests/test_estop_and_tick.py:16` |
| 假狗 / 假 Sport | `tests/test_real_sport.py:20,36` |
| 假 LLM fail | `tests/test_brain.py:258` |

指令要求的 `obstacle_blocked / action_timeout / path_invalid / localization_error / battery_low /
sensor_missing / simulator_delay / network_delay / executor_failure` —— **全部无法主动注入**
（现有 `ARGOS_*` 环境变量只有 API_KEY / MODEL / TIMEOUT / VECTOR_ANCHOR / READ_TIMEOUT / EXECUTOR / PORT / PERSONA）。

## 10. 是否可以通过 simulator 完整复现「感知 → 规划 → 行动 → 失败 → 修正」

**❌ 不能。** 三处硬缺口：

1. **无世界模型**：只有"地名→坐标"字典（`brain.py:78-84`：充电桩 / 家 / 桌边 / 门口）+ 矩形边界（`safety.py:18`）。
   无房间、走廊、门、障碍、充电站实体。MuJoCo 场景只是地平面 + 几个 box，属于上游资产不是项目资产。
2. **无 Replan**：失败即终止 —— 记 `_blocked[action] = tick + 5` 冷却（`BLOCK_AFTER_FAIL_TICKS=5`，`brain.py:350`）、
   写 `EV_FAIL`（`:354`）、`activity = None`、**剩余步骤全部丢弃**（`brain.py:346-356`）。不重试、不换路、不降级。
3. **无失败分类**（见 §5），上层分不清"被挡住"和"超时"，也就无从选择不同的修正策略。

---

## 11. 审计带来的四个设计决定

1. **旧代码不动**：新建 `argos/agent/` + `argos/world/` + `argos/backends/` 平行 runtime，旧 `brain.py` / `executor.py` / `backend.py` 一行不改 → 168 测试零回归。
2. **新 runtime 自带 `ActionGate`**：旧闸白名单只有 `move_to/navigate/grab/release`（`primitives.py:5`），会拒掉新世界的 `turn/wait/inspect`；
   且旧闸缺速度上限 / 超时 / 参数范围 / 缺字段 fail-closed。旧闸已冻结 → 新闸能力驱动，复用 `safety.battery_of` 与 `safety._scan_forbidden`（import 而非改写）。
3. **`SAFETY_REJECTED` 与"真实执行失败"分开**：被闸拒不是"世界给的经验"，不进 Lesson，否则污染换线逻辑。
4. **仿真层必须有 seed**：大脑层有种子注入口（`brain.py:145,160`），但 `DdsSim` / `MujocoEntity` 均无；已知 flaky（`README.md:96-98`）。
   新 runtime 所有随机走注入的 `random.Random`，逻辑时钟用 `sim_time` 累加而非 `time`。

---

*本文件所有结论可复现：`pytest tests -q -p no:cacheprovider`（审计当时裸环境 168 passed + 3 skipped；
现基线见 `文档/小结_20260829.md` §1 —— 本文件是 Phase 0 的**审计快照**，数字不随代码更新）；
代码结论按 `文件:行号` 可逐条核对。*
