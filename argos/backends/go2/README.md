# `argos/backends/go2/` —— 真机 backend 规范（**此处只有规范，没有实现**）

## 状态：未实现（这是有意为之）

本项目**当前没有任何真实机器人硬件**。这个目录里**只有这份规范**，
不放"看起来能跑"的真机代码 —— 因为那属于**伪造 real executor**（项目红线）。

验证这条红线：

```bash
$ python -m argos.run --backend go2
backend=go2  goal='去充电站'  seed=42  episodes=3
错误：没有名为 'go2' 的 backend。当前可用：simulator。
  说明：'go2' 尚未实现 —— 本项目**当前没有真实机器人硬件**，也不会写一个假的真机 backend 来冒充完成。规划见 文档/ROADMAP.md。
$ echo $?
2
```

**这个行为是正确的，不要"修"它。**

## 未来要在这里放什么

```
argos/backends/go2/
├── README.md        ← 本文件（规范）
├── __init__.py      ← 导出 build_go2_backend
├── backend.py       ← Go2Backend：实现 EmbodimentBackend 的四个方法
├── sdk_adapter.py   ← 厂商 SDK 的唯一接触面（认知层永远不许 import SDK）
└── errors.py        ← 厂商错误码 → FailReason 的映射表
```

## 四条硬约束（详见 `文档/FUTURE_ROBOT_BACKEND.md`）

1. **只依赖** `argos.agent.interfaces` + 厂商 SDK。不许 import 入口层、不许 import `argos.sim.*`。
2. **复用同一个 `ActionGate`**：可以加严（更小边界 / 更低速度上限），**不许放宽或绕过**。
3. **缺数据必须 fail-closed**：取不到位姿/电量就进 `Observation.missing`，**不许填默认值冒充**。
   急停要**同时**置闸门与执行器（只置闸门拦不住已经在动的电机）。
4. **不许把认知逻辑写进这里**：路线选择、反思、记忆都属于 `argos/agent/`。

## 完成定义（DoD）

- [ ] `Go2Backend` 实现 `capabilities / observe / apply / estop`
- [ ] 在 `argos/run.py::BACKENDS` 注册 `"go2"`，且 `--list-backends` 能看到
- [ ] 通过 `tests/test_action_gate.py` 的等价断言（闸门行为一致）
- [ ] 通过缺数据 fail-closed 与急停链路测试
- [ ] `capabilities()` 如实声明（做不到的动作**不写进白名单**）
- [ ] 先跑只读模式（只 `observe()`）确认观测可信，再开动作、初始速度压到最低
