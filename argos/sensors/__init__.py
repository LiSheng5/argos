"""感知层（Wave 3 / 指令 §19）—— **全部是模拟传感器**，不接任何真实硬件驱动。

目的不是"多一层"，而是让两件原本测不了的事变得可测：

  1. **传感器会失灵** → `Observation.missing` 点名不可信的字段，安全闸对缺数据 **fail-closed**；
  2. **感知有范围** → 看不见远处障碍时，agent 只能**撞上去才知道** ——
     这正是反思闭环存在的直接理由。

对外入口：`argos.sensors.simulated.simulated_suite(...)`。
"""
from argos.sensors.base import Sensor, SensorReading, SensorSuite, suite_of
from argos.sensors.simulated import (
    SimBatterySensor,
    SimObstacleSensor,
    SimPoseSensor,
    SimVisionSensor,
    simulated_suite,
)

__all__ = [
    "Sensor", "SensorReading", "SensorSuite", "suite_of",
    "SimPoseSensor", "SimBatterySensor", "SimObstacleSensor", "SimVisionSensor",
    "simulated_suite",
]
