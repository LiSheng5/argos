import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useConsole } from '../store.jsx'
import { CameraView, Dot, Metric, RobotImage } from '../components/shared.jsx'

export default function Robot() {
  const { robot, profile, refresh } = useConsole()
  const [name, setName] = useState('')
  const [id, setId] = useState('')
  const [saved, setSaved] = useState(false)

  // 只在首次拿到 profile 时灌初值：之后每次 refresh() 都会换成新 profile 对象，
  // 无条件重置会把用户正在输入的内容冲掉。
  const inited = useRef(false)
  useEffect(() => {
    if (profile && !inited.current) {
      setName(profile.name || ''); setId(profile.id || '')
      inited.current = true
    }
  }, [profile])

  const saveProfile = async () => {
    try {
      await api.saveProfile({ name, id })
      setSaved(true)
      refresh()
      setTimeout(() => setSaved(false), 1500)
    } catch (e) { alert('保存失败：' + e.message) }
  }

  const connected = robot?.connection?.status === 'connected'

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">Robot</h1>
        <p className="page-sub">机器人外观图（你上传）与实时相机（机器人视角）是两个不同的东西。</p>
      </div>

      <div className="split">
        {/* 外观图 */}
        <div>
          <div className="section-head"><span className="section-title">Appearance</span></div>
          <RobotImage onChanged={refresh} />
          <div className="field-hint" style={{ marginTop: 10 }}>
            支持 PNG / JPG / JPEG / WEBP。这张图用于 Hero、Robot Status 与 Profile 展示。
          </div>

          <div className="section-head" style={{ marginTop: 28 }}><span className="section-title">Profile</span></div>
          <div className="card">
            <div className="field">
              <label className="field-label">名称</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label className="field-label">Robot ID</label>
              <input className="input" value={id} onChange={(e) => setId(e.target.value)} />
            </div>
            <button className="btn btn-primary" onClick={saveProfile}>{saved ? '已保存' : '保存'}</button>
          </div>
        </div>

        {/* 相机 + 状态 */}
        <div>
          <div className="section-head">
            <span className="section-title">Live Camera</span>
          </div>
          <CameraView />
        </div>
      </div>

      {/* 实时状态 */}
      <div className="section">
        <div className="section-head"><span className="section-title">Live State</span></div>
        <div className="card">
          <div className="row" style={{ marginBottom: 18 }}>
            <Dot tone={connected ? 'connected' : 'disconnected'} />
            <span style={{ fontWeight: 500 }}>{connected ? 'Connected' : 'Disconnected'}</span>
            <span className="dim" style={{ fontSize: 12 }}>runtime: {robot?.runtime?.state ?? '—'}</span>
          </div>
          <div className="metrics" style={{ marginTop: 0 }}>
            <Metric label="X" value={robot?.pose?.x == null ? null : robot.pose.x.toFixed(2)} />
            <Metric label="Y" value={robot?.pose?.y == null ? null : robot.pose.y.toFixed(2)} />
            <Metric label="Yaw" value={robot?.pose?.yaw == null ? null : Math.round(robot.pose.yaw)} unit="°" />
            <Metric label="Battery" value={robot?.battery == null ? null : Math.round(robot.battery)} unit="%" />
            <Metric label="Temperature" value={robot?.temperature == null ? null : Math.round(robot.temperature)} unit="°C" />
            <Metric label="CPU" value={robot?.cpu == null ? null : Math.round(robot.cpu)} unit="%" />
            <Metric label="Gripper" value={robot?.gripper || '空'} />
            <Metric label="E-stop" value={robot?.estop ? 'ON' : 'OFF'} />
          </div>
          <div className="field-hint" style={{ marginTop: 16 }}>
            Temperature / CPU 目前执行器没有上报，显示 — 是诚实的「没有这个传感器」，不是漏了。
          </div>
        </div>
      </div>
    </>
  )
}
