# 架构借鉴清单 · Microduck → ArgOS

> 来源：2026-09-13 调研 Pollen Robotics / Hugging Face 的开源双足机器鸭 **Microduck**。
> 性质：**外部参考带来的改造待办**（不是缺陷修复，不阻塞现有功能）。
> 红线：只做「观测 / 健壮性」增强，**不改 brain / safety / executor 逻辑**（与 Web Console 不侵入原则一致）；
> 不新增第三方依赖；缺数据仍一律 `null`。

---

## 为什么值得抄

Microduck 与 ArgOS 同样是「下层控制环 + 上层指令面」的分层，但它在**故障隔离与可观测性**上做得更狠。

| Microduck 的硬约束 | ArgOS 现状 | 差距 |
|---|---|---|
| 健康门看「循环有没有跟上频率」，不是「进程还活着」 | `/api/system/health` 恒返回 `{"status":"ok"}`（`web/api.py:51-53`）；tick 循环无耗时统计 | ❌ 现有健康检查是空壳 |
| 跨进程只读 last-value 缓存，控制环绝不同步 RPC | 每个读端点实时调 `executor.pose()`（`web/telemetry.py:19-25`）；同一次请求可能读到两帧 | ⚠️ 已用 `to_thread` 解阻塞，但无缓存、无一致快照 |
| 配置/升级进程不依赖控制进程（控腿挂了还能改 Wi-Fi） | 单进程；`tick_sink` 异常已隔离；急停不抢锁 | ⚠️ 方向对，但读端点无超时保护，executor 卡死会挂住 HTTP |

---

## TODO 1 · 让健康检查说真话（看循环，不看进程）

**现状**：`/api/system/health` 只回 `{"status": "ok", "ts": ...}`；
`argos/server.py::_tick_loop` 只管 `await asyncio.to_thread(brain.tick)` + sleep，**不记耗时**。
真机上若 executor 卡死或 tick 越来越慢，界面**没有任何信号**——这正是 Microduck 用"健康门"防的事。

- [x] **1.1** `_tick_loop` 记录每帧耗时（`perf_counter`）与"最近一帧完成时间"，维护环形缓冲（建议最近 60 帧）。
  - 验收：能读出 `lastTickAt` / `lastFrameMs` / `slowFrames`（耗时 > interval 的帧数）。
- [x] **1.2** `/api/system/health` 返回真实状态：
  `{status: ok | degraded | stalled, lastTickAgeMs, lastFrameMs, slowFrames, estop}`
  - 判据：`age > 3×interval` → `stalled`；`slowFrames > 0` → `degraded`；否则 `ok`。
  - 验收：注入慢 tick（测试里用会 sleep 的假 executor）→ 状态如实变 `degraded` / `stalled`。
- [x] **1.3** Console 顶部（Overview）显示大脑健康徽标；`stalled` 时显著告警。
  - 验收：停掉 tick 或喂慢 executor → 前端 5 秒内可见告警。

> **完成记录（2026-09-13）**：1.1 / 1.2 已落地 ——
> 新增 `argos/web/health.py::TickTracker`（环形 60 帧、时钟可注入、线程安全）；
> `server._tick_loop` 每帧记耗时（鸭子类型 `record()`，**不 import web 层**）；
> `/api/system/health` 返回 `{status, lastTickAgeMs, lastFrameMs, avgFrameMs, intervalMs, slowFrames, window}`，
> 另加 **`idle`** 态（没跑过帧不谎报 ok）；未挂 tracker 时保持旧形状（回归钉）。
> 测试：`tests/test_tick_health.py`（9 例，含「tick 循环真的在喂 tracker」接线钉）。
> **1.3 待做**（UI 调性，先与用户对齐）。

> **1.3 完成（2026-09-13，用户定调「和原来一个风格」）** —— 全程沿用现有 `Pill + Dot` 写法：
> - 后端：`Console.health()` 把 tracker 状态透出；`ws.py` 新增 `system.health` 一路，
>   与 telemetry 同频 **1Hz 推送**（WS 为主，不是轮询）；`gateway` 把 tracker 同时交给 Console 与 tick 循环。
> - 前端：`store` 收 `system.health`（首次填充走 `api.health()`）；Overview 的 Hero 区在
>   System Online 旁加一枚同风格徽标 —— `Tick 正常 / Tick 变慢 / 大脑无响应 / Tick 未启动 / 健康未知`；
>   非正常状态再补一行说明（距上一帧多少秒、慢帧几次）。
> - 测试：`test_tick_health.py` 加 2 例（`Console.health()` 透传四态 / 无 tracker → unknown）。

## TODO 2 · 读端点吃 last-value 缓存（同一帧的一致快照）

**现状**：`telemetry.py::_safe_pose` 每次调用都 `brain.backend.observe()` → `executor.pose()`；
`robot_state()` 与 `telemetry()` 还各读一次 → **同一次请求里可能读到两个不同帧**（真机上 pose 是会动的）。

- [x] **2.1** `Console.tick_sink()` 每帧把 `observe()` 结果缓存成 `last_state`（带 `ts`）。
  - 验收：缓存含 `pose` + `ts`，且**纯存快照、不调 brain**。
- [x] **2.2** `robot_state()` / `telemetry()` 优先读缓存；过期（>`stale_after`，建议 2×interval）才回落实时读。
  - 验收：连续两次调用返回**同一份快照**（时间戳一致），且不触发额外 `executor.pose()`。
- [x] **2.3** 缓存内容照旧守诚实边界：缺的字段仍是 `None`（不因为加了缓存就补假值）。
  - 验收：`temperature` / `cpu` / `memory` 仍为 `null`。

> **完成记录（2026-09-13）**：2.1 / 2.2 / 2.3 已落地 ——
> `Console._refresh_state()` 每帧写 `_last_state`（observe 在锁外、写锁内，守住 AB-BA 前提）；
> `state_snapshot()` 带锁读；`robot_state()/telemetry()` 传 `pose=` / `runtime_state=` 走快照。
> **踩到的坑**：`brain.status()` 内部**也带一次 `observe()`** —— 光传 pose 不够，
> 状态名也得由调用方给（`runtime_state`），否则读端点照样去戳执行器。
> 测试：`test_read_isolation.py` 的 `CountingEntity` 用例（读完后 `pose_calls` 不增）。

## TODO 3 · 观测层不能把 HTTP 拖死（隔离的最后一段）

**现状**：上轮已把只读端点改成 `to_thread`（防阻塞事件循环）；但 `to_thread` 只是把阻塞挪走，
**executor 若永久卡死，该请求会一直挂着**，前端等不到响应。

- [x] **3.1** 只读端点加超时：`await asyncio.wait_for(asyncio.to_thread(fn), timeout=2.0)`，
  超时返回上一次缓存 / 降级状态（HTTP 200 + `stale: true`），**不返回 500**。
  - 验收：测试注入 `sleep(10)` 的假 executor → 端点 2s 内返回降级结果。
- [x] **3.2** 急停路径永远不受影响（回归钉）：即便读端点被卡，`POST /api/safety/estop` 仍立即返回。
  - 验收：新增测试钉住（与既有 `test_estop_and_tick` 同思路）。
- [x] **3.3** 把「哪些回调必须异常隔离」列成检查清单（`tick_sink` / EventBus 订阅者 / WS 推送 / 缓存写入），逐条确认。
  - 验收：清单落文档，每条有对应代码位置。

---

> **完成记录（2026-09-13）**：3.1 / 3.2 / 3.3 已落地 ——
> `api._read_or()` 把 `to_thread` 包进 `asyncio.wait_for`（默认 2s，`ARGOS_READ_TIMEOUT` 可配），
> 超时/异常 → 降级骨架（HTTP 仍 200）；新增 `telemetry.offline_state()`（连接断开、数据全 null）。
> 回归钉：执行器卡死时急停端点仍 < 1s 返回。
>
> **⚠️ 两个测量陷阱（都踩过，写下来省得再踩）**：
> 1. **TestClient 是同步封装**，请求收尾会等那个"被取消、却仍在跑"的 to_thread 线程，
>    端到端耗时被放大成 executor 的完整卡顿时长（实测 0.2s 超时 → 1.5s 端到端）。
>    → **别用 TestClient 的端到端耗时度量超时**，要直接测 `_read_or`。
> 2. **`asyncio.run` 收尾会 join 默认线程池**（`shutdown_default_executor`），
>    在外面量耗时同样会等到慢读跑完 → 要在 loop **内部**量。
>
> **3.3 回调异常隔离清单（逐条核对过代码位置）**：
>
> | 回调 | 位置 | 隔离方式 |
> |---|---|---|
> | tick 事件 sink | `server._tick_loop` | try/except + 打印 |
> | 健康追踪写入 | `server._tick_loop` | try/except（写失败不影响大脑） |
> | 事件总线订阅者 | `web/events.py` | 发布时复制列表 + 逐个 try/except |
> | WS 推送 | `web/ws.py::broadcast` | 单连接异常 → 摘掉该连接 |
> | 快照刷新 | `web/bridge.py::_refresh_state` | observe 失败 → 保留上一次快照 |
> | 遥测读取 | `web/telemetry.py::_safe_pose` / `_status` | 各自 try/except → 空值 |

## 优先级与前置条件

| TODO | 现在就能做？ | 依赖 | 价值 |
|---|---|---|---|
| 1.1 / 1.2 | ✅ | 无 | 真机上唯一的「大脑还活着吗」信号 |
| 1.3 | ✅ | 1.2 | 界面可见 |
| 2.1 / 2.2 / 2.3 | ✅ | 无（只改 web 层） | 真机 `pose()` 阻塞不再影响读接口 |
| 3.1 | ✅ | 2.1（需要降级目标） | 防止 HTTP 被拖死 |
| 3.2 | ✅ | 无 | 安全兜底 |
| 3.3 | ✅ | 无 | 防回归 |

## 明确不做

- **不拆多进程**：Microduck 的 `configd` / `updaterd` 分离是为"量产固件升级"设计的，ArgOS 是单机研究项目，收益不抵成本。
- **不动执行器 / 通信层**：这是借鉴清单，不是重构计划。
- **不为"界面上多几个指标"编造温度 / CPU / 延迟**——缺数据仍是 `null`。
