---
name: npc-sidekick-dog
version: 1.0.0
author: NPCSidekick
description: >
  控制本机的 NPCSidekick 宇树机器狗（仿真）：它有落账口大脑——接单前过安全闸，
  办事记记忆，会自主巡逻/待命/低电量回桩。触发词：机器狗、宇树、Go2、狗子、
  robot dog、sidekick、巡逻、狗在哪、让狗去、急停。
---

# NPCSidekick 机器狗

本机大脑服务：`http://127.0.0.1:8766`（robot/server.py，FastAPI）。
狗认识的话只有四类：**去某地 / 巡逻 / 拿某物 / 放下**。地点表缺省有：
充电桩、家（都在原点）、桌边、门口。

## 铁律（必须遵守）

1. **原话转述**：把狗的 `reply` 逐字转给用户，禁止自己编造"办好了"。
   狗的设计就是诚实拒绝（急停/电量/边界/听不懂），拒绝也是正常回复。
2. **狗说"我不认识"时**：最多用上面四类话改述一次（例："跳个舞"→ 无对应
   动词，如实说狗不会）；仍不行就如实报告，不要反复换词试探。
3. **狗说"刚失败过，先缓缓"**：这是失败冷却（约 15 秒），等 15 秒最多重试
   一次，仍拒绝就如实转述。
4. **"停/停下/急停"**：立即执行急停，不询问、不确认。
5. **解除急停**：只在用户明确要求恢复时执行，并转述狗的后续表现。

## 指令（curl）

```bash
# 对狗说话（主力端点）——回复在 JSON 的 reply 字段里
curl -s -X POST http://127.0.0.1:8766/api/command \
  -H "Content-Type: application/json" -d '{"text":"去门口"}'

# 看状态（位置/电量/在干嘛/最近 5 条记忆）
curl -s http://127.0.0.1:8766/api/state

# 翻全部记忆
curl -s http://127.0.0.1:8766/api/memory

# 急停 / 解除
curl -s -X POST http://127.0.0.1:8766/api/estop -H "Content-Type: application/json" -d '{"on":true}'
curl -s -X POST http://127.0.0.1:8766/api/estop -H "Content-Type: application/json" -d '{"on":false}'
```

## 说法对照

| 用户说 | 动作 |
|---|---|
| 去[门口/桌边/家/充电桩] | `POST /api/command` `{"text":"去门口"}` |
| 巡逻一圈 / 巡检 | `{"text":"巡逻一圈"}` |
| 拿[某物]（如拿小球） | `{"text":"拿小球"}` |
| 放下 / 松开 | `{"text":"放下"}` |
| 你在哪 / 在干嘛 / 电量 | `GET /api/state` |
| 你记得什么 | `GET /api/memory` |
| 停 / 急停 | `POST /api/estop` `{"on":true}` |
| 可以动了 / 解除急停 | `POST /api/estop` `{"on":false}` |

注意：地点表之外的地点（如"厨房"）狗不认识，会诚实拒绝；要加地点需改
robot/brain.py 的 DEFAULT_PLACES（或建 brain 时传 places）。

## 故障处理

- **连接被拒 / 超时**：大脑服务没开。让用户双击 `robot\启动机器人服务器.bat`
  （或在本目录跑 `python -m robot.server`），然后再试。
- **reply 含"急停"**：如实转述；用户要继续时先解除急停。
- **reply 含"先缓缓"**：按铁律 3 处理。
- **/api/state 里 `estop: true`**：狗趴窝中，此时任何移动请求都会被拒，
  先告诉用户急停是开着的。
