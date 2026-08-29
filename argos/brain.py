"""ArgOS 机器人大脑：Dagent NPC 自主循环的机器人版（简化移植，零 LLM、零新依赖）。

移植对照（1_Dagent/npc 只读参考，本包不 import 那边任何代码）：
  reviewer.compile_task（B2 编译）  → compile_command   一句话 → 任务单（机器人动词表）
  book.guarded_book（三道门）       → RobotBrain.book   落账口：白名单 + 安全闸预审
  scheduler._tick_one（每tick一步） → RobotBrain.tick   玩家单 > 自主日常；失败冷却
  memory.NPCMemory（EV_DONE/FAIL）  → RobotBrain.remember / recall 事件记忆（JSON 可编辑）
  memory_card.maybe_reflect（反思） → RobotBrain.maybe_reflect  事实摘要，禁止编造
  housekeeper（管家降级）           → RobotBrain._archive_overflow  降级不删除，证据链留卡上
铁律不变：LLM 只提议、代码决定执行 —— 每步动作在 RobotBackend 里还要再过一次
SafetyGate（不可绕过），本模块落账前的预审只是第一道。

对应 架构.md §9 的"最小闭环"：文本指令 → 编译 → 预审 → 落账 → stub/仿真执行 → 记忆回流。
"""
from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from argos.backend import RobotBackend
from argos.executor import build_executor
from argos.perception import observe_text
from argos.primitives import ALLOWED_MOTION_ACTIONS
from argos.safety import NORMAL_BATT, SAFE_BATT, SafetyGate, battery_of

# 记忆事件前缀（与 1_Dagent/npc/memory.py 同源措辞，机器人版单一出处）
EV_DONE = "完成: "
EV_FAIL = "没做成: "
BLOCK_AFTER_FAIL_TICKS = 5   # 失败冷却 tick 数（Dagent scheduler 同款语义，按动作计）
MAX_MEMORY = 100             # 活跃记忆上限（Dagent 管家同思想：超限降级 archived 不删除）

# 反思（阶段① 海马体，Dagent memory_card.maybe_reflect 同款语义）：未反思记忆
# 重要性之和达阈值 → 归纳一条反思记忆。铁律: 只复述/归纳给定事实，禁止编造。
REFLECT_IMPORTANCE_THRESHOLD = 18   # 闲聊不凑数，攒够大事才总结（Dagent 2026-08-28 同步）
REFLECT_MAX_ENTRIES = 8             # 一次反思最多纳入的条目数（防上下文过长）

# 地点表：名字 → (x, y[, yaw])。充电桩即"家"，缺省在原点（SimEntity 出生点）。
DEFAULT_PLACES: Dict[str, tuple] = {
    "充电桩": (0.0, 0.0, 0.0),
    "家": (0.0, 0.0, 0.0),
    "桌边": (2.0, 0.0, 90.0),
    "门口": (4.0, 4.0, 180.0),
}

# 自主日常（Dagent persona.routine 的机器人版）：加权随机，玩家单优先。
# need="low_battery" 的项只在电量 ≤20% 时参与（回充），平时跳过；到桩边也不再选。
DEFAULT_ROUTINE = (
    {"action": "navigate", "desc": "巡逻一圈", "weight": 3},
    {"action": "move_to", "place": "桌边", "desc": "去桌边看看", "weight": 2},
    {"action": "move_to", "place": "充电桩", "desc": "回充电桩补电",
     "weight": 1, "need": "low_battery"},
    {"action": "rest", "desc": "原地待命", "weight": 1},
)

_RELEASE_WORDS = ("放下", "松开", "放开")
_PATROL_WORDS = ("巡逻", "巡检", "转一圈")
_GRAB_WORDS = ("拿", "抓", "捡", "取")
_GOTO_WORDS = ("去", "到", "回")
_TEXT_TAIL = " ，。!！?？、吧呀呢哈嘛哦"


def compile_command(text: str,
                    places: Optional[Dict[str, tuple]] = None) -> Optional[Dict]:
    """B2 编译（规则快路径）：一句话 → 任务单，认不出 → None（调用方诚实回话）。

    识别顺序（先长后短，防"去拿X"被"去"截胡）：放下 > 巡逻 > 拿 > 去/到/回+地名。
    产出的动作全部落在 ALLOWED_MOTION_ACTIONS 白名单内，参数即后续执行参数。
    """
    text = (text or "").strip()
    if not text:
        return None
    if any(w in text for w in _RELEASE_WORDS):
        return {"action": "release"}
    if any(w in text for w in _PATROL_WORDS):
        return {"action": "navigate"}            # waypoints 由大脑按地点表补全
    for w in _GRAB_WORDS:
        i = text.find(w)
        if i >= 0:
            target = text[i + len(w):].strip(_TEXT_TAIL)[:20]
            if target:
                return {"action": "grab", "target": target}
            break                                 # "拿"后面没东西 → 不硬接
    table = places if places is not None else DEFAULT_PLACES
    for name in sorted(table, key=len, reverse=True):   # 最长地名优先
        if name in text and any(w in text for w in _GOTO_WORDS):
            x, y, *rest = table[name]
            return {"action": "move_to", "x": float(x), "y": float(y),
                    "yaw": float(rest[0]) if rest else 0.0, "place": name}
    return None


class RobotBrain:
    """一台机器人的大脑：接单（编译+预审+落账）→ tick 一步 → 记忆回流。

    用法：
        brain = RobotBrain()                  # 默认 stub 执行器，纯内存记忆
        brain.try_command("去门口")            # 接单，返回给用户的回复
        brain.tick()                          # 由外部循环每帧推一步
    """

    def __init__(self, executor=None, gate: Optional[SafetyGate] = None,
                 places: Optional[Dict[str, tuple]] = None,
                 routine=DEFAULT_ROUTINE, memory_path: Optional[str] = None,
                 rng: Optional[random.Random] = None) -> None:
        self.executor = executor if executor is not None else build_executor("sim")
        self.backend = RobotBackend(self.executor, gate=gate)
        self.places = dict(DEFAULT_PLACES if places is None else places)
        self.routine = tuple(routine)
        self.rng = rng or random.Random()
        self.memory_path = Path(memory_path) if memory_path else None
        self.memory: List[Dict] = []
        # 并发保护（评审 P0-2）：tick 在线程里跑且可能耗时十几秒，
        # /api/command 在主线程推进同一份状态。急停路径刻意不抢这把锁 ——
        # 它必须立刻生效，不能排在长动作后面。
        self._lock = threading.RLock()
        self._load_memory()
        # 运行时状态（不落盘 — 重启即回 idle，Dagent 同款语义）
        self.state = "idle"                    # idle / working / resting
        self.activity: Optional[Dict] = None   # {"item", "steps", "desc"} 进行中的活动
        self.pending_task: Optional[Dict] = None
        self._blocked: Dict[str, int] = {}     # {动作: 冷却到第几 tick}
        self._blocked_desc: Dict[str, str] = {}  # {动作: 失败时的描述} 用于如实回话
        self._tick = 0

    # ── 感知 ─────────────────────────────────────────

    def observe(self) -> str:
        """观察文本（喂给未来 LLM 上下文 / 前端展示）。"""
        return observe_text(self.backend.observe())

    def status(self) -> Dict:
        """当前快照（/api/state 的机器人版雏形）。"""
        task = self.pending_task
        return {"state": self.state, "tick": self._tick,
                "activity": self.activity_desc(),
                "pending": self._describe(task) if task else "",
                "estop": bool(self.backend.gate.estop),
                "pose": self.backend.observe()}

    def activity_desc(self) -> str:
        if self.activity is None:
            return ""
        return f"{self.activity['desc']}（剩 {len(self.activity['steps'])} 步）"

    # ── 接单（B2 编译 + A 预审 + 落账口）──────────────

    def book(self, task: Dict) -> Tuple[bool, str]:
        """落账口 —— 唯一允许产生 pending_task 的入口（Dagent 铁律同款）。

        预审 = 白名单 + SafetyGate（急停/电量/边界优先报根本原因）+ 冷却。
        通过后打断自主日常、登记玩家单；新单直接顶掉旧单。
        """
        with self._lock:
            action = str(task.get("action", ""))
            if action not in ALLOWED_MOTION_ACTIONS:
                return False, f"不允许的动作：{action}"
            params = {k: v for k, v in task.items() if k != "action"}
            ok, reason = self.backend.gate.check(
                action, params, self.backend.observe())
            if not ok:
                return False, reason
            if self._blocked.get(action, 0) > self._tick:
                # 冷却是按**动作类型**计的，所以要报真正失败的那件事的描述，
                # 不能拿当前这句话顶替（原来会说"去门口刚失败过"，
                # 但实际失败的是"去桌边"，张冠李戴）。
                what = self._blocked_desc.get(action) or self._describe(task)
                return False, f"{what}刚失败过，先缓缓。"
            self.pending_task = task
            self.activity = None                   # 打断自主日常，听用户的
            self.state = "idle"
            self.remember(f"接到任务: {self._describe(task)}", importance=6)
            return True, ""

    def try_command(self, text: str) -> str:
        """对话接单：编译 → 落账，返回给用户的回复（诚实拒绝，不空头承诺）。"""
        task = compile_command(text, self.places)
        if task is None:
            return "……这个我不认识。我只懂：去某地 / 巡逻 / 拿某物 / 放下。"
        ok, reason = self.book(task)
        if not ok:
            return f"……这个我现在做不了（{reason}）。"
        return self._ack(task)

    def estop(self, on: bool = True) -> None:
        """急停/解除（评审 P0-1）：**不抢锁**，必须立刻生效。

        置位后闸门拒绝一切新动作，同时由 backend 通知执行器，让它从正在跑的
        长动作内部退出 —— 原来只置闸门，等于跑完当前那一段（最长 15s）才停。
        """
        self.backend.estop(on)

    # ── 自主循环（每 tick 恰一步）─────────────────────

    def tick(self) -> Optional[Dict]:
        """推一帧：玩家单 > 自主日常；无单可接时加权随机选日常。

        返回转换事件 {"started"/"completed"/"failed"/"reflected": ...}，无转换 → None。
        调用方（server / 真机循环）按事件决定展示与落盘。
        可能耗时（执行器一个 move_to 可以走十几秒），所以 server 把它放进线程跑，
        本方法自带锁，和 /api/command 互斥（评审 P0-2）。
        """
        with self._lock:
            ev = self._tick_once()
            reflection = self.maybe_reflect()   # 重要事攒够 → 归纳一条反思记忆
            if reflection:
                ev = dict(ev or {})
                ev["reflected"] = reflection
            return ev

    def _tick_once(self) -> Optional[Dict]:
        """一帧的执行体（不含反思，见 tick）。"""
        self._tick += 1
        ev: Dict = {}
        if self.pending_task is not None:
            task, self.pending_task = self.pending_task, None   # 接单后只执行一次
            desc = self._describe(task)
            self.activity = {"item": task, "desc": desc, "from_user": True,
                             "steps": self._plan_steps(task) or []}
            ev["started"] = desc
        if self.activity is None:
            item = self._choose_routine()
            if item is None:
                self.state = "idle"
                return None
            desc = str(item.get("desc") or item.get("action", ""))
            self.activity = {"item": item, "desc": desc, "from_user": False,
                             "steps": self._plan_steps(item) or []}
            ev["started"] = desc

        act = self.activity
        if not act["steps"]:                   # 规划不出路线 → 诚实记账后放弃
            self.activity = None
            self.state = "idle"
            self.remember(f"{EV_FAIL}{act['desc']}（没规划出路线）", importance=4)
            ev["failed"] = act["desc"]
            return ev

        step = act["steps"].pop(0)
        if step["action"] == "rest":           # 内部待命步：不走执行器、不过闸
            self.state = "resting"
        else:
            ok, reason = self.backend.apply(step["action"], step["params"])
            if not ok:
                item = act["item"]
                key = str(item.get("action", ""))
                self._blocked[key] = self._tick + BLOCK_AFTER_FAIL_TICKS
                self._blocked_desc[key] = act["desc"]
                self.activity = None
                self.state = "idle"
                self.remember(f"{EV_FAIL}{act['desc']}（{reason}）", importance=4)
                ev["failed"] = act["desc"]
                return ev
            self.state = "working"
        if not act["steps"]:
            if act.get("from_user"):    # 日常完成是噪音不写卡（管家闸1思想：源头断垃圾）
                self.remember(f"{EV_DONE}{act['desc']}", importance=5)
            self.activity = None
            self.state = "idle"
            ev["completed"] = act["desc"]
        return ev

    # ── 内部：规划 / 选日常 ──────────────────────────

    def _plan_steps(self, item: Dict) -> Optional[List[Dict]]:
        """任务/日常 → 步骤列表（每步 {action, params}；rest 为内部待命步）。"""
        kind = item.get("action")
        if kind == "move_to":
            if "x" in item and "y" in item:
                p = {"x": item["x"], "y": item["y"], "yaw": item.get("yaw", 0.0)}
            else:
                spot = self.places.get(str(item.get("place", "")))
                if spot is None:
                    return None
                p = {"x": spot[0], "y": spot[1],
                     "yaw": spot[2] if len(spot) > 2 else 0.0}
            return [{"action": "move_to", "params": p}]
        if kind == "navigate":
            wps = item.get("waypoints")
            if not wps:                        # 巡逻缺省路线 = 全部地点
                wps = [{"x": s[0], "y": s[1], "yaw": s[2] if len(s) > 2 else 0.0}
                       for s in self.places.values()]
            if not wps:
                return None
            # 评审 P1-1：每个途经点一步，tick 每帧推进一步。原来整段路线算一步，
            # 一次 tick 就把四个地点全跑完 —— stub 瞬移看不出来，真机上等于
            # "一帧走完四个房间"，还会把 tick 循环阻塞几十秒。
            return [{"action": "move_to",
                     "params": {"x": float(w.get("x", 0.0)),
                                "y": float(w.get("y", 0.0)),
                                "yaw": float(w.get("yaw", 0.0))}}
                    for w in wps]
        if kind == "grab":
            return [{"action": "grab", "params": {"target": item.get("target", "")}}]
        if kind == "release":
            return [{"action": "release", "params": {}}]
        if kind == "rest":
            return [{"action": "rest", "params": {}}]
        return None

    def _choose_routine(self) -> Optional[Dict]:
        """加权随机选日常（Dagent _choose_routine_item 简版 + 电量门控预跳）。

        急停中 → None（连试都不试，不刷"没做成"记忆）；电量语义与 SafetyGate
        对齐：≤20% 跳过巡逻（navigate 会被闸拒），≤10% 再跳过抓放；
        回充项低电量时权重 ×10，已在桩边则不选（防空转刷记忆）。
        """
        if self.backend.gate.estop:
            return None
        pose = self.backend.observe()
        batt = battery_of(pose)
        if batt is None:
            batt = SAFE_BATT      # 电量未知按最低档（评审 P1-6：不再默认满电）
        cands, weights = [], []
        for item in self.routine:
            action = str(item.get("action", ""))
            if self._blocked.get(action, 0) > self._tick:
                continue
            if action == "navigate" and batt <= NORMAL_BATT:
                continue
            if action in ("grab", "release") and batt <= SAFE_BATT:
                continue
            low = item.get("need") == "low_battery"
            if low:
                if batt > NORMAL_BATT:
                    continue
                # 已在自己的目标点就不再选。原来硬编码"充电桩"，自定义 places
                # 里没这个地名时判定失效，会在桩边反复空转刷记忆（评审 P3-1）。
                spot = self.places.get(str(item.get("place", "")))
                if spot is not None and self._near_spot(spot, pose):
                    continue
            w = int(item.get("weight", 1))
            cands.append(item)
            weights.append(w * 10 if low else max(1, w))
        if not cands:
            return None
        return self.rng.choices(cands, weights=weights, k=1)[0]

    def _near(self, place: str, pose: Dict, eps: float = 0.5) -> bool:
        spot = self.places.get(place)
        return self._near_spot(spot, pose, eps) if spot is not None else False

    @staticmethod
    def _near_spot(spot, pose: Dict, eps: float = 0.5) -> bool:
        return abs(float(pose.get("x", 0.0)) - float(spot[0])) <= eps and \
            abs(float(pose.get("y", 0.0)) - float(spot[1])) <= eps

    # ── 措辞（单一出处，Dagent _task_desc/_task_ack 同思想）──

    @staticmethod
    def _describe(task: Dict) -> str:
        a = task.get("action")
        if a == "move_to":
            if task.get("place"):
                return f"去{task['place']}"
            return f"移动到({float(task.get('x', 0)):.1f},{float(task.get('y', 0)):.1f})"
        if a == "navigate":
            return "巡逻一圈"
        if a == "grab":
            return f"拿{task.get('target', '东西')}"
        if a == "release":
            return "放下"
        return str(task.get("desc") or a)

    @staticmethod
    def _ack(task: Dict) -> str:
        a = task.get("action")
        if a == "move_to":
            return f"好，我{RobotBrain._describe(task)}。"
        if a == "navigate":
            return "好，我这就去巡逻一圈。"
        if a == "grab":
            return f"好，我去拿{task.get('target', '东西')}。"
        return "好，这就放下。"

    # ── 记忆卡（JSON = 可编辑文档）────────────────────

    def remember(self, content: str, importance: int = 5) -> None:
        """记一条事件（接地约束同 Dagent：只记真实发生的事）。"""
        self.memory.append({"content": content,
                            "importance": max(0, min(9, int(importance))),
                            "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        self._archive_overflow()
        self.save()

    def _archive_overflow(self) -> None:
        """超限降级（Dagent housekeeper 的极简版）：最老的活跃条目标记 archived，
        退出检索与反思；条目本身留在卡上永不物理删除（证据链红线）。"""
        active = [e for e in self.memory if not e.get("archived")]
        overflow = len(active) - MAX_MEMORY
        if overflow > 0:
            for e in active[:overflow]:
                e["archived"] = True

    def recent(self, n: int = 5) -> List[Dict]:
        """最近 n 条活跃记忆（archived 不上屏，卡上仍可翻）。"""
        active = [e for e in self.memory if not e.get("archived")]
        return active[-n:]

    def recall(self, query: str, top_k: int = 3) -> List[Dict]:
        """逐字召回（不编造）：命中关键词的最近活跃记忆，最新的在前。"""
        hits = [e for e in self.memory
                if not e.get("archived") and query and query in e["content"]]
        return list(reversed(hits))[:top_k]

    def maybe_reflect(self) -> Optional[str]:
        """反思归纳（Dagent memory_card.maybe_reflect 简版，规则兜底零 LLM）。

        触发: 未反思记忆的重要性之和 ≥ REFLECT_IMPORTANCE_THRESHOLD。
        产出 = 事实摘要（复述权重最高的 2 条，不发明新事实）；已归纳条目就地
        标记 reflected 不再重复；反思条本身不进候选；同文反思不重写（静默翻篇）。
        返回反思文本；未触发 → None。
        """
        cands = [e for e in self.memory
                 if not e.get("reflected") and not e.get("archived")
                 and e.get("kind") != "reflection"]
        cands = cands[:REFLECT_MAX_ENTRIES]
        if not cands or \
                sum(e.get("importance", 5) for e in cands) < REFLECT_IMPORTANCE_THRESHOLD:
            return None
        tops = sorted(cands, key=lambda e: e.get("importance", 0), reverse=True)[:2]
        text = "我最近做了这些事：" + "；".join(t["content"] for t in tops)
        if any(e.get("content") == text for e in self.memory):
            text = None                     # 同文不重写，只翻篇
        else:
            self.memory.append({"content": text, "importance": 8,
                                "kind": "reflection",
                                "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        for e in cands:
            e["reflected"] = True           # 这批已归纳，不再重复（Dagent 指针语义）
        self.save()
        return text

    def save(self) -> None:
        """记忆卡落盘；未配置 memory_path 则纯内存（测试/演示零副作用）。"""
        if self.memory_path is None:
            return
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text(
            json.dumps(self.memory, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_memory(self) -> None:
        """读记忆卡；读不出来或格式不对 → 把坏卡改名留证，从头开一张新的。

        评审 P1-5：原来只挡了 JSONDecodeError，卡被写成 dict（手改坏、写盘中断）
        时会一路带进 self.memory，下次 remember() 直接
        AttributeError: 'dict' object has no attribute 'append'，服务起不来。
        坏卡不删 —— 证据链红线。
        """
        if self.memory_path is None or not self.memory_path.exists():
            return
        try:
            data = json.loads(self.memory_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._quarantine_memory()
            self.memory = []
            return
        if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
            self._quarantine_memory()
            self.memory = []
            return
        self.memory = data

    def _quarantine_memory(self) -> None:
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self.memory_path.rename(
                self.memory_path.with_suffix(f".bad-{stamp}.json"))
        except OSError as exc:
            print(f"[RobotBrain] 坏记忆卡改名失败（不影响启动）：{exc}")
