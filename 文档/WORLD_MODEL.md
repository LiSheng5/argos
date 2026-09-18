# WORLD_MODEL —— 世界模型与几何约定

> 代码：`argos/world/state.py`（状态）+ `argos/world/mini_world.py`（几何）。
> 仿真能跑出什么见 `文档/SIMULATION.md`。

---

## 1. WorldState：唯一真相源

| 字段 | 类型 | 语义 |
|---|---|---|
| `robot` | `Pose(x, y, yaw, vx, vy, vyaw)` | 位姿（含速度分量）|
| `battery` | `float` | 电量百分比 |
| `obstacles` | `Dict[name, Rect]` | 障碍 |
| `objects` | `Dict[name, Any]` | 物体（迷你世界里主要是"看得见的地方"）|
| `locations` | `Dict[name, Pose]` | 具名地点（目标解析用）|
| `people` | `Dict[name, Any]` | 人（本世界为空，字段留着）|
| `events` | `List[str]` | 事件流（失败、跳闸都会落这里）|
| `tasks` | `List[str]` | 任务 |
| `sim_time` | `float` | **逻辑时钟** |
| `version` | `int` | 每次写入 `+1`（`touch()`）|
| `missing` | `Tuple[str, ...]` | 本轮**没读到的传感器名** |

两条纪律：

1. **只有 backend 能写**（`_sync` / `bump`）。Planner / Brain 拿到的是 `WorldView`；
2. `WorldView` 是**不可变投影**：字典降级为元组、`frozen=True`，改就抛 `FrozenInstanceError`。
   —— 旧系统"谁都能顺手改世界"的问题，在这里从类型上就堵死了。

`state.as_dict(items)` 是**唯一的形状转换入口**（批量对象 → 字典）。
踩过的坑：有数据源绕过它直接写 tuple 进 dict 字段 → `view()` 调 `.items()` 当场炸。

## 2. Mini Robot World（`mini_world.py`）

**房间 / 走廊**
| 名字 | 矩形（`x, y, w, h`）|
|---|---|
| `room_a` | 0, 0, 6, 6 |
| `hallway` | 5, 0, 4, 2 |
| `room_b` | 10, 0, 6, 6 |

**地点**：`room_a (0,0)` / `hallway (5,0)` / `door (7,0)` / `room_b (10,0)` / `charger (10,-2)`

**障碍**：`north_block` = `Rect(x=5, y=2, w=2, h=1.5)`（挡住北线）

**路线**（Planner 的偏好顺序就是声明顺序）：
- `north`：`(2,2) → (5,2) → (9,2) → (10,-2)` —— 短，但**第二段撞 `north_block`**
- `south`：`(2,-2) → (5,-2) → (9,-2) → (10,-2)` —— 长一点，畅通

> 这个"一条路被堵、另一条能绕"的最小结构，就是整个反思闭环的测试床：
> 先撞北线 → 换南线 → 记住教训 → 下次直接走南线。

## 3. 几何约定（**最容易踩的地方**）

```python
@dataclass(frozen=True)
class Rect:
    name: str
    x: float; y: float      # ⚠️ 是**角点**，不是 min/max
    w: float; h: float
```
- 范围是 `[x, x+w] × [y, y+h]`；**中心**得自己算 `(x + w/2, y + h/2)`；
- 需要 min/max 的场合（边界检查）另有一套 `boundaries` 字典，别混用；
- `blocked(ax, ay, bx, by)`：线段与所有障碍求交，返回**撞到的障碍名**或 `None`，
  内部按 `0.05m` 步长采样 —— 够用，但不是精确几何求交（这是已知简化）。

## 4. 缺数据（`missing`）

见 `文档/SAFETY_MODEL.md` §3。要点：
- `Observation.missing` → `WorldState.missing` → `WorldView.missing` 一路透传；
- 字段仍带**最后可用值**，但 `missing` 点名不可信的那个 —— **消费者必须先看 missing**；
- 闸门对缺 `pose` / `battery` 的移动是 **fail-closed**。

## 5. 怎么扩这个 世界

加**地点**：`mini_world.build_default_world()` 的 `locations` 里加一个 `(name, Pose)`，
并在 `planner.GOAL_WORDS` 里补中文/英文说法（否则听不懂）。
加**障碍**：`obstacles` 加 `Rect` —— 注意别把已有路线全堵死（那会变成"无路可走"，
是合法状态，但要有意为之）。
加**路线**：`routes` 加 `(name, waypoints)`；Planner 按声明顺序偏好，越靠前越优先。
加**新的世界变体用于实验**：别改默认世界，去 `benchmark/scenarios.py` 里加 `Scenario`
（它支持自定义 `routes` / `obstacles` / `max_steps` / 延迟 / 瞬时故障）。

⚠️ 两个坑（都踩过）：
1. **`obstacles=()` 不等于"没有障碍"** —— 空元组是 falsy，写成 `x if x else default`
   会让"无障碍场景"悄悄带回默认障碍。用 `None` 表示"沿用默认"。
2. 加地点后**忘了同步 `GOAL_WORDS`** → planner 会说"目标无法理解"（这是对的：认不出就不瞎猜）。

## 6. 已知简化

- 2D、轴对齐矩形、无高度、无遮挡（除了感知半径）；
- 无代价地图 / 无连续避障（移动是"直线段 + 撞了就停"）；
- 无动态障碍 / 无人流；
- `people` / `objects` 字段存在但内容极少 —— **不硬造数据来让世界"看起来丰富"**。
