# GLOSSARY —— 术语表

> 目的：**同一概念只在这里定义一次**，别处一律指过来。
> 建表动机：Episodic / FailReason / WorldView 这类词之前散在 8 篇文档里各解释一遍，
> 是"正文式重复"的最大单一来源。
> 两套 runtime 的术语**都收在这里**（`ARCHITECTURE.md` 只讲新 runtime，放那儿会错配）。
>
> 列「套」：新 = SIM-first Runtime（`argos/agent/` 一套）；旧 = 面向 Go2 的旧运行时（已冻结）。

---

## 1. 两套 runtime 怎么分

| 术语 | 套 | 一句话 | 定义处 |
|---|---|---|---|
| **旧运行时** | 旧 | `brain.py` / `executor.py` / `backend.py` / `safety.py` 一套，面向宇树 Go2，**冻结维护** | `文档/archive/架构.md` §1–§10 |
| **SIM-first Runtime** | 新 | `argos/agent/` + `argos/world/` + `argos/backends/`，零硬件依赖，后端可替换 | `文档/ARCHITECTURE.md` |
| **backend / embodiment** | 新 | 一种"身体"的实现（现在是 Simulator，未来可能是 Go2）。换身体只换它 | `文档/ARCHITECTURE.md` §5 |

## 2. 世界与感知（新）

| 术语 | 一句话 | 定义处 |
|---|---|---|
| **WorldState** | **唯一真相源**，只有 backend 能写 | `文档/WORLD_MODEL.md` §1 |
| **WorldView** | WorldState 的**不可变投影**；Planner 改它就抛 `FrozenInstanceError` | 同上 |
| **Observation** | 传感器滤镜下的观测（**不是**真相源） | `文档/SAFETY_MODEL.md` §3 |
| **`missing`** | 本轮没读到的传感器名，一路透传到闸门 | 同上 |
| **投影 ≠ 写入** | 感知/派生数据**永不回写**真相源，否则真相源变半真半假 | `文档/ARCHITECTURE.md` §2 |
| **探测半径** | 传感器能看多远 → "看不见 ≠ 挡不住"（只能撞了才知道） | `文档/SIMULATION.md` §2b |

## 3. 动作与失败（新）

| 术语 | 一句话 | 定义处 |
|---|---|---|
| **ActionProposal** | Planner 的**提议**（只提议，不碰世界） | `文档/ARCHITECTURE.md` §3 |
| **Action** | Proposal 转成、真正下发给 backend 的动作 | 同上 |
| **ActionKind** | 动作种类：`move` / `turn` / `stop` / `wait` / `inspect` / `grab` / `release` | `argos/agent/interfaces.py` |
| **ActionResult** | 结构化结果：`ok` + `reason` + `detail`，**不是裸 bool** | `文档/SIMULATION.md` §2 |
| **FailReason** | 失败分类，**九类**见下 | `argos/agent/interfaces.py` |
| **可学习失败 / LEARNING_REASONS** | 世界给的失败，可进记忆（9 类） | `文档/SAFETY_MODEL.md` §4 |
| **闸类失败** | `safety_rejected` / `invalid_params` —— **不可学习**、**不可注入**（不许伪造） | 同上 |
| **ROUTE_REASONS** | "路线相关"的失败：`obstacle_blocked` / `path_invalid` —— **只有它们**会生成"避开这条路"的教训 | `文档/REFLECTION_LOOP.md` §3 |
| **ActionGate** | 新 runtime 的**唯一判决点** | `文档/SAFETY_MODEL.md` §1 |
| **SafetyGate** | **旧** runtime 的闸门（别和 ActionGate 混） | `文档/archive/架构.md` §5 |

**九类 FailReason**：`obstacle_blocked`（障碍阻挡）/ `path_invalid`（路径失效）/ `action_timeout`（超时）/
`localization_error`（定位丢失）/ `battery_low`（电量低）/ `sensor_missing`（缺传感器）/
`executor_failure`（执行器故障）/ `simulator_delay`（模拟器延迟）/ `network_delay`（网络延迟/丢包）。

## 4. 记忆与学习（新）

| 术语 | 一句话 | 定义处 |
|---|---|---|
| **Episodic** | 每次尝试的**原始事件**，成败都记（有分母才算得出失败率） | `文档/REFLECTION_LOOP.md` §1b |
| **Semantic** | 滑窗统计出的**规律** → Planner **软降权**（只改先后，不淘汰） | 同上 |
| **Procedural** | 可执行的**策略**（Lesson）→ Planner **硬避开** | 同上 |
| **Lesson** | 教训；字段 `trigger` / `avoid` / `prefer` / `scope` / `evidence` / `confidence` / `hits` / `status` / `history` | `文档/REFLECTION_LOOP.md` §2 |
| **`hits`** | 支持证据数；反证 `-1`，归零 → `invalidated`（**不删**） | 同上 §5 |
| **反证削弱 / 复核** | 走通曾被避开的路线 → 削弱教训；**连续 2 次**探针成功才削弱（D-02） | 同上 §5 |
| **`revalidate_every`** | 每 N 个 episode 主动试探一次被避开的路线（0 = 不复核） | 同上 §5 |
| **`probe_streak()`** | 当前连续探针成功次数的公开读数出口 | `argos/agent/reflection.py` |
| **`route_ok` vs `episode_ok`** | "这条路顺不顺" vs "任务完成没" —— **两件事**，别用后者当前者 | `文档/REFLECTION_LOOP.md` §1b |
| **软降权 vs 硬避开** | 只改顺序 vs 候选直接消失；本世界规模下**效果相当** | `文档/BENCHMARK.md` §4 |

## 5. 旧 runtime 术语（冻结，读旧文档时会碰到）

| 术语 | 一句话 | 定义处 |
|---|---|---|
| **`book()` 落账口** | 唯一产生 pending_task 的入口，"承诺去执行"必须落账 | `文档/archive/架构.md` §3 |
| **RobotExecutor** | 执行器协议：`move_to` / `navigate` / `grab` / `release` / `pose` / `estop` | `文档/archive/架构.md` §4 |
| **RobotBackend** | 大脑 → 执行器的桥，**过闸不可绕过** | 同上 |
| **运动原语白名单** | `ALLOWED_MOTION_ACTIONS`；禁触字段递归扫描 | `文档/archive/架构.md` §5 |
| **SimEntity / MujocoEntity / DdsEntity / RealSportEntity** | 四种执行器：瞬移 / 真物理不会走 / 低层 trot 会真走 / 高层 SportClient 等真机 | `文档/archive/架构.md` §4 |
| **LinkWatchdog** | 链路看门狗：断线收速，**跳闸不自动恢复** | `文档/archive/架构.md` §5.1 |
| **TickTracker** | 健康门：看"循环有没有跟上"，不是"进程还活着" | `文档/Console_使用说明.md` §4.3 |

## 6. Benchmark 术语

| 术语 | 一句话 |
|---|---|
| **场景（scenario）** | 一个世界变体（障碍位置 / 路线偏好 / 失败类型 / 感知配置参数化生成）。现 **35 个**，见 `文档/BENCHMARK.md` |
| **臂 / 配置（config）** | 一组记忆+反思开关：`planner_only` / `semantic_only` / `memory_only` / `reflection_only` / `memory_reflection` / `memory_reflection_revalidate`（**现 6 组**） |
| **靶场景族** | 专为验证某个机制设计的场景（如 `two_strikes_then_clear_*` 验"连撞两次后环境恢复"） |
| **预算宽 / 紧** | 单次运行的动作额度够不够换路救回来 —— **决定复核是赚是亏** |
| **负结果臂** | 故意留的对照臂（`reflection_only`），打平就说明"反思没带来价值" |

> 臂数与场景数会变，**不要从本文档抄数** —— 以 `文档/BENCHMARK.md` 表头为准。
> 参数敏感度看 `文档/SWEEP.md`（同为生成物）。
