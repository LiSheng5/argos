"""Web 层数据模型（Step 3）。

设计取舍：
  1. 字段一律 camelCase（dataclass 直接 asdict 成 JSON，前端不用转换）；
  2. **拿不到的数据就是 None**，不做默认值填充 —— 现有执行器根本没有
     温度/CPU/延迟，填 0 或填随机数都是造假，UI 上显示 "—" 才是诚实的；
  3. Run 的阶段用 List[Stage] 而不是八个固定字段：现有链路里 LLM 不是必经
     环节（只在措辞时调用），用列表才能让某一节显示 "skipped/未调用"。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def now() -> float:
    return time.time()


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def to_dict(obj: Any) -> Dict:
    """dataclass → JSON 友好的 dict（None 保留为 null，由前端决定怎么显示）。"""
    return asdict(obj)


# ── 机器人身份（用户上传的外观图，与 camera 严格分开）──────────

@dataclass
class RobotProfile:
    """机器人档案。**imageUrl 是外观图**，不是实时画面。"""
    id: str = "ARGOS-01"
    name: str = "ARGOS-01"
    imageUrl: Optional[str] = None
    updatedAt: Optional[float] = None


# ── 机器人实时状态 ────────────────────────────────────

@dataclass
class Connection:
    status: str = "disconnected"          # connected | disconnected
    lastSeen: Optional[float] = None
    latencyMs: Optional[float] = None     # 现有系统没有 -> null


@dataclass
class Pose:
    x: float = 0.0
    y: float = 0.0
    z: Optional[float] = None
    yaw: Optional[float] = None


@dataclass
class Runtime:
    state: str = "unknown"                # idle / working / resting / navigating ...


@dataclass
class RobotState:
    """统一 telemetry 模型（对应需求 §15）。"""
    robotId: str = "ARGOS-01"
    connection: Connection = field(default_factory=Connection)
    runtime: Runtime = field(default_factory=Runtime)
    battery: Optional[float] = None
    pose: Optional[Pose] = None
    temperature: Optional[float] = None   # 现有执行器不产生 -> null
    cpu: Optional[float] = None           # 同上
    memory: Optional[float] = None        # 同上
    gripper: Optional[str] = None
    estop: bool = False
    updatedAt: float = field(default_factory=now)


# ── Brain / Safety / LLM ──────────────────────────────

@dataclass
class BrainState:
    state: str = "idle"                   # idle / working / resting
    status: str = "ready"                 # ready | busy（UI 上的 ● Ready）
    tick: int = 0
    activity: str = ""
    pending: str = ""
    executor: str = "sim"
    llmEnabled: bool = False
    memoryCount: int = 0


@dataclass
class SafetyDecision:
    action: str = ""
    approved: bool = False
    reason: str = ""
    at: float = field(default_factory=now)
    runId: Optional[str] = None


@dataclass
class SafetyState:
    estop: bool = False
    status: str = "active"                # active | tripped
    gates: Dict[str, bool] = field(default_factory=dict)
    boundaries: Dict[str, float] = field(default_factory=dict)
    lastDecision: Optional[SafetyDecision] = None


@dataclass
class LlmConfig:
    baseUrl: str = ""
    model: str = ""
    hasKey: bool = False
    maskedKey: Optional[str] = None       # 只回显 sk-***abcd，不回传明文
    timeout: float = 20.0


@dataclass
class CameraConfig:
    mode: str = "none"                    # none | url | usb
    url: Optional[str] = None             # 外部 MJPEG 地址
    usbIndex: int = 0                     # 本机摄像头序号


# ── Run（核心数据模型）────────────────────────────────

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"

# Run Detail 从上到下要走的八节（对应需求 §11）
STAGE_INPUT = "input"
STAGE_BRAIN = "brain"
STAGE_LLM = "llm"
STAGE_SAFETY = "safety"
STAGE_TASK = "task"
STAGE_EXECUTOR = "executor"
STAGE_ROBOT = "robot"
STAGE_RESULT = "result"

STAGE_LABELS = {
    STAGE_INPUT: "User Command",
    STAGE_BRAIN: "Brain",
    STAGE_LLM: "LLM",
    STAGE_SAFETY: "Safety Gate",
    STAGE_TASK: "Task",
    STAGE_EXECUTOR: "Executor",
    STAGE_ROBOT: "Robot",
    STAGE_RESULT: "Result",
}


@dataclass
class Stage:
    """Run 的一节。status 可以是 skipped —— LLM 在纯规则模式下就是没调用。"""
    key: str
    label: str = ""
    status: str = PENDING                 # pending | running | done | failed | skipped
    at: Optional[float] = None
    detail: Optional[str] = None
    data: Optional[Dict] = None


def new_stages() -> List[Stage]:
    return [Stage(key=k, label=v) for k, v in STAGE_LABELS.items()]


@dataclass
class Run:
    """一次用户操作 = 一条 Run（需求 §11）。

    source=user 是用户下指令；source=autonomous 是大脑自己选的日常
    （巡逻/待命/回充），这类也记，但列表里可以标注来源。
    """
    id: str = field(default_factory=lambda: uid("run"))
    createdAt: float = field(default_factory=now)
    updatedAt: float = field(default_factory=now)
    status: str = RUNNING                 # running | completed | failed | rejected
    source: str = "user"                  # user | autonomous
    command: str = ""
    reply: Optional[str] = None
    stages: List[Stage] = field(default_factory=new_stages)
    error: Optional[str] = None

    def stage(self, key: str) -> Optional[Stage]:
        for s in self.stages:
            if s.key == key:
                return s
        return None

    def set_stage(self, key: str, status: str, detail: Optional[str] = None,
                  data: Optional[Dict] = None) -> None:
        s = self.stage(key)
        if s is None:
            return
        s.status = status
        s.at = now()
        if detail is not None:
            s.detail = detail
        if data is not None:
            s.data = data
        self.updatedAt = now()


# ── Event ────────────────────────────────────────────

# 需求 §10 的事件分类
CAT_COMMAND = "Command"
CAT_BRAIN = "Brain"
CAT_LLM = "LLM"
CAT_SAFETY = "Safety"
CAT_ROBOT = "Robot"
CAT_MEMORY = "Memory"
CAT_SYSTEM = "System"


@dataclass
class Event:
    id: str = field(default_factory=lambda: uid("evt"))
    ts: float = field(default_factory=now)
    type: str = ""                        # command.received / safety.rejected ...
    category: str = CAT_SYSTEM
    message: str = ""
    runId: Optional[str] = None
    data: Optional[Dict] = None
