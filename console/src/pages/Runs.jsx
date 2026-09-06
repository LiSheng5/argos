import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useConsole } from '../store.jsx'
import { Dot, Pill, fmtRel, fmtTime } from '../components/shared.jsx'

const STATUS = {
  running: { tone: 'blue', dot: 'running', label: 'Running' },
  completed: { tone: 'green', dot: 'done', label: 'Completed' },
  failed: { tone: 'red', dot: 'failed', label: 'Failed' },
  rejected: { tone: 'amber', dot: 'busy', label: 'Rejected' },
}

export default function Runs() {
  const { runs } = useConsole()
  const navigate = useNavigate()
  const [filter, setFilter] = useState('')

  const list = runs.filter((r) => !filter || r.status === filter)

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">Runs</h1>
        <p className="page-sub">每一次指令都是一条 Run，从 Input 到 Result 全程留痕。</p>
      </div>

      <div className="row" style={{ marginBottom: 18 }}>
        {['', 'running', 'completed', 'failed', 'rejected'].map((s) => (
          <button key={s || 'all'} className={'btn btn-sm' + (filter === s ? ' btn-primary' : '')} onClick={() => setFilter(s)}>
            {s === '' ? '全部' : (STATUS[s]?.label || s)}
          </button>
        ))}
      </div>

      <div className="card card-tight">
        {list.length === 0 && <div className="empty-state">还没有 Run。回 Overview 发一条指令。</div>}
        {list.map((r) => {
          const st = STATUS[r.status] || { tone: '', dot: 'gray', label: r.status }
          return (
            <div key={r.id} className="run-row" style={{ cursor: 'pointer' }} onClick={() => navigate(`/runs/${r.id}`)}>
              <Dot tone={st.dot} />
              <div className="run-cmd">{r.command || '(空指令)'}</div>
              <Pill tone={st.tone}>{st.label}</Pill>
              {r.source === 'autonomous' && <Pill>autonomous</Pill>}
              <div className="run-meta">
                {fmtTime(r.createdAt)} · {fmtRel(r.createdAt)}
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}
