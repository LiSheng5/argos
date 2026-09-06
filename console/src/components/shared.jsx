import { useRef } from 'react'
import { api } from '../api.js'
import { useConsole } from '../store.jsx'

const DOT_TONES = {
  online: 'dot-green', ok: 'dot-green', ready: 'dot-green', active: 'dot-green',
  connected: 'dot-green', success: 'dot-green', done: 'dot-green',
  error: 'dot-red', emergency: 'dot-red', tripped: 'dot-red', rejected: 'dot-red',
  failed: 'dot-red', disconnected: 'dot-gray', offline: 'dot-gray',
  busy: 'dot-amber', working: 'dot-amber', running: 'dot-blue',
  ai: 'dot-blue', robot: 'dot-purple', system: 'dot-purple', skipped: 'dot-gray',
}

export function Dot({ tone = 'gray' }) {
  return <span className={'dot ' + (DOT_TONES[tone] || 'dot-' + tone)} />
}

const PILL_TONES = { green: 'pill-green', red: 'pill-red', blue: 'pill-blue', purple: 'pill-purple', amber: 'pill-amber' }

export function Pill({ tone = '', children }) {
  return <span className={'pill ' + (PILL_TONES[tone] || '')}>{children}</span>
}

export function Metric({ label, value, unit = '', na = false }) {
  return (
    <div>
      <div className="metric-label">{label}</div>
      <div className={'metric-value' + (na ? ' na' : '')}>
        {na || value === null || value === undefined ? '—' : value}{!na && value !== null && value !== undefined ? unit : ''}
      </div>
    </div>
  )
}

function fmtCoord(v) { return v === null || v === undefined ? '—' : Number(v).toFixed(2) }

// ── 机器人外观图（用户上传；与相机严格分开）──────────────
export function RobotImage({ onChanged }) {
  const { profile, refresh } = useConsole()
  const inputRef = useRef(null)

  const pick = () => inputRef.current?.click()
  const onChange = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      await api.uploadImage(file)
      refresh()
      onChanged?.()
    } catch (err) { alert('上传失败：' + err.message) }
  }
  const remove = async () => {
    try { await api.deleteImage(); refresh(); onChanged?.() }
    catch (err) { alert('删除失败：' + err.message) }
  }

  return (
    <div className="robot-frame">
      <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp"
        style={{ display: 'none' }} onChange={onChange} />
      {profile?.imageUrl ? (
        <>
          <img src={profile.imageUrl} alt={profile.name || 'robot'} />
          <div className="robot-frame-caption">
            <span>{profile.name}</span>
            <div className="row">
              <button className="btn btn-sm" style={{ color: '#fff', background: 'rgba(0,0,0,.4)', borderColor: 'transparent' }} onClick={pick}>替换</button>
              <button className="btn btn-sm" style={{ color: '#fff', background: 'rgba(0,0,0,.4)', borderColor: 'transparent' }} onClick={remove}>移除</button>
            </div>
          </div>
        </>
      ) : (
        <div className="robot-empty">
          <div className="robot-empty-title">No robot image</div>
          <div style={{ marginBottom: 12 }}>Upload your robot →</div>
          <button className="btn" onClick={pick}>上传图片</button>
        </div>
      )}
    </div>
  )
}

// ── 实时相机（MJPEG；无源时诚实显示 No camera signal）────
export function CameraView({ compact = false }) {
  const { camera, robot } = useConsole()
  const hasStream = camera?.mode === 'url' || camera?.mode === 'usb'
  return (
    <div className="cam-frame">
      <div className="cam-badge">
        <span className="dot" style={{ background: hasStream ? '#34c759' : '#8e8e93' }} />
        {hasStream ? 'LIVE' : 'NO SIGNAL'}
      </div>
      {hasStream ? (
        <img src="/api/camera/stream.mjpg" alt="robot camera" />
      ) : (
        <div className="cam-empty">
          <div>No camera signal</div>
          {!compact && <div style={{ fontSize: 11 }}>Settings 里配置外部 MJPEG 或本机摄像头</div>}
        </div>
      )}
      {!compact && (
        <div className="cam-telemetry">
          <div>{robot?.robotId || 'ARGOS-01'}</div>
          <div>x: {fmtCoord(robot?.pose?.x)}&nbsp;&nbsp;y: {fmtCoord(robot?.pose?.y)}
            &nbsp;&nbsp;yaw: {robot?.pose?.yaw === null || robot?.pose?.yaw === undefined ? '—' : Math.round(robot.pose.yaw) + '°'}</div>
        </div>
      )}
    </div>
  )
}

// ── 急停横幅 ─────────────────────────────────────────
export function EstopBanner() {
  const { safety, refresh } = useConsole()
  if (!safety?.estop) return null
  const release = async () => {
    try { await api.estop(false); refresh() } catch (e) { alert('解除失败：' + e.message) }
  }
  return (
    <div className="estop-banner" style={{ marginBottom: 24 }}>
      <div>
        <strong>Emergency stop engaged</strong>
        <div style={{ fontSize: 12.5, opacity: 0.9 }}>所有动作已拒绝，正在运行的长动作已从内部退出</div>
      </div>
      <button className="btn" onClick={release}>解除急停</button>
    </div>
  )
}

export function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

export function fmtRel(ts) {
  if (!ts) return ''
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${Math.floor(s / 3600)}h`
}
