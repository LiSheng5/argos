# ArgOS Console 使用说明

> ArgOS 的 Web 观察 + 控制层。**它只观测与下发指令，不决策**——
> 编译、落账、安全判定仍在 ArgOS（brain / safety / executor），Web 一行都不复制。

## 一、怎么跑

两个进程，先起后端再起前端（或只起后端，用浏览器直接开 5173）：

```bash
# 1) 后端（127.0.0.1:8766）
python -m argos.web.gateway --executor sim        # 纯逻辑仿真
python -m argos.web.gateway --executor dds        # 物理仿真 / DDS（会真走）

# 2) 前端（localhost:5173，自动代理 /api 到 8766）
cd console
npm install
npm run dev
```

旧的 `python -m argos.server` 入口完全不受影响。

## 二、页面

| 页 | 干什么 |
|---|---|
| Overview | Hero + 你的机器人图 + 实时相机 + Brain/Safety/Robot 三状态 + Latest Activity + 发起 Run |
| Runs | 所有 Run（用户指令 + 自主日常），点进去看八节流水线 |
| Run Detail | User Command → Brain → LLM → Safety → Task → Executor → Robot → Result |
| Robot | 上传 / 替换 / 删除机器人外观图，看实时位姿与遥测 |
| Memory | 搜记忆卡（recency + relevance + importance 加权） |
| Playground | Direct LLM（纯对话）或 ArgOS Brain（真的落账执行） |
| Settings | 填 API key（只存本地 api_key.txt）、配相机源、机器人 Profile |

## 三、几个关键设计（诚实优先）

1. **机器人外观图 ≠ 相机**：`robot_profile.imageUrl`（你上传）和
   `robot.camera_stream`（实时）是两个字段，永不混用。
2. **拿不到的数据就是 —**：温度 / CPU / 延迟目前执行器不上报，UI 显示 — ，
   不造数。
3. **LLM 不是 Run 的必经环节**：真实链路是 规则编译 → 落账 → 安全闸 → 执行，
   LLM 只做措辞。Run Detail 里 LLM 一节会如实标 skipped（未配 key）。
4. **所有控制过 SafetyGate**：E-stop / 移动 / 取消都走现有 `brain.estop()` /
   `RobotBackend.apply()`，Web 没有捷径。

## 四、架构（本节是 Console 设计的**单一信息源**）

**定位：Web 只观测与下发指令，不决策。** 编译、落账、安全判定仍在 ArgOS，
Web 一行都不复制。所有真实控制（E-stop / 移动 / 取消）必须走现有 SafetyGate。

```
Robot(执行器) ─→ ArgOS Runtime ─→ Event Bus ─┬─→ Run Store(SQLite)
                                             └─→ WS Gateway ─→ 浏览器
浏览器 ──HTTP──→ /api/runs ──→ Console.submit ──→ brain.try_command（唯一入口）
```

⚠️ **本界面服务的是旧运行时**（`brain` / `safety` / `executor`）。
2026-09 新增的 SIM-first Runtime（`argos/agent/` 那套，含 benchmark / 感知 / 反思闭环）
**没有接进这个界面** —— 它有自己的 CLI：`python -m argos.run` / `argos.benchmark` / `argos.demo`。

一句话概括：**不改 brain / safety / executor 内部逻辑** —— 安全闸裁决靠包装
`brain.backend`，tick 靠 `server.py` 多带一个可选 sink 回调，指令靠 Web 层自己包
`try_command`。

### 4.1 埋点方式：包一层，不进去改

| 想观测 | 手段 | 侵入性 |
|---|---|---|
| 安全闸裁决 | 把 `brain.backend` 换成 `InstrumentedBackend`（转发 + emit，**返回值原样透传**） | 包装，原对象不动 |
| tick 状态转换 | `server.py` 的 `_tick_loop` 多带一个可选 `sink` 回调 | 加默认 None 参数，旧行为逐字等价 |
| 用户指令 | Web 层包装 `try_command`（只调一次，调两次会污染记忆卡） | 无 |
| 记忆变化 | sink 里比对记忆条数 | 无 |

### 4.2 三条诚实边界

见本文件 **§三**，不在这里重复。

### 4.3 健康门 + 读端点隔离（2026-09-13，借鉴 Microduck 板端设计）

三条来自 Pollen Robotics **Microduck**（软件栈 Apache-2.0）板端运行时的硬约束，落到 ArgOS 的对应实现
（**只加观测/健壮性，不改 brain / safety / executor**）：

| Microduck 的约束 | ArgOS 的实现 | 位置 |
|---|---|---|
| 健康门看「循环有没有跟上频率」，不是「进程还活着」 | `TickTracker`（环形 60 帧、时钟可注入、线程安全），`_tick_loop` 每帧记耗时 | `web/health.py` / `server.py` |
| 控制环绝不同步 RPC，跨进程只读 last-value 缓存 | `Console._refresh_state()` 每帧写一份快照，读端点优先吃快照、过期（2×interval）才回落实时读 | `web/bridge.py` |
| 观测层不能把控制层拖死 | 只读端点 `asyncio.wait_for(to_thread(fn), 2s)` → 超时降级（HTTP 仍 200 + 离线骨架），**不返回 500** | `web/api.py::_read_or` |

- `/api/system/health` 返回真实状态：`{status, lastTickAgeMs, lastFrameMs, avgFrameMs, intervalMs, slowFrames, window}`。
  判据：`age > 3×interval` → `stalled`；`slowFrames > 0` → `degraded`；**没跑过帧 → `idle`（不谎报 ok）**；否则 `ok`。
  未挂 tracker 时保持旧形状（回归钉守着）。
- WS 新增 `system.health` 一路，与 telemetry 同频 **1Hz 推送**（WS 为主，不轮询）；
  Overview 复用既有 `Pill + Dot` 显示五态：`Tick 正常 / Tick 变慢 / 大脑无响应 / Tick 未启动 / 健康未知`。
- 读超时阈值 `ARGOS_READ_TIMEOUT` 可配（默认 2s）。**急停路径不在这条路上** ——
  读端点被卡死时 `POST /api/safety/estop` 仍 < 1s 返回（回归钉）。
- ⚠️ **两个测量陷阱**（踩过，别再用错口径量超时）：`TestClient` 是同步封装，请求收尾会等那个
  "已取消却仍在跑"的 to_thread 线程；`asyncio.run` 收尾会 join 默认线程池。
  → 量超时**直接测 `_read_or`**，或在 loop **内部**量。
- 超时/异常一律降级为 `telemetry.offline_state()`（连接断开、数据全 null），**不补假值**（诚实边界不变）。
- 回调异常隔离清单（逐条核对过代码位置）：tick sink / 健康追踪写入 / EventBus 订阅者 /
  WS 推送 / 快照刷新 / 遥测读取 —— 全部 try/except，坏一个不影响大脑。

> 启动方式见 **§一**（不在这里重复）。

## 五、测试

```bash
python -m pytest tests -q -p no:cacheprovider
# 与 Console 相关的三个文件：test_web_console.py（10）旧端点不回归 / Run 全链路 /
# 急停过闸 / 坏图拒绝 / WS 快照 / 缺传感器=null；test_tick_health.py（11）健康门四态 + 接线钉；
# test_estop_and_tick.py（6）急停到达执行器 / tick 不阻塞事件循环。
# ⚠️ 总数不写在这里 —— 测试基线唯一权威源是 文档/测试基线.md（写死会过期）。
```

## 六、数据从哪来（能拿到 / 拿不到）

> 原则：**Web 只是 Observation + Control Layer，不重新实现 ArgOS**。
> 下面每一条都来自实际代码（不是架构设想），"拿不到"的也照实写。

### 6.1 现在能拿到的

| 数据 | 来源（代码位置） | 获取方式 | 备注 |
|---|---|---|---|
| 位姿 x / y / yaw | `executor.pose()` | 拉模式 | **唯一真源**，四种执行器都走它 |
| 电量 `battery_pct` | 同上 | 拉 | sim / mujoco 恒 100；**真机高层 sportmode 没有电量** → 字段可能整个缺失 |
| 急停 `estop` | `pose()['estop']` 与 `brain.backend.gate.estop` | 拉 | 两处可能不同步，**以 gate 为准**（gate 才是拒单的那个） |
| 夹爪 `gripper` | `pose()['gripper']` | 拉 | dds / real 上 grab/release 恒 False（没装手臂） |
| 大脑状态 | `brain.status()` → `state / tick / activity / pending / estop / pose` | 拉 | `state` ∈ idle / working / resting |
| 记忆全量 | `brain.memory` | 拉 | `List[Dict]`，JSON 可编辑 |
| 记忆检索 | `recent(n)` / `recall(query, top_k)` | 拉 | recency + BM25 + importance 加权 |
| 命令回复 | `brain.try_command(text)` → `str` | 请求时 | 已含 LLM 措辞或规则兜底 |
| tick 转换事件 | `brain.tick()` → `{started, completed, failed, reflected}` | 每 3s 一帧 | 原本返回即丢（Run/Event 要新建的根因），现由 Event Bus 留存 |
| tick 健康 | `web/health.py::TickTracker` | 拉 + WS 1Hz | `lastTickAgeMs / lastFrameMs / avgFrameMs / slowFrames / window` |
| 安全闸裁决 | `RobotBackend.apply()` → `(ok, reason)` | 执行时 | 历史由 `InstrumentedBackend` 埋点留存 |
| 执行器种类 | `ROBOT_EXECUTOR` 环境变量 | 启动时定 | sim / mujoco / dds / real |
| LLM 可用性 | `llm.enabled()`、`llm.base_url`、`llm.model` | 拉 | 只有"有没有 key"，**没有上次调用的结果/耗时** |
| 地点表 | `brain.places` | 静态 | 充电桩 / 家 / 桌边 / 门口 |

### 6.2 拿不到的（Web 想要，但现有系统根本不产生）

| 数据 | 现状 | 处理办法 |
|---|---|---|
| 连接状态 / lastSeen / latency | 无 | sim、mujoco 视为 `connected`；`latencyMs` 恒 null |
| 温度 `temperature` | 无 | 恒 null，UI 显示 `—` |
| CPU / 内存占用 | 无 | 恒 null，UI 显示 `—` |
| Camera 画面 | 无（SDK 里有 `VideoClient.GetImageSample()`，ArgOS 一行没接） | 外部 MJPEG URL / 本机 USB 摄像头；无源时 `No camera signal` |
| Run / Task / Event 历史 | 无 | 新建（Run Store + Event Bus） |
| 安全闸历史裁决 | 无 | 新建：在 `backend.apply()` 处埋点记录 |
| 机器人外观图 | 无 | 新建：用户上传，与 camera 严格分两个字段 |
