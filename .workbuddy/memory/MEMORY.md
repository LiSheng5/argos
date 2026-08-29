# NPCSidekick robot —— 项目长期记忆

## 硬件硬门槛（2026-08-29 查证，来源：宇树官网支持页）

**Go2 分型号，只有部分型号开放二次开发：**

| 型号 | AIR | PRO | X | EDU |
|---|---|---|---|---|
| 二次开发（DDS） | 无 | 无 | 基础支持 | 支持 |

AIR / PRO **官方不开放**二次开发 → 真机 DDS 路线走不通。做任何真机规划前先确认型号。

其他全系/型号差异（影响功能可行性）：
- 4D LiDAR-L2 + 探物避障：**全系标配，开机默认开启** → 避障不必从零造
- 语音功能：PRO / X / EDU 有，AIR 无
- 充电桩回充：仅 X / EDU 支持（对应 brain 的"回充电桩"日常）
- 足端力传感器、深度相机：仅 EDU
- 机械臂（D1，6自由度+爪夹）：选配 → 不装则 `grab` 永远是假的
- 官方 L2 SLAM 开源；雷达可选 MID-360 / 禾赛 XT16 做导航

## 控制路线的关键判断

`SportClient.Move(vx, vy, vyaw)` 由狗自身小脑实现，已支持全向移动 + 转向
（官方示例 `example/go2/high_level/go2_sport_client.py` 里有 `Move(0,0,0.5)` 原地转）。

→ **真机上转弯不需要自己调步态。** 当前在 DDS 低层手调 trot 只能走直线（v1 限制），
那是"造轮子"路线；接真机时优先评估高层 SportClient，能省掉大量调参。

## 环境事实

- 唯一能跑测试的 venv：`C:\Users\Administrator\.workbuddy\binaries\python\envs\default`
  （已装 pytest / fastapi / httpx）
- **mujoco / cyclonedds / unitree_sdk2py 未装** → test_sim_smoke(2)、test_dds_sim(1)、
  test_dds_walk(1) 三个是 skip，DDS"真走 2m"的结论**尚未复验**
- 装法见 `requirements.txt`（含上游拉取命令与当前 commit 号）
- 基线：`pytest robot/tests -q -p no:cacheprovider` → 41 passed, 3 skipped

## 规矩 / 教训

- **测试钉必须反向验证**：写完回归测试后，把代码退回修复前的行为跑一遍，
  确认钉子会如期失败。第一版 P0-2 的探针测的是"阻塞结束后"而非"阻塞期间"，
  退化代码照样通过 —— 是反向验证抓出来的。（2026-08-29 教训）
- **提交身份分辨不出人**：用 `-c user.name/-c user.email` 临时身份提交时，
  author 字段都一样，只能靠时间戳 + diff 内容核对。给不同执行者配不同 committer 名。
