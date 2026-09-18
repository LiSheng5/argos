"""Agent Runtime 的全部抽象类型（Phase 1）。

这一层是 Brain 与 Embodiment 之间**唯一**的词汇表。Brain 只认识这里的东西：

    Observation   —— 世界给它的（只读投影）
    ActionProposal—— 它想做的（提议，不是命令）
    ActionResult  —— 世界回它的（含结构化失败原因）
    WorldState    —— 世界的真相（**只有 Backend 能写**）
    Lesson        —— 反思产物（Planner 必须消费）
    EmbodimentCapabilities —— 这个身体能干什么

铁律：**LLM / Brain 不得直接改 WorldState**，只能产出 ActionProposal；
世界怎么变，由 Simulator（未来的真机）说了算。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple


class ActionKind(str, Enum):
    """动作原语。比旧 `primitives.ALLOWED_MOTION_ACTIONS` 更贴近"迷你世界"的粒度。"""
    MOVE = "move"
    TURN = "turn"
    STOP = "stop"
    WAIT = "wait"
    INSPECT = "inspect"
    GRAB = "grab"
    RELEASE = "release"


@dataclass(frozen=True)
class Pose:
    """位置 + 朝向 + 速度。yaw 单位为弧度。"""
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vyaw: float = 0.0

    def dist_to(self, other: "Pose") -> float:
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5


@dataclass(frozen=True)
class Action:
    """已经过闸、准备下发给 backend 的动作。"""
    kind: ActionKind
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionProposal:
    """Brain / LLM 的产出物 —— **只是提议**。

    rationale 记录"为什么提这个"，供 trace 与反思溯源（诚实：不编造，没理由就空着）。
    """
    kind: ActionKind
    params: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    source: str = "planner"

    def to_action(self) -> Action:
        return Action(self.kind, dict(self.params))


class FailReason(str, Enum):
    """结构化的失败原因。**这是旧系统最缺的东西** —— 之前失败只是一个裸 False。"""
    OK = "ok"
    OBSTACLE_BLOCKED = "obstacle_blocked"
    ACTION_TIMEOUT = "action_timeout"
    PATH_INVALID = "path_invalid"
    LOCALIZATION_ERROR = "localization_error"
    BATTERY_LOW = "battery_low"
    SENSOR_MISSING = "sensor_missing"
    SIMULATOR_DELAY = "simulator_delay"
    NETWORK_DELAY = "network_delay"
    EXECUTOR_FAILURE = "executor_failure"
    # 被安全闸拒绝 ≠ 世界给的经验。单独枚举，不进 Lesson，免得污染换线逻辑。
    SAFETY_REJECTED = "safety_rejected"
    # 参数本身不合法（缺字段 / 类型错 / 越界）—— 也是闸的职责，同样不进 Lesson。
    INVALID_PARAMS = "invalid_params"


#: 这些原因表示"世界真的发生了一次失败"，值得反思学习。
#: 延迟（simulator/network）也算 —— 它是世界的真实状态，agent 该学会"这条路会卡"。
#: **不含** SAFETY_REJECTED / INVALID_PARAMS：那是闸门和参数的问题，不是世界的经验。
LEARNING_REASONS = frozenset({
    FailReason.OBSTACLE_BLOCKED,
    FailReason.ACTION_TIMEOUT,
    FailReason.PATH_INVALID,
    FailReason.LOCALIZATION_ERROR,
    FailReason.BATTERY_LOW,
    FailReason.SENSOR_MISSING,
    FailReason.EXECUTOR_FAILURE,
    FailReason.SIMULATOR_DELAY,
    FailReason.NETWORK_DELAY,
})


@dataclass(frozen=True)
class ActionResult:
    """动作执行结果。**结构化**，上层可按 reason 分派不同的修正策略。"""
    ok: bool
    reason: FailReason = FailReason.OK
    detail: str = ""
    pose_before: Optional[Pose] = None
    pose_after: Optional[Pose] = None
    sim_time: float = 0.0

    @property
    def learnable(self) -> bool:
        """是否值得记一条失败经验（被闸拒不算）。"""
        return (not self.ok) and self.reason in LEARNING_REASONS


@dataclass(frozen=True)
class EmbodimentCapabilities:
    """这个身体能干什么。**Brain 不许假设**，只能读。

    Simulator 与未来的 Go2 会给出不同的能力集合 —— 这正是"换身体不改大脑"的支点。
    """
    actions: Tuple[ActionKind, ...] = ()
    has_arm: bool = False
    max_speed: float = 0.0
    can_localize: bool = True

    def supports(self, kind: ActionKind) -> bool:
        if kind in (ActionKind.GRAB, ActionKind.RELEASE):
            return bool(self.has_arm) and kind in self.actions
        return kind in self.actions


@dataclass(frozen=True)
class Observation:
    """WorldState 的**只读投影**，Brain 只能拿到这个。

    刻意做成 frozen + 元组：谁想改都改不了，避免"上层顺手改世界"。
    """
    robot_pose: Pose = Pose()
    battery: float = 100.0
    obstacles: Tuple[Any, ...] = ()
    objects: Tuple[Any, ...] = ()
    locations: Tuple[Tuple[str, Pose], ...] = ()
    people: Tuple[Any, ...] = ()
    events: Tuple[str, ...] = ()
    tasks: Tuple[str, ...] = ()
    sim_time: float = 0.0
    version: int = 0
    #: 这一轮**没读到的传感器名**（失灵 / 超范围）。字段里仍带最后可用值，
    #: 但**消费者必须先看 `missing`** —— 安全闸对缺数据是 fail-closed 的。
    missing: Tuple[str, ...] = ()


class EmbodimentBackend(Protocol):
    """具身后端协议。现在只有 Simulator，未来加 Go2 / 其他机器人。

    上层（Brain/Planner/Memory/Reflector）**只**通过这个协议访问世界。
    """
    def capabilities(self) -> EmbodimentCapabilities: ...
    def observe(self) -> Observation: ...
    def apply(self, action: Action) -> ActionResult: ...
    def estop(self, on: bool = True) -> None: ...


@dataclass
class WorldState:
    """**唯一真相源**。只有 Backend 能写。

    `version` 每次写入自增，供观测层对账（防止"读到半更新态"）。
    注意：本类可变；给 Planner 的一律是 `WorldView`（frozen 投影）。
    """
    robot: Pose = Pose()
    battery: float = 100.0
    obstacles: Dict[str, Any] = field(default_factory=dict)
    objects: Dict[str, Any] = field(default_factory=dict)
    locations: Dict[str, Pose] = field(default_factory=dict)
    people: Dict[str, Any] = field(default_factory=dict)
    events: List[str] = field(default_factory=list)
    tasks: List[str] = field(default_factory=list)
    sim_time: float = 0.0
    version: int = 0
    #: 本轮没读到的传感器名（见 `Observation.missing`）。缺 pose / battery 时闸门拒绝移动。
    missing: Tuple[str, ...] = ()

    def touch(self) -> None:
        """任何写入之后调用：版本号 +1。"""
        self.version += 1


@dataclass(frozen=True)
class Lesson:
    """反思产物 —— **Planner 必须消费它**，否则反思就是写给自己看的日记。

    * trigger: 触发场景（如 `route:north`）
    * avoid  : 以后避开什么
    * prefer : 改用什么
    * scope  : 这条经验的适用域（如 `route:north`）—— 防止把"低电量"学成"这条路不行"
    * evidence: 源事实原文（防编造：没有证据的 Lesson 不该被采纳）
    """
    id: str
    trigger: str
    avoid: str
    prefer: str
    evidence: str = ""
    confidence: float = 0.0
    hits: int = 1
    scope: str = ""
    #: `active` = 现在生效；`invalidated` = 已被反证推翻（**保留不删**，供审计与复盘）。
    #: 参考 Zep/Graphiti 的做法：invalidate 而不 discard —— 删掉就再也查不到"当初学到过什么"。
    status: str = "active"
    #: 验证历史（形如 `support@ep1` / `counter_evidence@ep2` / `reinstate@ep5`），
    #: 让"这条教训是怎么来的、又是怎么被推翻的"可追溯。
    history: Tuple[str, ...] = ()
    created_episode: int = 0
    updated_episode: int = 0

    @property
    def active(self) -> bool:
        return self.status == "active"

    def matches(self, candidate: str) -> bool:
        """候选路线/目标是否命中这条教训的 avoid。"""
        return bool(candidate) and candidate == self.avoid
