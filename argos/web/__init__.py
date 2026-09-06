"""ArgOS Web 层：观察 + 控制层（不接管决策）。

目录职责：
  models.py     数据模型（Step 3）
  events.py     Event Bus（Step 4）
  ws.py         WebSocket Gateway（Step 5）
  telemetry.py  Robot Telemetry（Step 6）
  upload.py     Robot Image Upload（Step 7）
  camera.py     Camera Stream（Step 8）
  store.py      Run / Event 落盘（SQLite）
  api.py        HTTP 路由汇总
  gateway.py    把上面这些挂到现有 FastAPI app

铁律：本层只读现有 ArgOS 的状态、只调用现有入口（try_command / estop），
不复制、不改写大脑与安全闸的任何逻辑。
"""
