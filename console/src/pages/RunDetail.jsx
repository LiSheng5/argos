import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api.js'
import { Dot, Pill, fmtTime } from '../components/shared.jsx'

const STATUS = {
  running: { tone: 'blue', label: 'Running' },
  completed: { tone: 'green', label: 'Completed' },
  failed: { tone: 'red', label: 'Failed' },
  rejected: { tone: 'amber', label: 'Rejected' },
}

// 八节从上到下：User Command → Brain → LLM → Safety → Task → Executor → Robot → Result
const ORDER = ['input', 'brain', 'llm', 'safety', 'task', 'executor', 'robot', 'result']

export default function RunDetail() {
  const { id } = useParams()
  const [run, setRun] = useState(null)
  const [events, setEvents] = useState([])
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    api.run(id).then((d) => { if (alive) { setRun(d.run); setEvents(d.events) } })
      .catch((e) => alive && setErr(e.message))
    return () => { alive = false }
  }, [id])

  if (err) return <div className="alert alert-red">加载失败：{err}</div>
  if (!run) return <div className="empty-state">加载中…</div>

  const st = STATUS[run.status] || { tone: '', label: run.status }
  const stages = {}
  run.stages.forEach((s) => { stages[s.key] = s })

  return (
    <>
      <div className="page-head">
        <div className="row" style={{ marginBottom: 6 }}>
          <Link to="/runs" className="dim" style={{ fontSize: 13 }}>← Runs</Link>
        </div>
        <h1 className="page-title" style={{ fontSize: 26 }}>{run.command || '(空指令)'}</h1>
        <div className="row" style={{ marginTop: 8 }}>
          <Pill tone={st.tone}>{st.label}</Pill>
          {run.source === 'autonomous' && <Pill>autonomous</Pill>}
          <span className="dim" style={{ fontSize: 12 }}>run {run.id}</span>
        </div>
      </div>

      {run.reply && (
        <div className="panel" style={{ marginBottom: 28 }}>
          <div className="section-title" style={{ marginBottom: 6 }}>Reply</div>
          <div style={{ fontSize: 14 }}>{run.reply}</div>
        </div>
      )}

      <div className="split">
        <div>
          <div className="section-head"><span className="section-title">Pipeline</span></div>
          <div className="card" style={{ padding: '22px 24px' }}>
            <div className="pipeline">
              {ORDER.map((key) => {
                const s = stages[key]
                if (!s) return null
                const dot = s.status === 'done' ? 'done' : s.status === 'failed' ? 'failed'
                  : s.status === 'running' ? 'running' : s.status === 'skipped' ? 'skipped' : ''
                return (
                  <div key={key} className="pipe-step">
                    <div className={'pipe-dot ' + dot} />
                    <div className="pipe-body">
                      <div className="pipe-label">
                        {s.label}
                        <span className="dim" style={{ fontWeight: 400, marginLeft: 8 }}>{s.status}</span>
                      </div>
                      {s.detail && <div className="pipe-detail">{s.detail}</div>}
                      {s.data && <pre className="pipe-data">{JSON.stringify(s.data)}</pre>}
                    </div>
                    {s.at && <div className="event-time">{fmtTime(s.at)}</div>}
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div>
          <div className="section-head"><span className="section-title">Events</span></div>
          <div className="card card-tight">
            {events.length === 0 && <div className="empty-state">没有事件</div>}
            {events.slice().reverse().map((ev) => (
              <div key={ev.id} className="event-row">
                <span className="event-time">{fmtTime(ev.ts)}</span>
                <span className="event-msg">{ev.message}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
