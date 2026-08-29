"""位姿闭环的判据测试（纯函数，不用 mujoco，跑得快）。

背景（2026-08-29 实测）：走 2m 侧向漂 0.2m，累计走 4m 漂 **1.2m**，而且是加速累积的。
原来的到点判据**只看 x 轴**，所以漂成那样也照样算"到了" —— 判据太松比没有判据更危险，
它会让上层以为一切正常。

改了两处：
1. `arrived()` 改成二维（x 和 y 都要在容差内）
2. `drifted()` 加横向漂移预算：走的过程中偏出预算就停下诚实放弃
   （v1 不会转弯，硬走只会更偏，别把 WALK_TIMEOUT 全耗光）
"""
from argos.sim.dds_entity import (ARRIVE_TOL_X, ARRIVE_TOL_Y, MAX_LATERAL,
                                  MAX_YAW_DRIFT, WALK_DIR, arrived, drifted,
                                  heading_drifted)


# ── arrived：二维到点判据 ──────────────────────────────

def test_arrived_requires_both_axes():
    assert arrived({"x": 0.0, "y": 0.0}, 0.0, 0.0) is True
    assert arrived({"x": -3.9, "y": 0.1}, -4.0, 0.0) is True      # 两轴都在容差内
    assert arrived({"x": -3.9, "y": 1.2}, -4.0, 0.0) is False     # y 漂太多 → 不算到


def test_old_one_dimensional_check_would_have_lied():
    """对照：只看 x 的一维判据会把漂 1.2m 的情况判成"到了"。"""
    pose, tx, ty = {"x": -3.9, "y": 1.2}, -4.0, 0.0
    old = abs(tx - pose["x"]) <= ARRIVE_TOL_X         # 修复前
    assert old is True and arrived(pose, tx, ty) is False


def test_two_axes_have_different_tolerances():
    """横向容差比纵向宽，因为 v1 不会转向 —— 那是能力上限，不是目标。"""
    assert ARRIVE_TOL_Y > ARRIVE_TOL_X
    # 纵向很严：偏 0.5m 就不算到
    assert arrived({"x": -3.5, "y": 0.0}, -4.0, 0.0) is False
    # 横向松：偏 0.5m 仍算到（实测 2m 就能漂到 0.7）
    assert arrived({"x": -4.0, "y": 0.5}, -4.0, 0.0) is True


def test_arrived_boundary_is_inclusive():
    assert arrived({"x": ARRIVE_TOL_X, "y": 0.0}, 0.0, 0.0) is True
    assert arrived({"x": ARRIVE_TOL_X + 0.01, "y": 0.0}, 0.0, 0.0) is False
    assert arrived({"x": 0.0, "y": ARRIVE_TOL_Y}, 0.0, 0.0) is True
    assert arrived({"x": 0.0, "y": ARRIVE_TOL_Y + 0.01}, 0.0, 0.0) is False


def test_arrived_accepts_custom_tolerance():
    assert arrived({"x": 0.4, "y": 0.0}, 0.0, 0.0, tol_x=0.5) is True
    assert arrived({"x": 0.4, "y": 0.0}, 0.0, 0.0, tol_x=0.25) is False
    assert arrived({"x": 0.0, "y": 0.4}, 0.0, 0.0, tol_y=0.25) is False


def test_arrived_tolerates_missing_pose_fields():
    assert arrived({}, 0.0, 0.0) is True             # 缺字段按 0 处理，不炸


# ── drifted：横向漂移预算 ──────────────────────────────

def test_drift_budget_flags_only_over_budget():
    assert drifted({"y": 0.2}, 0.0) is False         # 走 2m 的量级，放行
    assert drifted({"y": 0.7}, 0.0) is False         # 走 2m 最坏那次，仍在预算内
    assert drifted({"y": 1.2}, 0.0) is True          # 走 4m 的量级，叫停
    assert drifted({"y": MAX_LATERAL}, 0.0) is False  # 边界 inclusive


def test_drift_is_measured_against_target_y():
    """漂的是"离目标 y 多远"，不是离原点多远。"""
    assert drifted({"y": 2.4}, 2.0, budget=0.5) is False    # 相对目标只偏 0.4
    assert drifted({"y": 2.6}, 2.0, budget=0.5) is True     # 偏 0.6，超预算
    assert drifted({"y": 0.1}, 2.0, budget=0.5) is True     # 离目标远，不是"离原点近"就行


def test_drift_budget_is_configurable():
    assert drifted({"y": 0.8}, 0.0, budget=1.0) is False
    assert drifted({"y": 0.8}, 0.0, budget=0.5) is True


# ── heading_drifted：航向失控（比位移漂移更早的信号）────────────────
#
# 实测走 1m 的航向漂移：1.4° / 19.9° / 163.2° / 85.3° —— 后两次狗在打转。
# 等到横向位移超预算时它已经跑出去 3.6m 了，所以航向要单独看。

def test_heading_budget_catches_spin():
    assert heading_drifted({"yaw": 1.4}, 0.0) is False
    assert heading_drifted({"yaw": 19.9}, 0.0) is False
    assert heading_drifted({"yaw": 85.3}, 0.0) is True
    assert heading_drifted({"yaw": -163.2}, 0.0) is True


def test_heading_budget_is_measured_against_start():
    assert heading_drifted({"yaw": 100.0}, 80.0) is False      # 相对起点只转 20°
    assert heading_drifted({"yaw": 150.0}, 80.0) is True       # 转了 70°


def test_heading_budget_wraps_around_180():
    """350° 相对 10° 只差 20°，不能被当成 340°。"""
    assert heading_drifted({"yaw": 350.0}, 10.0) is False
    assert heading_drifted({"yaw": 10.0}, 350.0) is False
    assert heading_drifted({"yaw": 90.0}, 350.0) is True       # 差 100°


def test_heading_budget_boundary_is_exclusive():
    assert heading_drifted({"yaw": MAX_YAW_DRIFT}, 0.0) is False
    assert heading_drifted({"yaw": MAX_YAW_DRIFT + 0.1}, 0.0) is True


def test_heading_budget_is_configurable():
    assert heading_drifted({"yaw": 40.0}, 0.0, budget=60.0) is False
    assert heading_drifted({"yaw": 40.0}, 0.0, budget=20.0) is True


def test_heading_tolerates_missing_pose_fields():
    assert heading_drifted({}, 0.0) is False


def test_drift_tolerates_missing_pose_fields():
    assert drifted({}, 0.0) is False


# ── 方向约束（v1 只会沿 -x 走）──────────────────────────

def test_walk_direction_constant_documented():
    """WALK_DIR = -1 表示当前步态沿世界 -x；改步态时这个值必须跟着改。"""
    assert WALK_DIR == -1.0
    # 目标在 -x 方向才走得动；+x 或原地都该被拒（move_to 里的方向判据）
    assert (-2.0 - 0.0) * WALK_DIR > 0               # 走得动
    assert (2.0 - 0.0) * WALK_DIR <= 0               # 要掉头 → 拒
    assert (0.0 - 0.0) * WALK_DIR <= 0               # 已到达 → 由 arrived 先拦
