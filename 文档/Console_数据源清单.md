# ArgOS Console 数据源清单（Web 开工前盘点 · 2026-09-06）

> 本文件回答 Step 2「列出现有数据源」。
> 原则：**Web 只是 Observation + Control Layer，不重新实现 ArgOS**。
> 下面每一条都来自实际代码（不是架构文档里的设想），"拿不到"的也照实写。

## 1. 现在能拿到的数据

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
| tick 转换事件 | `brain.tick()` → `{started, completed, failed, reflected}` | 每 3s 一帧 | **目前返回即丢，没有留存** —— Run/Event 要新建的根因 |
| 安全闸裁决 | `RobotBackend.apply()` → `(ok, reason)` | 执行时 | **没有历史**，只有当次返回值 |
| 执行器种类 | `ROBOT_EXECUTOR` 环境变量 | 启动时定 | sim / mujoco / dds / real |
| LLM 可用性 | `llm.enabled()`、`llm.base_url`、`llm.model` | 拉 | 只有"有没有 key"，**没有上次调用的结果/耗时** |
| 地点表 | `brain.places` | 静态 | 充电桩 / 家 / 桌边 / 门口 |

## 2. 拿不到的（Web 想要，但现有系统根本不产生）

| 数据 | 现状 | 本项目的处理办法 |
|---|---|---|
| 连接状态 / lastSeen / latency | 无 | sim、mujoco 视为 `connected`；`latencyMs` 恒 null |
| 温度 `temperature` | 无 | 恒 null，UI 显示 `—` |
| CPU / 内存占用 | 无 | 恒 null，UI 显示 `—` |
| Camera 画面 | 无（SDK 里有 `VideoClient.GetImageSample()`，ArgOS 一行没接） | 外部 MJPEG URL / 本机 USB 摄像头；无源时 `No camera signal` |
| Run / Task / Event 历史 | 无 | **新建**（Run Store + Event Bus） |
| 安全闸历史裁决 | 无 | **新建**：在 `backend.apply()` 处埋点记录 |
| 机器人外观图 | 无 | **新建**：用户上传，与 camera 严格分两个字段 |

## 3. 三条边界（写代码时反复对照）

1. **Web 不决策**：编译、落账、安全判定仍在 ArgOS。Web 只把 `text` 交给 `try_command()`，
   拿到 reply 与状态，不自己解释"该做什么动作"。
2. **E-stop / 移动 / 取消任务必须走现有路径**（`brain.estop()` → gate + executor），不另开捷径。
3. **拿不到的数据就是 null**，UI 显示 `—`。**绝不用随机数、占位数字或假 telemetry 充数** ——
   一个会显示假温度的控制台，比没有温度更危险。
