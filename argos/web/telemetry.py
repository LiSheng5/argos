"""Robot Telemetry（Step 6）：把现有 ArgOS 的状态翻译成统一 RobotState。

诚实边界（写死在这，别到时候手滑）：
  现有执行器的 pose() 只给 x / y / yaw / battery_pct / estop / gripper 六个字段。
  **没有温度、没有 CPU、没有内存占用、没有链路延迟**。这些在模型里是
  Optional，这里一律填 None → JSON null → 前端显示 "—"。
  不要为了"看起来完整"编几个数字进去：一个会显示假温度的控制台，
  比老老实实写着"没有这个传感器"危险得多。
"""
from __future__ import annotations

from typing import Optional

from argos.web.models import (BrainState, Connection, Pose, RobotProfile,
                              RobotState, Runtime, SafetyState,
                              SafetyDecision, now, to_dict)


def _safe_pose(brain) -> tuple:
    """取 pose；执行器抽风时不要带塌整个状态接口。"""
    try:
        pose = brain.backend.observe() or {}
        return pose, True
    except Exception:
        return {}, False


def robot_state(brain, profile: Optional[RobotProfile] = None,
                pose: Optional[dict] = None,
                runtime_state: Optional[str] = None) -> dict:
    """需求 §15 的统一模型。5–10Hz 推。

    pose / runtime_state 可由调用方传入（Console 的 last-value 快照与状态）：
    给了就不碰执行器 —— 注意 `brain.status()` 内部**也带一次 `observe()`**，
    正是要绕开的那个调用，所以状态名也请调用方直接给。None → 走旧行为。
    """
    if pose is None:
        pose, ok = _safe_pose(brain)
    else:
        ok = True
    if runtime_state is None:
        runtime_state = str(_status(brain).get("state", "unknown"))
    estop = bool(getattr(brain.backend.gate, "estop", False))
    return to_dict(RobotState(
        robotId=(profile.id if profile else "ARGOS-01"),
        connection=Connection(
            status="connected" if ok else "disconnected",
            lastSeen=now() if ok else None,
            latencyMs=None,                       # 现有系统不测量，不给假数
        ),
        runtime=Runtime(state=str(runtime_state)),
        battery=_as_float(pose.get("battery_pct")),
        pose=Pose(x=float(pose.get("x", 0.0) or 0.0),
                  y=float(pose.get("y", 0.0) or 0.0),
                  z=None,
                  yaw=_as_float(pose.get("yaw"))),
        temperature=None,                         # 没有这个传感器
        cpu=None,                                 # 同上
        memory=None,                              # 同上
        gripper=pose.get("gripper") or None,
        estop=estop,
        updatedAt=now(),
    ))


def offline_state(brain, profile: Optional[RobotProfile] = None) -> dict:
    """读超时 / 执行器不响应时的诚实骨架：连接断开、数据一律 null。

    与「缺传感器 = null」同一个原则：拿不到就说拿不到，不编一个数字出来。
    """
    return to_dict(RobotState(
        robotId=(profile.id if profile else "ARGOS-01"),
        connection=Connection(status="disconnected", lastSeen=None,
                              latencyMs=None),
        runtime=Runtime(state="unknown"),
        battery=None,
        pose=None,
        temperature=None,
        cpu=None,
        memory=None,
        gripper=None,
        estop=False,
        updatedAt=now(),
    ))


def telemetry(brain, pose: Optional[dict] = None) -> dict:
    """慢变量，1Hz 推。现在只有电量是真数据。pose 语义同 robot_state。"""
    if pose is None:
        pose, _ = _safe_pose(brain)
    return {
        "battery": _as_float(pose.get("battery_pct")),
        "temperature": None,
        "cpu": None,
        "memory": None,
        "ts": now(),
    }


def brain_state(brain, executor_kind: str = "sim") -> dict:
    st = _status(brain)
    llm = getattr(brain, "llm", None)
    return to_dict(BrainState(
        state=str(st.get("state", "idle")),
        status="busy" if st.get("state") == "working" else "ready",
        tick=int(st.get("tick", 0) or 0),
        activity=str(st.get("activity", "") or ""),
        pending=str(st.get("pending", "") or ""),
        executor=executor_kind,
        llmEnabled=bool(llm is not None and llm.enabled()),
        memoryCount=len(getattr(brain, "memory", []) or []),
    ))


def safety_state(brain, last_decision: Optional[SafetyDecision] = None) -> dict:
    gate = brain.backend.gate
    estop = bool(getattr(gate, "estop", False))
    return to_dict(SafetyState(
        estop=estop,
        status="tripped" if estop else "active",
        gates={
            "estop": not estop,
            "battery": True,          # 由 check() 判定，这里只反映"门在不在"
            "workspace": True,
            "policy": True,
        },
        boundaries=dict(getattr(gate, "boundaries", {}) or {}),
        lastDecision=last_decision,
    ))


def _status(brain) -> dict:
    try:
        return brain.status() or {}
    except Exception:
        return {}


def _as_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
