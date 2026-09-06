# ArgOS Console 使用说明

> ArgOS 的 Web 观察 + 控制层。**它只观测与下发指令，不决策**——
> 编译、落账、安全判定仍在 ArgOS（brain / safety / executor），Web 一行都不复制。

## 一、怎么跑

两个进程，先起后端再起前端（或只起后端，用浏览器直接开 5173）：

```bash
# 1) 后端（127.0.0.1:8766）
python -m argos.web.gateway --executor sim        # 纯逻辑仿真
python -m argos.web.gateway --executor dds        # 物理仿真 / DDS（会真走）

# 2) 前端（localhost:5173，自动代理 /api 到 8766）
cd console
npm install
npm run dev
```

旧的 `python -m argos.server` 入口完全不受影响。

## 二、页面

| 页 | 干什么 |
|---|---|
| Overview | Hero + 你的机器人图 + 实时相机 + Brain/Safety/Robot 三状态 + Latest Activity + 发起 Run |
| Runs | 所有 Run（用户指令 + 自主日常），点进去看八节流水线 |
| Run Detail | User Command → Brain → LLM → Safety → Task → Executor → Robot → Result |
| Robot | 上传 / 替换 / 删除机器人外观图，看实时位姿与遥测 |
| Memory | 搜记忆卡（recency + relevance + importance 加权） |
| Playground | Direct LLM（纯对话）或 ArgOS Brain（真的落账执行） |
| Settings | 填 API key（只存本地 api_key.txt）、配相机源、机器人 Profile |

## 三、几个关键设计（诚实优先）

1. **机器人外观图 ≠ 相机**：`robot_profile.imageUrl`（你上传）和
   `robot.camera_stream`（实时）是两个字段，永不混用。
2. **拿不到的数据就是 —**：温度 / CPU / 延迟目前执行器不上报，UI 显示 — ，
   不造数。
3. **LLM 不是 Run 的必经环节**：真实链路是 规则编译 → 落账 → 安全闸 → 执行，
   LLM 只做措辞。Run Detail 里 LLM 一节会如实标 skipped（未配 key）。
4. **所有控制过 SafetyGate**：E-stop / 移动 / 取消都走现有 `brain.estop()` /
   `RobotBackend.apply()`，Web 没有捷径。

## 四、架构（Web 层 = 包一层，不进去改）

```
argos/web/
  models.py      数据模型（camelCase；缺数据 = null）
  events.py      Event Bus（订阅者隔离 + 环形缓冲）
  store.py       Run / Event / Settings → SQLite（argos/store/argos.db）
  telemetry.py   现有状态 → 统一 RobotState
  upload.py      机器人图（magic bytes 校验 + uuid 文件名）
  camera.py      MJPEG（外部 URL 转发 / 本机 USB / 无源 No camera signal）
  bridge.py      Console 中枢 + InstrumentedBackend（包装埋点，返回值透传）
  ws.py          /api/ws（Event Bus 订阅者 + 分频推送）
  api.py         REST 路由
  gateway.py     装配入口（只在它这里加 CORS）
```

埋点方式：**不改 brain/safety/executor 内部** —— 安全闸裁决靠包装 `brain.backend`，
tick 靠 `server.py` 多带一个可选 sink 回调，指令靠 Web 层自己包 `try_command`。

## 五、测试

```bash
python -m pytest tests -q -p no:cacheprovider
# 新增 tests/test_web_console.py（10 例）：原有端点不回归、Run 全链路、
# 急停过闸、坏图拒绝、WS 快照、缺传感器=null
```
