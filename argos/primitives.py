"""机器人运动原语白名单（防篡改）。
对应 npc/reviewer.py 的游戏动作白名单，机器人版只放行白名单运动原语。
铁律：LLM 零关节/零文件直控 —— 所有写出必须命中 ALLOWED_MOTION_ACTIONS。
"""
ALLOWED_MOTION_ACTIONS = ("move_to", "navigate", "grab", "release")

# 纵深防御：任务/参数里出现这些字段名/值的字段 -> 安全闸直接拒绝
FORBIDDEN_MOTION_TOKENS = frozenset({"file", "path", "write", "read", "exec",
                                     "shell", "delete", "open"})