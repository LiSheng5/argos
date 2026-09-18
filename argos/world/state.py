"""WorldState 的读写边界（Phase 2）。

两条铁律：
  1. **只有 Backend 能写 WorldState**（`touch()` 让 version 自增，可审计）；
  2. **Planner / Brain 只能拿到 `WorldView`**（frozen 投影，改就抛错）。

旧系统在这里的病是"状态散在四处、谁都能改"（见 `文档/SIM_FIRST_AUDIT.md` §4）。
这里用类型把这个边界钉死：dict→tuple、可变→frozen。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from argos.agent.interfaces import Observation, Pose, WorldState

__all__ = ["WorldState", "WorldView", "view", "from_observation", "bump"]


@dataclass(frozen=True)
class WorldView:
    """WorldState 的**不可变快照**，Planner / Brain 只能吃这个。

    字典一律降级为元组：拿到手就改不了，也就不存在"顺手改世界"。
    """
    robot: Pose = Pose()
    battery: float = 100.0
    obstacles: Tuple[Tuple[str, Any], ...] = ()
    objects: Tuple[Tuple[str, Any], ...] = ()
    locations: Tuple[Tuple[str, Pose], ...] = ()
    people: Tuple[Tuple[str, Any], ...] = ()
    events: Tuple[str, ...] = ()
    tasks: Tuple[str, ...] = ()
    sim_time: float = 0.0
    version: int = 0
    #: 本轮没读到的传感器名（缺数据时 Planner 也看得到，别让它以为一切正常）
    missing: Tuple[str, ...] = ()

    def location(self, name: str):
        """按名字取地点；不存在返回 None（不抛、不瞎猜）。"""
        for k, v in self.locations:
            if k == name:
                return v
        return None


def view(state: WorldState) -> WorldView:
    """把可变的 WorldState 投影成不可变的 WorldView。"""
    return WorldView(
        robot=state.robot,
        battery=state.battery,
        obstacles=tuple(sorted(state.obstacles.items())),
        objects=tuple(sorted(state.objects.items())),
        locations=tuple(sorted(state.locations.items())),
        people=tuple(sorted(state.people.items())),
        events=tuple(state.events),
        tasks=tuple(state.tasks),
        sim_time=state.sim_time,
        version=state.version,
        missing=tuple(state.missing),
    )


def from_observation(obs: Observation) -> WorldState:
    """Observation → WorldState（**只在初始化 backend 时用**，之后 WorldState 才是真源）。"""
    return WorldState(
        robot=obs.robot_pose,
        battery=obs.battery,
        obstacles=as_dict(obs.obstacles),
        objects=as_dict(obs.objects),
        locations=dict(obs.locations),
        people=as_dict(obs.people),
        events=list(obs.events),
        tasks=list(obs.tasks),
        sim_time=obs.sim_time,
        version=obs.version,
        missing=tuple(obs.missing),
    )


def as_dict(items) -> Dict[str, Any]:
    """把一批对象 / (名字, 值) 对转成 WorldState 用的字典。

    **所有写入口子都必须走这里** —— 踩过的坑：感知层把传感器返回的 tuple 直接写进
    `state.obstacles`，而 `view()` 期待的是 dict（要调 `.items()`），一读就炸。
    转换只放在一处，就不会再出现"某种数据源写进去的形状不对"。
    """
    items = tuple(items or ())
    if items and isinstance(items[0], tuple) and len(items[0]) == 2:
        return dict(items)
    return dict(zip(_names(items), items))


def _names(items) -> List[str]:
    """给一批对象生成稳定名字（有 name 用 name，没有用 `obj#i`）。"""
    out = []
    for i, it in enumerate(items):
        n = getattr(it, "name", None)
        out.append(str(n) if n else f"obj#{i}")
    return out


def bump(state: WorldState, **changes) -> None:
    """写入并 bump 版本号 —— backend 唯一的写口子。"""
    for k, v in changes.items():
        setattr(state, k, v)
    state.touch()
