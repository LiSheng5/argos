# REFLECTION_LOOP —— 反思闭环：失败如何变成下一次不同的计划

> 本文对着代码写（`argos/agent/{reflection,memory_agent,planner,brain}.py`），
> 每个机制后面都标了实现位置；**改了代码请同步改这里**。
> 实测数据见 `文档/BENCHMARK.md`；文献对照见 `文档/经验学习_相关方案调研.md`。

---

## 1. 闭环长什么样

```
Goal → Planner.plan() ──读──> LessonStore.active()   ← 反思产物在这里被**消费**
   ↓
ActionProposal → SafetyGate → SimulatorBackend → ActionResult(reason)
   ↓
  失败？
   ├─ 是 SAFETY_REJECTED / INVALID_PARAMS → **不学**（不是世界给的经验）
   ├─ 是真实失败 → Reflector.record_failure()
   │        ↓（同一 episode 内同类失败只算 1 条独立证据）
   │     Reflector.consolidate() → hits ≥ min_hits 且 confidence ≥ 0.6 → 产出 Lesson
   │        ↓
   │     LessonStore.add(lesson)   ← 写
   └─ Planner.replan() → 换一条路线继续（**不是**冷却等待）
```

关键点：**写与读必须落在同一个 store 上**。旧系统的病正是"写在一处、没人读"——
本仓库 benchmark 实测：`reflection_only`（反思只写不读）与完全不做反思，四个指标**逐位相同**。

## 2. 数据结构：一条 Lesson 里有什么

| 字段 | 含义 | 为什么要它 |
|---|---|---|
| `trigger` | 触发场景，如 `route:north` | 决定"什么情况下该想起这条" |
| `avoid` / `prefer` | 避开什么 / 改用什么 | Planner 直接消费；`avoid` 是命中键 |
| `scope` | 适用域，如 `route:north` | 防止"低电量"被学成"北线不能走" |
| `evidence` | 源事实原文（来自 `ActionResult.detail`） | **防编造**：没有证据的教训不该被采纳 |
| `confidence` | 置信度 `hits/(hits+1)`，封顶 0.95 | 随证据增长，但**不假装绝对确定** |
| `hits` | 支持证据数 | 门槛判据 |
| `status` | `active` / `invalidated` | **失效不删除**，保留审计轨迹 |
| `history` | `support@ep1` / `counter_evidence@ep2` / `reinstate@ep9` | 可追溯"怎么学的、怎么推翻的" |
| `created_episode` / `updated_episode` | 时间戳（逻辑时钟） | 判断新鲜度 |

实现：`argos/agent/interfaces.py::Lesson`、`argos/agent/memory_agent.py::LessonStore`

## 3. 写入路径（三条硬约束）

1. **只从"路线相关"的失败里学**（`reflection.py::ROUTE_REASONS` = `OBSTACLE_BLOCKED` / `PATH_INVALID`）。
   低电量、执行器故障会被**统计**，但不会生成"避开这条路"的教训 ——
   因为那**不在路线上**，学出来的就是错误因果。（早期版本会，已修。）
2. **同一次 episode 内的重复失败只算 1 条独立证据**（`Reflector.begin_episode()` + 去重）。
   没有这一步，一次运行里连撞两次就凑满 `min_hits=2`，
   "两次独立尝试才学"这个意图就会落空。
3. **门槛要有**：`min_hits=2` 且 `confidence ≥ 0.6`（`Reflector` 构造参数）。
   实测：门槛是**为了不过度泛化**而存在的 —— 去掉后学得更快，但会把一次偶发当成永久教训。

## 4. 读取路径：Planner 怎么用它

- `AgentBrain.run()` → `self.store.active(self.lesson_threshold)` → `Planner.plan(…, lessons)`；
- `Planner.choose_route()` 跳过被 `lesson.avoid` 命名的路线；
- `Planner.replan()` 失败后换一条**没被点名**的路线（从当前位置出发，不是从头再来）。

⚠️ **读写门槛必须同源**：`AgentBrain.lesson_threshold` 与 `Reflector.min_confidence` 要一致。
踩过的坑：读侧曾硬编码 0.6，把 `memory_only` 的"无门槛"设置架空（写出来 0.5 的教训读不到）。

## 5. 撤销与复核（治"一次偶发被当成永久教训"）

这是本闭环最容易做错的地方。四个机制：

| 机制 | 实现 | 作用 |
|---|---|---|
| **反证削弱** | `LessonStore.weaken()` | 走通了曾被避开的路线 → `hits-1`；归零 → `status="invalidated"`（**不删**） |
| **周期复核** | `Reflector.revalidate_every` + `Planner.plan(probe=True)` | 每 N 个 episode **主动试探**一次被避开的路线，看环境是不是恢复了 |
| **反证后重置证据** | `Reflector.record_success()` | 清空该路线的失败计数 —— 想复活必须**重新积累** min_hits 次独立失败 |
| **复活** | `LessonStore.add()` 检测 `status != active` | 环境又变回去时，失效的教训可重新生效（失效 ≠ 永久作废） |

**实测效果**（靶场景：北线在 ep0/ep1 各被挡一次后恢复；南线是 8 途经点的超长绕路）：

| 配置 | 平均动作数 | 平均失败数 |
|---|---|---|
| 不复核（`memory_reflection`） | 10.80 | 0.40 |
| 每 2 个 episode 复核一次 | **9.20** | 0.40 |

即 **用一次试探买回一条路**，且没多付失败代价。

## 6. 三条"不学"的边界

1. **被闸拒不算经验**：`SAFETY_REJECTED` / `INVALID_PARAMS` 单独枚举，
   `ActionResult.learnable` 为 False → 不记录、不反思、不重试，直接停。
2. **归因本身不可靠**：Who&When（ICML 2025）实测最好的方法定位"决定性错误步骤"只有 **14.2%**。
   所以「这次失败是因为北线」**本质上是个未被验证的假设** ——
   这正是要把"复核/干预验证"做成一等公民的原因，而不是指望把归因做准。
3. **故障必须绑在世界位置上**：`FailureInjector.arm(where=...)`。
   不绑位置的后果实测过：agent 改走绕路后被挡 → 把绕路也记成不能走 → 两条路全禁 → 无路可走。

## 7. 已知限制（照实说）

- 阈值 `min_hits=2` / `confidence ≥ 0.6` 与复核周期 `revalidate_every=2` **都是拍的值**，
  没做扫参（Phase 7.1 待做）。
- **反证削弱是粗糙规则**（成功一次降一级），没考虑"偶然成功一次不代表恢复"。
- 教训只在**进程内存**里，尚无持久化与人工审阅入口。
- 更严谨的方向：把路线选择当**非平稳多臂老虎机**（折扣/滑窗或变点检测），
  而不是二值 `avoid` —— 见 `文档/经验学习_相关方案调研.md` §2。
