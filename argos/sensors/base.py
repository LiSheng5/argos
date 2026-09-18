"""感知层基础抽象（Wave 3 / 指令 §19）。

为什么要有这一层：`SimulatorBackend.observe()` 原来是**直接读实体**（上帝视角、永远准确）。
这样有两件事测不了：

  1. **传感器会失灵** —— 拿不到数据时 agent 会不会瞎猜？
  2. **感知有范围** —— 看不全的时候，agent 只能靠试错学（这恰好是反思闭环存在的理由）。

⚠️ 诚实约定：**字段仍然带着"最后可用值"，但 `missing` 里会点名不可信的那个传感器。**
消费者（尤其是安全闸）**必须先看 `missing`** —— 闸门对缺数据是 fail-closed 的（见 `ActionGate`）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

__all__ = ["Sensor", "SensorReading", "SensorSuite"]


class Sensor(Protocol):
    """一个传感器：读一次实体 + 世界，返回自己负责的那个观测字段。

    返回 `None` = **这次没读到**（失灵 / 被遮挡 / 超出范围），不是"读到了 None 这个值"。
    """
    name: str
    obs_field: str

    def read(self, entity: Any, world: Any) -> Optional[Any]:  # pragma: no cover - 协议
        ...


@dataclass(frozen=True)
class SensorReading:
    name: str
    obs_field: str
    ok: bool
    value: Any = None


@dataclass
class SensorSuite:
    """一组传感器：按顺序读，产出一份 `字段覆盖表` + `缺失名单`。"""
    sensors: List[Sensor] = field(default_factory=list)

    def add(self, sensor: Sensor) -> "SensorSuite":
        self.sensors.append(sensor)
        return self

    def sense(self, entity: Any, world: Any) -> Tuple[Dict[str, Any], Tuple[str, ...], List[SensorReading]]:
        """返回 `(字段覆盖, 缺失的传感器名, 逐项读数)`。"""
        overrides: Dict[str, Any] = {}
        missing: List[str] = []
        readings: List[SensorReading] = []
        for s in self.sensors:
            value = s.read(entity, world)
            ok = value is not None
            readings.append(SensorReading(name=s.name, obs_field=s.obs_field, ok=ok, value=value))
            if ok:
                overrides[s.obs_field] = value
            else:
                missing.append(s.name)          # 读不到 → 点名，不假装有数据
        return overrides, tuple(missing), readings

    def names(self) -> Tuple[str, ...]:
        return tuple(s.name for s in self.sensors)


def suite_of(*sensors: Sensor) -> SensorSuite:
    return SensorSuite(sensors=list(sensors))
