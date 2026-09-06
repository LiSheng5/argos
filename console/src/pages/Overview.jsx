import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useConsole } from '../store.jsx'
import { CameraView, Dot, EstopBanner, Metric, Pill, RobotImage, fmtTime } from '../components/shared.jsx'

export default function Overview() {
  const { system, brain, safety, robot, events, runs, connected, refresh } = useConsole()
  const navigate = useNavigate()
  const [cmd, setCmd] = useState('')
  const [sending, setSending] = useState(false)

  const estop = safety?.estop
  const online = connected && system?.online

  const submit = async () => {
    const text = cmd.trim()
    if (!text || sending) return
    setSending(true)
    try {
      const run = await api.createRun(text)
      setCmd('')
      refresh()
      navigate(`/runs/${run.id}`)
    } catch (e) {
      alert('下发失败：' + e.message)
    } finally {
      setSending(false)
    }
  }

  const activeRun = runs.find((r) => r.status === 'running') || null

  return (
    <>
      <EstopBanner />

      {/* ── Hero ─────────────────────────────────────── */}
      <div className="split">
        <div>
          <div className="row" style={{ marginBottom: 18 }}>
            <Pill tone={online ? 'green' : 'red'}>
              <Dot tone={online ? 'online' : 'disconnected'} /> {online ? 'System Online' : 'Offline'}
            </Pill>
          </div>
          <h1 className="hero-title">ARGOS</h1>
          <p className="hero-sub">Intelligent robotics runtime. One sentence in, guarded motion out.</p>
          <div className="hero-actions">
            <button className="btn btn-primary" onClick={() => navigate('/playground')}>Test LLM</button>
            <button className="btn" onClick={() => document.getElementById('new-run')?.focus()}>Open Console</button>
          </div>
          <div className="section" style={{ marginTop: 32 }}>
            <div className="section-head">
              <span className="section-title">Robot</span>
            </div>
            <RobotImage />
          </div>
        </div>

        <div>
          <div className="section-head">
            <span className="section-title">Robot View</span>
            <span className="section-note">live camera</span>
          </div>
          <CameraView />
        </div>
      </div>

      {/* ── 三个核心状态 ──────────────────────────────── */}
      <div className="section">
        <div className="section-head">
          <span className="section-title">System</span>
        </div>
        <div className="grid grid-3">
          <div className="card state-card">
            <div className="state-card-title">
              <Dot tone={brain?.status === 'busy' ? 'busy' : 'ready'} /> Brain
            </div>
            <div className="state-card-meta">{brain?.status === 'busy' ? 'Working' : 'Ready'} · tick {brain?.tick ?? '—'}</div>
            <div className="state-card-desc">LLM + Planning + Memory</div>
            <div className="metrics">
              <Metric label="LLM" value={brain?.llmEnabled ? 'on' : 'off'} />
              <Metric label="Memory" value={brain?.memoryCount} na={brain?.memoryCount == null} />
              <Metric label="State" value={brain?.state} />
            </div>
          </div>

          <div className="card state-card">
            <div className="state-card-title">
              <Dot tone={estop ? 'emergency' : 'active'} /> Safety
            </div>
            <div className="state-card-meta">{estop ? 'Tripped' : 'Active'} · E-stop {estop ? 'ON' : 'OFF'}</div>
            <div className="state-card-desc">Policy + E-stop + Boundary</div>
            <div className="metrics">
              <Metric label="E-stop" value={estop ? 'ON' : 'OFF'} />
              <Metric label="Boundary" value={`±${safety?.boundaries?.x_max ?? '—'}`} />
              <Metric label="Last" value={safety?.lastDecision ? (safety.lastDecision.approved ? 'approved' : 'rejected') : '—'} />
            </div>
          </div>

          <div className="card state-card">
            <div className="state-card-title">
              <Dot tone={robot?.connection?.status === 'connected' ? 'connected' : 'disconnected'} /> Robot
            </div>
            <div className="state-card-meta">{robot?.connection?.status === 'connected' ? 'Connected' : 'Disconnected'} · {robot?.runtime?.state}</div>
            <div className="state-card-desc">Navigation + Execution + Sensors</div>
            <div className="metrics">
              <Metric label="Battery" value={robot?.battery === null ? null : Math.round(robot?.battery)} unit="%" na={robot?.battery == null} />
              <Metric label="Position" value={robot?.pose ? `${robot.pose.x.toFixed(1)}, ${robot.pose.y.toFixed(1)}` : '—'} />
              <Metric label="Temp" value={robot?.temperature === null ? null : Math.round(robot?.temperature)} unit="°C" na={robot?.temperature == null} />
            </div>
          </div>
        </div>
      </div>

      {/* ── 活动 + 当前 Run ───────────────────────────── */}
      <div className="section">
        <div className="split">
          <div>
            <div className="section-head">
              <span className="section-title">Latest Activity</span>
              <button className="btn btn-sm" onClick={() => navigate('/runs')}>View all</button>
            </div>
            <div className="card card-tight">
              {events.length === 0 && <div className="empty-state">还没有活动。发一条指令试试。</div>}
              {events.slice(0, 8).map((ev) => (
                <div key={ev.id}
                  className={'event-row' + (ev.runId ? ' clickable' : '')}
                  onClick={() => ev.runId && navigate(`/runs/${ev.runId}`)}>
                  <span className="event-time">{fmtTime(ev.ts)}</span>
                  <span className="event-msg">{ev.message}</span>
                  <span className={'event-cat cat-' + (ev.category || 'System')}>{ev.category}</span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="section-head">
              <span className="section-title">Current Run</span>
            </div>
            <div className="card">
              {activeRun ? (
                <div>
                  <div className="row" style={{ marginBottom: 6 }}>
                    <Dot tone="running" />
                    <span style={{ fontWeight: 500 }}>{activeRun.command}</span>
                  </div>
                  <div className="muted" style={{ fontSize: 13 }}>
                    状态 {activeRun.status} · 来源 {activeRun.source}
                  </div>
                  <div style={{ marginTop: 14 }}>
                    <button className="btn btn-sm" onClick={() => navigate(`/runs/${activeRun.id}`)}>查看详情 →</button>
                  </div>
                </div>
              ) : (
                <div className="empty-state">
                  当前没有进行中的 Run。
                  {runs.length > 0 ? '最近一次：' + runs[0].command : ''}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── 发起新 Run ────────────────────────────────── */}
      <div className="section">
        <div className="section-head">
          <span className="section-title">Start a new run</span>
        </div>
        <div className="card">
          <div className="command-bar">
            <input
              id="new-run"
              className="input"
              placeholder="给机器人下指令，例如「去门口」「巡逻一圈」「拿小球」"
              value={cmd}
              onChange={(e) => setCmd(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
            />
            <button className="btn btn-primary" onClick={submit} disabled={!cmd.trim() || sending}>
              {sending ? '下发中…' : 'Run →'}
            </button>
          </div>
          <div className="field-hint" style={{ marginTop: 8 }}>
            指令会经过 Brain 编译 → SafetyGate 预审 → 落账 → tick 执行，全程由 ArgOS 决策，Web 只做下发与观测。
          </div>
        </div>
      </div>
    </>
  )
}
