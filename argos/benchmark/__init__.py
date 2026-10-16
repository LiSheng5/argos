"""Reflection Benchmark（Phase 7）—— 用数字回答"反思到底有没有用"。

组成：
  scenarios.py  20 个可复现场景（永久障碍 / 瞬时故障 / 通畅对照 / 低电量 / 链路不稳）
  configs.py    Agent 配置（核心四组 + 复核臂 + 语义软降权臂，共六组）
  runner.py     场景 × 配置 × seed 全矩阵，采集五个指标
  report.py     渲染 markdown 报告
  __main__.py   CLI：list / run / all

红线：**不许挑成功案例证明效果**（指令第八节）。跑出来是什么就写什么，负结果照写。
"""
