"""Benchmark 场景库（Phase 7）。

设计原则（对齐指令第十四节）：
  * **可复现**：场景是纯数据，随机只吃 `seed`；
  * **可失败**：每个场景都指明"失败从哪来"（永久障碍 / 瞬时故障 / 低电量 / 丢包）；
  * **同 seed 可比**：同一场景+seed 下跑不同 Agent 配置，结论才有意义。

⚠️ 诚实声明：这 20+ 个场景是**少量原型 × 参数化变体**（障碍位置 / 路线偏好 / 延迟剖面），
不是 20 个手写故事。写清楚这一点，比把参数变体吹成"20 个独立任务"要诚实。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from argos.agent.interfaces import FailReason, Pose
from argos.sensors import simulated_suite, suite_of
from argos.world.mini_world import MiniWorld, Rect, build_default_world


@dataclass(frozen=True)
class SensorSpec:
    """场景里"传感器有多不可靠"。

    默认全 0/宽松 = 不配传感器（上帝视角），行为与从前逐字一致；
    一旦指定，runner 会真的给 backend 装上这套传感器 ——
    于是**感知层第一次进入 benchmark**（在此之前它只在单测里验证过）。
    """
    pose_noise: float = 0.0          # 定位噪声（米）
    pose_dropout: float = 0.0        # 定位失灵概率（每次读）
    battery_step: float = 0.0        # 电量量化步长
    obstacle_radius: float = 5.0     # 障碍探测半径（米）
    vision_radius: float = 6.0       # 视觉探测半径（米）

    def build(self, seed: int):
        return suite_of(*simulated_suite(
            seed=seed, pose_noise=self.pose_noise, pose_dropout=self.pose_dropout,
            battery_step=self.battery_step, obstacle_radius=self.obstacle_radius,
            vision_radius=self.vision_radius))

#: 加长版南线：比北线多两个途经点，用来度量"绕路成本"
_LONG_SOUTH = (
    Pose(2.0, -2.0, 0.0), Pose(3.5, -3.0, 0.0), Pose(5.0, -3.0, 0.0),
    Pose(7.0, -3.0, 0.0), Pose(9.0, -2.5, 0.0), Pose(10.0, -2.0, 0.0),
)
#: 超长南线（8 个途经点）：把"永久绕远路"的代价放大到肉眼可见，
#: 否则"过度泛化"这件事度量不出来（失败数一样，动作数只差一点）。
_VERY_LONG_SOUTH = (
    Pose(1.5, -2.0, 0.0), Pose(2.5, -3.5, 0.0), Pose(4.0, -4.0, 0.0),
    Pose(5.5, -4.0, 0.0), Pose(7.0, -4.0, 0.0), Pose(8.5, -3.5, 0.0),
    Pose(9.5, -2.5, 0.0), Pose(10.0, -2.0, 0.0),
)
_SHORT_NORTH = (
    Pose(2.0, 2.0, 0.0), Pose(5.0, 2.0, 0.0), Pose(9.0, 2.0, 0.0), Pose(10.0, -2.0, 0.0),
)


@dataclass(frozen=True)
class Scenario:
    """一个完整、可复现的实验设定。"""
    name: str
    goal: str
    description: str
    kind: str                                   # permanent / transient / open / battery / link
    # ⚠️ 必须用 None 表示"沿用默认"，不能拿空元组当"没有障碍" ——
    #    空元组是 falsy，早先写成 `x if x else base` 会让"无障碍场景"悄悄带上障碍（已踩过一次）。
    routes: Optional[Tuple[Tuple[str, Tuple[Pose, ...]], ...]] = None
    obstacles: Optional[Tuple[Rect, ...]] = None
    latency: Optional[str] = None               # LatencyProfile 名字
    #: 在**哪些 episode** 里注入一次"瞬时障碍"（其余 episode 是通的）。
    #: 空 = 不注入。用元组而非 bool，才能造出"连撞两次、然后恢复"这种关键场景。
    transient_episodes: Tuple[int, ...] = ()
    #: 瞬时故障绑在哪个**世界位置**上（见 runner 的 _WHERE 表）。
    #: 必须是位置而不是"当前路线" —— 否则 agent 改走绕路时会把绕路也一起记成不能走。
    transient_where: str = "north_corridor"
    #: 注入**哪一类**失败。默认是障碍阻挡；换成别的才能回答
    #: "反思/记忆在**非路线类**失败上还该不该起作用"（见 G/H 族）。
    failure: FailReason = FailReason.OBSTACLE_BLOCKED
    #: 感知配置。None = 不装传感器（上帝视角，与历史基线逐字一致）。
    sensors: Optional[SensorSpec] = None
    start_battery: float = 100.0
    episodes: int = 3
    #: 单次运行的**动作预算**。预算紧时才区分得出"学过 vs 没学过"：
    #: 预算充裕时，现场换路总能把失败救回来（这正是早期 benchmark 区分不出成功率的原因）。
    max_steps: int = 40

    def world(self) -> MiniWorld:
        base = build_default_world()
        return MiniWorld(
            name=f"mini_world::{self.name}",
            rooms=base.rooms,
            obstacles=base.obstacles if self.obstacles is None else self.obstacles,
            locations=base.locations,
            routes=base.routes if self.routes is None else self.routes,
            bounds=base.bounds,
        )


_SHORT_SOUTH = (Pose(2.0, -2.0, 0.0), Pose(5.0, -2.0, 0.0),
                Pose(9.0, -2.0, 0.0), Pose(10.0, -2.0, 0.0))


def _routes(*order: str, long_south: bool = False, very_long_south: bool = False):
    """按给定顺序组装路线（顺序 = Planner 的偏好顺序）。"""
    south = _VERY_LONG_SOUTH if very_long_south else (_LONG_SOUTH if long_south else _SHORT_SOUTH)
    table = {"north": _SHORT_NORTH, "south": south}
    return tuple((k, table[k]) for k in order)


def build_scenarios() -> Tuple[Scenario, ...]:
    """20 个可复现场景。"""
    out = []

    # --- A. 永久障碍（3 个障碍位置 × 2 个路线偏好 = 6）---
    for i, bx in enumerate((4.5, 5.0, 5.5)):
        for pref in (("north", "south"), ("south", "north")):
            out.append(Scenario(
                name=f"permanent_block_x{bx}_{pref[0]}first",
                goal="去充电站",
                description=f"北线被永久挡在 x={bx}；路线偏好 {'>'.join(pref)}",
                kind="permanent",
                routes=_routes(*pref),
                obstacles=(Rect("north_block", bx, 2.0, 2.0, 1.5),),
            ))

    # --- B. 瞬时故障（只在第 0 次注入一次；南线更长，用来看"过度泛化"的代价 = 4）---
    for lat in (None, "normal", "slow", "unstable"):
        out.append(Scenario(
            name=f"transient_jam_latency_{lat or 'none'}",
            goal="去充电站",
            description="北线只被挡一次（瞬时），之后恢复；南线是绕路（更贵）",
            kind="transient",
            routes=_routes("north", "south", long_south=True),
            obstacles=(),
            latency=lat,
            transient_episodes=(0,),
        ))

    # --- B2. 连撞两次后恢复（**治过度泛化的靶场景** = 2）---
    #     北线在 ep0、ep1 各失败一次 → 达到 min_hits=2 → 会生成"避开北线"的教训；
    #     但 ep2 起北线已经通了。没有复核机制的 agent 会从此永久绕远路。
    #     ⚠️ 时域 = 6（原来 5）：D-02 之后"真正削弱教训"要求**连续两次探针成功**，
    #        而每 2 轮才探一次（`revalidate_every=2`）→ 需要 2 次探针才撤得掉教训，
    #        5 轮里只够探一次。时域加一格才量得到"恢复"，否则测的是半途状态。
    for lat in (None, "normal"):
        out.append(Scenario(
            name=f"two_strikes_then_clear_{lat or 'none'}",
            goal="去充电站",
            description="北线在 ep0/ep1 各被挡一次后恢复通畅；南线是超长绕路 —— 用来量「过度泛化」的代价",
            kind="transient",
            routes=_routes("north", "south", very_long_south=True),
            obstacles=(),
            latency=lat,
            transient_episodes=(0, 1),
            episodes=6,
        ))

    # --- B3. 预算是紧的：现场换路救不回来，只有"学过"的才活得下来（= 2）---
    #     北线永久被挡；南线畅通但**更长**；动作预算只够走一趟南线。
    #     没学过的 agent 每次都先撞北线 → 预算耗尽 → 失败；
    #     学过的（避开北线 / 或语义软降权）直接走南线 → 完成。
    #     ← 这一族是专门用来治「成功率区分不出各组配置」的。
    for lat in (None, "normal"):
        out.append(Scenario(
            name=f"learn_to_survive_{lat or 'none'}",
            goal="去充电站",
            description="北线永久被挡、南线更长，而单次动作预算只够走一趟 —— 现场换路救不回来",
            kind="unrecoverable",
            routes=_routes("north", "south"),
            obstacles=(Rect("north_block", 5.0, 2.0, 2.0, 1.5),),
            latency=lat,
            episodes=4,
            max_steps=6,
        ))

    # --- C. 无障碍（对照组 = 2）---
    for pref in (("north", "south"), ("south", "north")):
        out.append(Scenario(
            name=f"open_path_{pref[0]}first",
            goal="去充电站",
            description="世界通畅，作为对照：所有配置都应满分",
            kind="open",
            routes=_routes(*pref),
            obstacles=(),
        ))

    # --- D. 低电量（两种：起始就低 / 途中耗到低 = 2）---
    out.append(Scenario(
        name="battery_low_start",
        goal="去充电站",
        description="起步电量 5%（低于闸门 10%）→ 任何移动都会被拒，这是**不该被反思修好**的情况",
        kind="battery",
        routes=_routes("north", "south"),
        obstacles=(),
        start_battery=5.0,
    ))
    out.append(Scenario(
        name="battery_normal_open",
        goal="去充电站",
        description="电量正常、无故障（低电量场景的对照）",
        kind="battery",
        routes=_routes("north", "south"),
        obstacles=(),
        start_battery=100.0,
    ))

    # --- E. 链路不稳（3 档 = 3）---
    for lat in ("moderate", "slow", "packet_loss"):
        out.append(Scenario(
            name=f"unstable_link_{lat}",
            goal="去充电站",
            description=f"链路剖面 {lat}；看丢包/延迟下还能不能到达",
            kind="link",
            routes=_routes("north", "south"),
            obstacles=(),
            latency=lat,
        ))

    # --- G. 路线类失败，但**换一种原因**：path_invalid（= 2）---
    #     与 two_strikes_then_clear 同形，只把注入类型从「障碍阻挡」换成「路径失效」。
    #     PATH_INVALID 与 OBSTACLE_BLOCKED 同属"路线相关"失败 → **学习应当照样有用**。
    #     这一族的作用：把"反思有效"的结论从 1 类失败扩到第 2 类。
    #     ⚠️ 时域、路线、故障注入必须与 B2 族**逐项一致**（同为 6 轮），
    #        否则"两族数字逐位相同"这条结论就没法比 —— 变的只能是 `failure` 一项。
    for lat in (None, "normal"):
        out.append(Scenario(
            name=f"two_strikes_path_invalid_{lat or 'none'}",
            goal="去充电站",
            description="北线在 ep0/ep1 各「路径失效」一次后恢复；南线超长绕路 —— 换一种失败原因重测学习是否有效",
            kind="route_failure",
            routes=_routes("north", "south", very_long_south=True),
            obstacles=(),
            latency=lat,
            failure=FailReason.PATH_INVALID,
            transient_episodes=(0, 1),
            episodes=6,
        ))

    # --- H. **非路线类**失败（负对照）：学习**不该**起作用（= 6）---
    #     这些失败不是"这条路的问题"（定位漂移 / 超时 / 执行器故障 / 模拟器延迟 /
    #     缺传感器 / 电量低）→ 正确行为是**统计得到，但绝不生成"避开这条路"的教训**。
    #     如果这里出现"学过 vs 没学过"的差异，说明有层级把非路线失败算在了路线头上。
    for kind in (FailReason.LOCALIZATION_ERROR, FailReason.ACTION_TIMEOUT,
                 FailReason.EXECUTOR_FAILURE, FailReason.SIMULATOR_DELAY,
                 FailReason.SENSOR_MISSING, FailReason.BATTERY_LOW):
        out.append(Scenario(
            name=f"nonroute_failure_{kind.value}",
            goal="去充电站",
            description=f"北线在 ep0/ep1 各注入一次「{kind.value}」—— 这不是路线的问题，反思不该乱学",
            kind="nonroute_failure",
            routes=_routes("north", "south", very_long_south=True),
            obstacles=(),
            failure=kind,
            transient_episodes=(0, 1),
            episodes=4,
        ))

    # --- I. 感知状态（三档 = 3）—— 感知层第一次进 benchmark ---
    out.append(Scenario(
        name="sensor_pose_noise",
        goal="去充电站",
        description="定位有 0.3m 噪声（但不失灵）—— 看带噪声的观测会不会把任务带偏",
        kind="perception",
        routes=_routes("north", "south"),
        obstacles=(),
        sensors=SensorSpec(pose_noise=0.3, battery_step=1.0),
    ))
    out.append(Scenario(
        name="sensor_pose_dropout",
        goal="去充电站",
        description="定位每次读有 15% 概率失灵 → 闸门 fail-closed 拒动；量「宁可不动」的代价",
        kind="perception",
        routes=_routes("north", "south"),
        obstacles=(),
        sensors=SensorSpec(pose_dropout=0.15),
        episodes=4,
    ))
    out.append(Scenario(
        name="sensor_range_limited",
        goal="去充电站",
        description="北线有永久障碍，但障碍探测半径只有 1m —— 观测里**看不见**它，世界照样挡：只能撞了才知道",
        kind="perception",
        routes=_routes("north", "south"),
        obstacles=(Rect("north_block", 5.0, 2.0, 2.0, 1.5),),
        sensors=SensorSpec(obstacle_radius=1.0, vision_radius=1.5),
        episodes=4,
    ))

    # --- F. 永久障碍 + 链路不稳（组合 = 3）---
    for lat in ("normal", "slow", "packet_loss"):
        out.append(Scenario(
            name=f"block_plus_link_{lat}",
            goal="去充电站",
            description=f"北线永久被挡 + 链路 {lat}",
            kind="permanent",
            routes=_routes("north", "south"),
            obstacles=(Rect("north_block", 5.0, 2.0, 2.0, 1.5),),
            latency=lat,
        ))

    return tuple(out)


def scenario_names() -> Tuple[str, ...]:
    return tuple(s.name for s in build_scenarios())


def by_name(name: str) -> Scenario:
    for s in build_scenarios():
        if s.name == name:
            return s
    raise KeyError(f"未知场景：{name}；可用：{list(scenario_names())}")


def summary_table() -> str:
    rows = ["| 场景 | 类型 | 说明 |", "|---|---|---|"]
    for s in build_scenarios():
        rows.append(f"| `{s.name}` | {s.kind} | {s.description} |")
    return "\n".join(rows)
