"""具身后端目录。

现在只有 `simulator_backend.py`（仿真，第一公民）。
未来接真机时在这里新增 `go2_backend.py`（实现同一 `EmbodimentBackend` 协议），
上层 Brain / Planner / Memory / Reflector **零改动**。

⚠️ 本轮不写任何真机代码，也不伪造 real executor。
"""
