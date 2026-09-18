# ARCHITECTURE —— SIM-first Runtime 的结构

> **范围**：本文只描述**新 runtime**（`argos/agent/` / `argos/world/` / `argos/backends/` /
> `argos/sensors/` / `argos/input/` / `argos/benchmark/`）。
> **旧运行时**（`brain.py` / `executor.py` / `backend.py` … 面向宇树 Go2）的结构见
> `文档/架构.md` §1–§10，那份仍是它的**单一信息源**，本文**不重抄**（免得两套清单漂移）。

---

## 1. 分层与依赖方向

```
        ┌──────────────────────────────────────────┐
        │ 入口层   argos/run.py    argos/demo.py    │
        │          argos/benchmark/                 │
        └──────────────────┬───────────────────────┘
                           │ 只调用，不被调用
        ┌──────────────────▼───────────────────────┐
        │ 认知层   argos/agent/                     │
        │   brain.py     （主循环：Goal→…→Replan）   │
        │   planner.py   （选路线、重规划、复核探针）│
        │   gate.py      （唯一判决点）              │
        │   reflection.py / memory_agent.py（三层记忆）│
        │   watchdog.py  （心跳/动作/后端超时）      │
        │   interfaces.py（**全部抽象**）            │
        └──────────────────┬───────────────────────┘
                           │ 只依赖 interfaces，不认识具体身体
        ┌──────────────────▼───────────────────────┐
        │ 身体层   argos/backends/simulator_backend │
        │          （未来：argos/backends/go2/）     │
        └──────────────────┬───────────────────────┘
                           │
        ┌──────────────────▼───────────────────────┐
        │ 世界层   argos/world/（state.py, mini_world.py）
        │ 仿真层   argos/sim/  （mini_entity, failure_injector, latency）
        │ 感知层   argos/sensors/   输入层 argos/input/
        └──────────────────────────────────────────┘
```

**依赖方向只允许自上而下。** 具体地说：

| 规则 | 为什么 |
|---|---|
| 认知层**不许** import `argos.backends.*` / `argos.sim.*` | 否则"大脑与执行器分离"就废了 |
| 认知层**不许** import `unitree_sdk2py` 等硬件 SDK | 同上；真机依赖只能出现在 `backends/go2/` |
| 身体层**不许** import 入口层 | 反向依赖 |
| `argos/world/state.py` **不依赖**任何其它 runtime 模块 | 它是被依赖方 |

## 2. 三条铁律

1. **LLM 只提议、代码决定执行**：编译 / 落账 / 安全闸**全程不调 LLM**。
   （旧 runtime 就立了这条，新 runtime 继承。新 runtime 目前唯一用到语言的地方是
   `argos/input/speech.py`，而且是**规则抽取、不是 LLM**。）
2. **WorldState 是唯一真相源，且只有 backend 能写**：Planner / Brain 拿到的是
   `WorldView`（不可变投影，改就抛 `FrozenInstanceError`）。
3. **感知是投影，不是写入**：`observe()` 在真相源之上打传感器滤镜；**永不回写 state**
   （回写会让"真相源"变成半真半假的混合体 —— 实测踩过）。

## 3. 数据流（一次动作的完整旅程）

```
Planner.plan(goal, WorldView, lessons, caps, probe, soft_penalty)
   → ActionProposal(kind, params, rationale)      ← 只是提议
ActionProposal.to_action() → Action
backend.apply(Action)
   看门狗 → ActionGate.check() → 失败注入 → 延迟 → MiniEntity.apply()
   → _sync()（写 WorldState + 事件）
   → ActionResult(ok, reason, detail, pose_before/after, sim_time)
Brain：成功 → 下一步；失败 → Reflector → LessonStore / AgentMemory → Planner.replan()
```

## 4. 各模块职责与边界（新 runtime）

| 文件 | 职责 | **不做**什么 |
|---|---|---|
| `agent/interfaces.py` | 全部抽象：`Action` / `ActionKind` / `Proposal` / `Result` / `FailReason` / `Observation` / `WorldState` / `Lesson` / `EmbodimentCapabilities` / `EmbodimentBackend` 协议 | 不含任何具体实现 |
| `agent/brain.py` | 主循环；把失败交给反思；跨 episode 记情节记忆 | 不选路线（那是 Planner）、不判安全（那是 Gate）|
| `agent/planner.py` | 目标→路线→提议串；失败换路线；周期复核探针 | **不碰世界**、不判安全 |
| `agent/gate.py` | 唯一判决点（见 `SAFETY_MODEL.md`）| 不执行、不反思 |
| `agent/reflection.py` | 失败→结构化 `Lesson`（门槛 + 证据 + 反证）| 不决定路线 |
| `agent/memory_agent.py` | 三层记忆：Episodic / Semantic / Procedural | 不做 I/O |
| `agent/watchdog.py` | 心跳 / 动作 / 后端超时；跳闸→安全停止 | 不判业务逻辑 |
| `backends/simulator_backend.py` | 唯一写口：看门狗→闸→注入→延迟→执行→同步 | 不含认知逻辑 |
| `world/state.py` | `WorldState`（真相源）+ `WorldView`（不可变投影）+ `as_dict` | 不依赖别的 runtime 模块 |
| `world/mini_world.py` | 房间 / 路线 / 障碍 / 地点 + `blocked()` 几何 | 不含机器人行为 |
| `sim/mini_entity.py` | 运动学 + 电量消耗 + 逻辑时钟 | 不管安全（闸在上面）|
| `sim/failure_injector.py` | 9 类失败注入（可绑**世界位置**）| **不能伪造闸类失败** |
| `sim/latency.py` | 6 档延迟剖面（逻辑时钟）| 不做真实 sleep |
| `sensors/` | 感知层（噪声/量化/半径/失灵）| 不接真实驱动 |
| `input/` | 人话 → goal（text / speech）| **不是 ASR**；听不懂不猜 |
| `benchmark/` | 场景 × 配置 × seed 全矩阵；参数扫描 | 不含生产逻辑 |

## 5. 扩展点：想加东西改哪一处

| 想做的事 | 改这里 | 上层要不要动 |
|---|---|---|
| **换身体**（真机） | `backends/` 加一个实现 + `run.py` 注册表加一行 | ❌ 一行都不用改 |
| 加传感器 | `sensors/simulated.py` 加一个 + 在 suite 里装上 | ❌ |
| 加输入方式（如手势） | `input/` 加一个 backend | ❌ |
| 加世界/场景 | `world/mini_world.py` 或 `benchmark/scenarios.py` | ❌ |
| 加失败类型 | `FailReason` + `LEARNING_REASONS` + 注入器 | ❌ |
| 改判分口径 | `agent/interfaces.py::ActionResult` 的语义 | ⚠️ 影响 marker |
| **改安全规则** | `agent/gate.py`（**唯一入口**）| ❌ 但要跑全量测试 |

⚠️ 唯一的已知耦合：**Planner 仍绑 `MiniWorld` 的路线拓扑**（`argos/run.py::_route_topology`）。
拿不到拓扑时它**如实抛错**、不假装 backend 无关。真机 backend 要么自己提供路线拓扑，
要么把拓扑改成从 `Observation` 里取（`ROADMAP.md` Wave 3 记着）。

## 6. 与旧运行时的关系

- 两条运行时**并存、互不调用**；旧的一行不改（`git diff` 为空的纪律）。
- 旧运行时继续服务机器狗链路与 Web Console；新 runtime 用于验证认知闭环。
- 对照表在 `文档/架构.md` §11。**改旧 runtime 看那份，改新 runtime 看这份。**
