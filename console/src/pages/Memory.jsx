import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useConsole } from '../store.jsx'
import { fmtRel } from '../components/shared.jsx'

function Importance({ v }) {
  const n = Math.max(0, Math.min(9, Number(v) || 0))
  return (
    <span className="imp-bar" title={`importance ${n}`}>
      {Array.from({ length: 9 }, (_, i) => (
        <span key={i} className={'imp-cell' + (i < n ? ' on' : '')} />
      ))}
    </span>
  )
}

export default function Memory() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)   // null = 显示全量
  const [searching, setSearching] = useState(false)
  const [allEntries, setAll] = useState([])

  useEffect(() => {
    // 全量记忆走 REST（snapshot 里只有最近几条）
    api.memory().then((d) => setAll((d.entries || []).slice().reverse()))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!query.trim()) { setResults(null); return }
    const t = setTimeout(async () => {
      setSearching(true)
      try {
        const r = await api.memorySearch(query.trim())
        setResults(r.entries || [])
      } catch (e) { console.warn(e) }
      finally { setSearching(false) }
    }, 300)
    return () => clearTimeout(t)
  }, [query])

  const list = results !== null ? results : allEntries

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">Memory</h1>
        <p className="page-sub">What does ArgOS remember?</p>
      </div>

      <div className="field" style={{ maxWidth: 520 }}>
        <input
          className="input"
          placeholder="Search memories…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ padding: '12px 14px' }}
        />
        <div className="field-hint">
          {results !== null
            ? (searching ? '搜索中…' : `找到 ${list.length} 条相关记忆（recency + relevance + importance 加权）`)
            : `共 ${allEntries.length} 条记忆 · 内存里只保留活跃条目`}
        </div>
      </div>

      <div className="card card-tight" style={{ maxWidth: 760 }}>
        {list.length === 0 && (
          <div className="empty-state">{query ? '没有相关记忆' : '还没有记忆。跑几次指令就有记录了。'}</div>
        )}
        {list.map((m) => (
          <div key={m.id} className="mem-item">
            <div className="mem-content">{m.content}</div>
            <div className="mem-meta">
              <span>importance <Importance v={m.importance} /></span>
              <span>{m.importance}</span>
              {m.at && <span>{m.at}</span>}
              {m.created_at && <span>{fmtRel(m.created_at)} ago</span>}
              {m.archived && <span style={{ color: '#c62828' }}>archived</span>}
              {m.reflected && <span style={{ color: '#6b57d6' }}>reflected</span>}
            </div>
          </div>
        ))}
      </div>

      <div className="field-hint" style={{ marginTop: 16, maxWidth: 760 }}>
        检索算法：recency×0.5 + relevance×3（原词/同义词 + BM25）+ importance×2 + 一跳关联
        （向量锚点开启时走语义路与关键词路 RRF 融合）。记忆卡 = 可编辑 JSON（argos/store/robot_memory.json）。
      </div>
    </>
  )
}
