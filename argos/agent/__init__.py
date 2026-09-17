"""ArgOS Agent Runtime —— 与具体机器人无关的具身智能体运行时。

设计红线：
  * Brain / Planner / Memory / Reflector **只依赖本包里的抽象**，不依赖任何具体机器人；
  * 真实 embodiment 只能通过 `EmbodimentBackend` 协议接入；
  * 现在唯一的 embodiment 是 **Simulator**（见 `argos/backends/simulator_backend.py`）——
    它是**仿真器，不是真机**。未来接 Go2 时只需新增 `Go2Backend`，上层零改动。

本包内文件：
  interfaces.py   全部抽象（Observation/Action/ActionResult/WorldState/Lesson/...)
  gate.py         ActionGate：能力驱动的动作闸门（所有动作出口之前）
  planner.py      Planner：plan / replan
  reflection.py   失败 → Lesson
  memory_agent.py Lesson 存取
  brain.py        AgentBrain：只吃抽象
"""
