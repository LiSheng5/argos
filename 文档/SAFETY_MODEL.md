# SAFETY_MODEL —— 安全模型（SIM-first Runtime）

> 本文只描述**新 runtime**（`argos/agent/` + `argos/backends/`）的安全模型。
> 旧运行时的安全设计见 `文档/架构.md` §7（那份仍在服役，**不在这里重抄**）。
> 铁律一句话：**LLM 只提议，代码决定执行。**

---

## 1. 五道关，顺序不可颠倒

```
人说的话 ──① 输入层（听不懂就报错，不猜）
   ↓
Planner.plan() ──② 只产出 ActionProposal（提议），不碰世界
   ↓
③ ActionGate.check()  ← **唯一判决点**
   ↓
④ SimulatorBackend.apply()
     ├─ 看门狗（跳闸 → 除 STOP 外全拒）
     ├─ 闸门再 check（**不可绕过**的那一次）
     ├─ 失败注入（研究用，不能伪造"闸类失败"）
     ├─ 延迟剖面（逻辑时钟）
     └─ 执行器（唯一能改世界的实体）
   ↓
⑤ 世界状态 / 记忆（失败分类 → 只有"世界给的失败"能被学习）
```

| 关 | 代码位置 | 职责 |
|---|---|---|
| ① 输入 | `argos/input/` | 听不懂 → `None` + CLI 退出码 2，**不猜目标** |
| ② 规划 | `argos/agent/planner.py` | 只写 `ActionProposal`，**没有写世界的权限** |
| ③ 闸门 | `argos/agent/gate.py` | 白名单 / 参数 / 边界 / 速度 / 超时 / 禁触字段 / 电量 / **缺数据** |
| ④ 执行 | `argos/backends/simulator_backend.py` | 唯一写口；执行前**再 check 一次**（纵深防御）|
| ⑤ 记录 | `argos/agent/memory_agent.py` | `SAFETY_REJECTED` **不进记忆**（不是世界的经验）|

## 2. fail-closed 清单（拿不准就拒绝）

| 情况 | 结果 | 原因 |
|---|---|---|
| 未知动作 / 身体做不到 | `SAFETY_REJECTED` | 不兜底、不猜 |
| **缺少必要参数** | `INVALID_PARAMS` | 旧闸靠 `KeyError` 兜底 + 默认补 0，**新闸不补** |
| 参数不是有限数字 | `INVALID_PARAMS` | `"abc"` / `NaN` / `inf` 都拒 |
| 目标超出工作空间 | `SAFETY_REJECTED` | 边界写死在闸里 |
| 速度 / 时长超上限 | `SAFETY_REJECTED` | 指令要求的速度上限与超时 |
| 参数里出现禁触字段 | `SAFETY_REJECTED` | 递归扫参数树（复用旧闸 `_scan_forbidden`，**import 不改写**）|
| **传感器缺 pose / battery** | `SAFETY_REJECTED` | 拿不到定位或电量 → 拒绝移动（见 §3）|
| 急停 | `SAFETY_REJECTED` | 全拒 |
| 看门狗跳闸 | `ACTION_TIMEOUT` + 拒移动 | 须**显式 reset**，不自动恢复 |
| 电量 ≤ `battery_min` | `BATTERY_LOW` | ⚠️ **不是**闸的错，见 §4 |

## 3. 缺数据为什么必须 fail-closed

"拿不到的数据就是 null"是底线，但**光记 null 不够**：机器人不能基于"猜的坐标"走出去。

- `Observation.missing` / `WorldState.missing` / `WorldView.missing` 一路透传缺了哪些传感器；
- 闸门对 `MOVE` / `TURN` 检查 `missing` —— 缺 `pose` 或 `battery` 直接拒；
- **闸门看的是"感知到的世界"，不是真值**（`gate.check(action, from_observation(observe()))`）——
  拿不到就该拒绝，而不是凭真值偷偷放行；
- `STOP` / `WAIT` / `INSPECT` **永不因缺数据被拒**：不能把安全动作锁死。

## 4. 两类失败：闸的拒绝 ≠ 世界的经验

| | 触发方 | 例子 | 可学习？ | 为什么 |
|---|---|---|---|---|
| **闸拒绝** | 安全层 | `safety_rejected` / `invalid_params` | ❌ **不进记忆** | 这是"我们不让做"，不是"世界给了反馈"。学它等于污染换线逻辑 |
| **世界失败** | 环境 | 障碍阻挡 / 超时 / 路径失效 / 定位丢失 / 缺传感器 / 电量低 / 执行器故障 / 延迟 / 丢包 | ✅ 进记忆 | 9 类（`LEARNING_REASONS`，与可注入集合一致）|

⚠️ 而且**只有"路线相关"的失败**（`OBSTACLE_BLOCKED` / `PATH_INVALID`）才会生成
"避开这条路"的教训 —— 低电量不是路线问题，学成"北线不能走"就是错误因果。

## 5. 四条可测试的不变量

1. **LLM 不在控制链路上**：编译 / 落账 / 安全闸全程不调 LLM（旧 runtime 的铁律在这里同样成立）。
2. **闸门不可绕过**：`apply()` 内部先过闸；所有动作出口只有一个。
3. **STOP 永远放行**：急停、跳闸、缺数据…任何状态都不阻断 STOP。
4. **跳闸不自动恢复**：`reset_watchdog()` 必须显式调用 —— 断过一次就该停下来被人看一眼。

## 6. 已知限制（照实说）

- **没有真实动力学安全**：仿真里"撞上"就是停下 + 报 `OBSTACLE_BLOCKED`；真机需要力矩/碰撞检测等另一套机制。
- ⚠️ **软件安全之外还有物理与人**：本文只讲软件。**上真机前必读 `文档/真机安全清单.md`**
  （有人在场、物理急停、空旷场地…）。那句话值得原样引用：
  **"软件急停是最后一道，永远不是第一道。"**
- **没有常驻监督进程**：看门狗跑在同一个进程里，进程级失联靠未来的独立监督者。
- **单机单机**：没有多机协同 / 权限模型 / 网络准入。
- **参数范围是拍的**（边界 ±20 / 速度上限来自 `EmbodimentCapabilities` / 超时 10s）——
  已扫参的只有学习侧的阈值（`文档/SWEEP.md`），**安全侧的数值没有扫过**（也不该随便扫）。
- **真机迁移的红线**写在 `文档/FUTURE_ROBOT_BACKEND.md`：真机 backend **必须复用同一个 `ActionGate`**，
  不许"为了跑通"把闸绕过或放宽。
