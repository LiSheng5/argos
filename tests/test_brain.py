"""RobotBrain 自主循环冒烟 — 对照 Dagent 的 test_npc 风格：
编译（B2）→ 落账（预审+白名单）→ tick 执行 → 记忆回流。
"""
from argos.brain import (EV_DONE, EV_FAIL, MAX_MEMORY, RobotBrain,
                         compile_command)
from argos.sim.stub import SimEntity


def _brain(**kw) -> RobotBrain:
    kw.setdefault("executor", SimEntity())
    kw.setdefault("memory_path", None)
    return RobotBrain(**kw)


# ── B2 编译 ──────────────────────────────────────────

def test_compile_intents():
    places = {"充电桩": (0, 0), "桌边": (2, 0)}
    assert compile_command("去桌边", places) == {
        "action": "move_to", "x": 2.0, "y": 0.0, "yaw": 0.0, "place": "桌边"}
    assert compile_command("巡逻一圈", places)["action"] == "navigate"
    assert compile_command("拿红色小球", places)["target"] == "红色小球"
    assert compile_command("放下", places)["action"] == "release"
    assert compile_command("今天天气不错", places) is None
    assert compile_command("", places) is None


def test_compile_grab_beats_goto():
    # "去拿X" 语义是拿，不能被"去"截胡
    assert compile_command("去拿杯子")["action"] == "grab"
    assert compile_command("回家")["place"] == "家"


# ── 接单 → 执行 → 记忆回流 ────────────────────────────

def test_command_moves_and_remembers():
    b = _brain()
    reply = b.try_command("去门口")
    assert "门口" in reply and b.pending_task is not None
    ev = b.tick()
    assert ev and ev.get("completed") == "去门口"
    pose = b.backend.observe()
    assert (pose["x"], pose["y"]) == (4.0, 4.0)
    assert any(e["content"].startswith(EV_DONE) for e in b.memory)


def test_grab_release_flow():
    b = _brain()
    b.try_command("拿小球")
    assert b.tick()["completed"] == "拿小球"
    assert b.backend.observe()["gripper"] == "小球"
    b.try_command("放下")
    b.tick()
    assert b.backend.observe()["gripper"] is None


def test_unknown_command_honest_refusal():
    b = _brain()
    reply = b.try_command("给我写个文件")
    assert "我不认识" in reply and b.pending_task is None


def test_estop_refuses_at_booking():
    b = _brain()
    b.estop()
    reply = b.try_command("去门口")
    assert "做不了" in reply and "急停" in reply and b.pending_task is None


def test_estop_parks_autonomous_routine():
    b = _brain()
    b.estop()
    assert b.tick() is None and b.state == "idle"   # 急停中不选日常、不刷失败记忆
    assert not any(e["content"].startswith(EV_FAIL) for e in b.memory)


def test_out_of_boundary_refusal():
    b = _brain(places={"远处": (99.0, 99.0, 0.0)})
    assert "做不了" in b.try_command("去远处") and b.pending_task is None


# ── 自主日常（NPC 自主循环 → 机器人自主循环的核心）──────

def test_idle_tick_runs_routine():
    b = _brain()
    b.rng.seed(7)
    ev = b.tick()
    assert ev and "started" in ev              # 巡逻是多步日常，首帧只算开始
    for _ in range(10):                        # 推到这一段日常走完
        if b.activity is None:
            break
        b.tick()
    assert b.state == "idle" and b.activity is None
    assert not any(e["content"].startswith(EV_DONE)
                   for e in b.memory)          # 日常完成是噪音，不写卡


def test_navigate_is_stepwise():
    """评审 P1-1：巡逻必须逐点推进，不能一帧跑完全部地点。

    stub 执行器是瞬移的，所以这里数的是"大脑把路线拆成了几步"。
    """
    b = _brain()
    ok, reason = b.book({"action": "navigate"})
    assert ok, reason
    steps = 0
    while True:
        b.tick()
        steps += 1
        if b.activity is None:
            break
        assert steps < 20, "巡逻步骤数异常（可能又回到一步跑完）"
    assert steps == len(b.places), f"应逐点走 {len(b.places)} 步，实际 {steps}"


def test_memory_overflow_archives_not_deletes():
    b = _brain()
    for i in range(MAX_MEMORY + 5):
        b.remember(f"事件{i}", importance=5)
    assert len(b.memory) == MAX_MEMORY + 5     # 卡上全在（证据链不删）
    active = [e for e in b.memory if not e.get("archived")]
    assert len(active) == MAX_MEMORY
    assert b.memory[0].get("archived") is True  # 最老的已降级
    assert b.recall("事件0") == []              # 退出检索
    assert b.recall(f"事件{MAX_MEMORY + 4}")    # 新的仍可召回


def test_low_battery_returns_to_dock():
    b = _brain(executor=SimEntity(start=(3.0, 0.0, 0.0), battery_pct=15),
               routine=({"action": "move_to", "place": "充电桩",
                         "desc": "回充电桩补电", "weight": 1,
                         "need": "low_battery"},))
    ev = b.tick()
    assert ev and "充电桩" in ev["completed"]
    assert b.backend.observe()["x"] == 0.0


def test_high_battery_skips_charge_item():
    b = _brain(routine=({"action": "move_to", "place": "充电桩",
                         "desc": "回充电桩补电", "weight": 1,
                         "need": "low_battery"},))
    assert b.tick() is None and b.state == "idle"


def test_at_dock_low_battery_no_charge_loop():
    b = _brain(executor=SimEntity(start=(0.0, 0.0, 0.0), battery_pct=15),
               routine=({"action": "move_to", "place": "充电桩",
                         "desc": "回充电桩补电", "weight": 1,
                         "need": "low_battery"},))
    assert b.tick() is None                    # 已在桩边：不再刷"回桩"记忆


# ── 失败冷却（防反复撞墙）─────────────────────────────

def test_failure_cooldown_and_memory():
    b = _brain()
    ok, _ = b.book({"action": "move_to", "x": 4.0, "y": 4.0, "yaw": 0.0,
                    "place": "门口"})
    assert ok
    b.estop()                                  # 接单后急停 → 执行闸拒绝
    ev = b.tick()
    assert ev and "failed" in ev
    assert any(e["content"].startswith(EV_FAIL) for e in b.memory)
    b.backend.gate.set_estop(False)
    ok, reason = b.book({"action": "move_to", "x": 4.0, "y": 4.0, "yaw": 0.0,
                         "place": "门口"})
    assert not ok and "缓缓" in reason         # 冷却期内诚实拒绝


# ── 记忆卡持久化（JSON 可编辑文档）────────────────────

def test_memory_persistence_roundtrip(tmp_path):
    path = tmp_path / "mem.json"
    b = _brain(memory_path=path)
    b.try_command("拿小球")
    b.tick()
    b2 = RobotBrain(executor=SimEntity(), memory_path=path)
    hits = b2.recall("小球")
    assert hits and "拿小球" in hits[0]["content"]


def test_observe_and_status():
    b = _brain()
    assert "电量" in b.observe()
    st = b.status()
    assert st["state"] == "idle" and "x" in st["pose"]


# ── 记忆反思（Dagent 阶段① 海马体的机器人版）──────────

def test_reflection_triggers_after_enough_events():
    b = _brain()
    b.try_command("去门口")
    b.tick()                                   # 6 + 5 = 11 < 18，不触发
    assert b.maybe_reflect() is None
    b.try_command("拿小球")
    b.tick()                                   # 累计 22 ≥ 18，tick 内已触发
    text = next(e["content"] for e in b.memory if e.get("kind") == "reflection")
    assert text.startswith("我最近做了这些事：")
    assert all(e.get("reflected") for e in b.memory
               if e.get("kind") != "reflection")   # 这批已归纳
    assert b.maybe_reflect() is None              # 同一批不重复反思


def test_reflection_only_counts_unreflected():
    b = _brain()
    for cmd in ("去门口", "拿小球"):
        b.try_command(cmd)
        b.tick()                               # 第二轮触发一次反思
    n = len([e for e in b.memory if e.get("kind") == "reflection"])
    assert n == 1
    b.try_command("放下")
    b.tick()                                   # 新增 5 分 < 18，不再触发
    assert len([e for e in b.memory
                if e.get("kind") == "reflection"]) == n
