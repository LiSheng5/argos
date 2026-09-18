# SIMULATION —— 仿真里到底模拟了什么

> 一句话：**这是一个用于研究"认知闭环"的玩具世界，不是物理引擎。**
> 它的价值在于"可复现、可注入失败、可测量"，不在于"像真机"。
> 世界几何与状态字段见 `文档/WORLD_MODEL.md`；安全见 `文档/SAFETY_MODEL.md`。

---

## 1. 模拟了什么 / 没模拟什么（照实说）

| 模拟了 | 没模拟 |
|---|---|
| 直线段运动 + 速度 + 停/转/等待/观察 | ❌ 真实动力学（摩擦、惯性、打滑、步态）|
| 电量消耗（按米 + 按秒） | ❌ 电池化学特性 / 温度 / 老化 |
| 矩形障碍 + 采样碰撞 | ❌ 连续体 / 可变形物体 / 斜坡台阶 |
| **逻辑时钟**（`sim_time`）| ❌ 真实墙钟 / 实时约束 / 抖动 |
| 9 类失败 + **可绑世界位置** | ❌ 真实故障分布（注入是我们画的）|
| 6 档网络延迟 + 丢包 | ❌ 真实网络栈 / 重传 / 乱序 |
| 传感器噪声 / 量化 / 探测半径 / 失灵 | ❌ 真实传感器驱动、标定、温漂 |
| 看门狗（心跳/动作/后端超时）| ❌ 进程级失联、硬件看门狗 |

**别拿这个世界的数字当物理结论。** 它能回答的是"认知机制在受控条件下是否成立"。

## 2. 运动与消耗（`argos/sim/mini_entity.py`）

- 动作：`move`（走到指定坐标）/ `turn` / `stop` / `wait` / `inspect`
  （`grab` / `release` 在枚举里，但迷你身体 `has_arm=False` → 闸门直接拒）；
- 移动按 `speed`（米/秒）逐步推进，`dt=0.05s`；
- 途中**采样检测碰撞**：撞到障碍 → **真的不动** + 返回 `OBSTACLE_BLOCKED`（诚实：不假装动了）；
- 电量：`drain_per_m` × 距离 + `drain_per_s` × 时长；
- 时钟是 `sim_time`（逻辑时钟）—— **同 seed 两次运行逐位一致**。

## 3. 延迟剖面（`argos/sim/latency.py`）

| 剖面 | 往返延迟 | 抖动 | 丢包 |
|---|---|---|---|
| `normal` | 50ms | — | — |
| `moderate` | 100ms | — | — |
| `slow` | 300ms | — | — |
| `very_slow` | 1s | — | — |
| `unstable` | 150ms | +250ms | — |
| `packet_loss` | 100ms | +60ms | 30% |

⚠️ 延迟加在**逻辑时钟**上（不做真实 `sleep`），所以"慢网络"下 benchmark 仍然可复现。
丢包 → `NETWORK_DELAY`（**可学习**：它是世界的真实状态）。

## 4. 失败注入（`argos/sim/failure_injector.py`）

9 类（与 `LEARNING_REASONS` 一致）：`obstacle_blocked` / `path_invalid` / `action_timeout` /
`localization_error` / `battery_low` / `sensor_missing` / `executor_failure` /
`simulator_delay` / `network_delay`。

支持：`once`（只触发一次）、`at_step`（第几步）、`on`（限定动作类型）、`probability`（概率）、
**`where`（位置谓词）**。

**`where` 是必须的**：故障属于**世界里的某个位置**，不属于"agent 当时选的那条路"。
不绑位置会怎样？实测：agent 改走绕路时被挡 → 把绕路也记成不能走 → 两条路全被禁 →
`planner` 返回 `None` → 直接无路可走（成功率掉到 20%）。

**闸类失败（`safety_rejected` / `invalid_params`）不可注入** —— 不许伪造"闸拒绝了"。

## 5. 看门狗（`argos/agent/watchdog.py`）

盯三类超时：**心跳**（距上次成功动作多久）、**单次动作**、**后端整体**。
跳闸 → 强制安全停止（清速度）→ 记 `WATCHDOG_TRIGGERED` → **除 STOP 外全拒** → **不自动恢复**
（必须显式 `reset_watchdog()`）。

## 6. 确定性与可复现（本项目的硬要求）

- 随机只从 `seed` 派生的 `random.Random` 来（注入器、传感器、抖动各一条独立流）；
- 不用墙钟、不用真实 `sleep`、不依赖字典序以外的顺序；
- 已钉死的复现测试：同 seed 的仿真步进、延迟/丢包序列、benchmark 全矩阵、参数扫描。

⚠️ **边界**：可复现的前提是**调用序列一致**。额外多调一次 `observe()`
（会消耗一次传感器随机流）就会改变后续噪声 —— 这不是 bug，但写测试时要知道。

## 7. 怎么在这个仿真里做实验

```bash
python -m argos.run --backend simulator --goal "去充电站" --episodes 3
python -m argos.run --input speech --say "麻烦帮我去一下充电站吧"     # 口语入口
python -m argos.benchmark all   --out 文档/BENCHMARK.md               # 24 场景 × 6 臂 × 3 seed
python -m argos.benchmark sweep --out 文档/SWEEP.md                   # 参数敏感度
python -m argos.demo                                                  # 逐步 trace
```

加一个实验（场景）的步骤：在 `benchmark/scenarios.py` 里加 `Scenario`（世界变体 +
`transient_episodes` / `transient_where` / `max_steps`），然后 `benchmark all` 会把它算进去。
