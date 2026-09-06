import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'

export default function Playground() {
  const [mode, setMode] = useState('direct')
  const [message, setMessage] = useState('')
  const [system, setSystem] = useState('你是 ArgOS，一只诚实的机器狗。')
  const [advOpen, setAdvOpen] = useState(false)
  const [maxTokens, setMaxTokens] = useState(200)
  const [temperature, setTemperature] = useState(0.7)
  const [loading, setLoading] = useState(false)
  const [log, setLog] = useState([])
  const [models, setModels] = useState(null)

  useEffect(() => {
    api.models().then((r) => setModels(r)).catch(() => setModels({ models: [], error: '拉取失败' }))
  }, [])

  const run = async () => {
    const text = message.trim()
    if (!text || loading) return
    setLoading(true)
    setLog((l) => [...l, { who: 'you', text }])
    setMessage('')
    try {
      const r = await api.chat({
        mode, message: text, system,
        maxTokens, temperature,
      })
      setLog((l) => [...l, { who: 'ai', text: r.reply, meta: r }])
    } catch (e) {
      setLog((l) => [...l, { who: 'ai', text: '出错：' + e.message, err: true }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">LLM Playground</h1>
        <p className="page-sub">Test how ArgOS thinks.</p>
      </div>

      <div className="mode-switch" style={{ marginBottom: 16 }}>
        <button className={mode === 'direct' ? 'on' : ''} onClick={() => setMode('direct')}>Direct LLM</button>
        <button className={mode === 'brain' ? 'on' : ''} onClick={() => setMode('brain')}>ArgOS Brain</button>
      </div>
      <div className="field-hint" style={{ marginBottom: 20, maxWidth: 560 }}>
        {mode === 'direct'
          ? 'Direct LLM：User → LLM。纯对话，不碰机器人、不过安全闸。'
          : 'ArgOS Brain：User → Brain → LLM → Safety → Executor。会真的落账并可能让机器人动起来。'}
      </div>

      <div className="card" style={{ maxWidth: 720 }}>
        <div className="chat-log">
          {log.length === 0 && (
            <div className="dim" style={{ textAlign: 'center', padding: '40px 0' }}>
              输入一句话，看 ArgOS 怎么回应。
            </div>
          )}
          {log.map((m, i) => (
            <div key={i} className={'chat-msg ' + (m.who === 'you' ? 'chat-you' : 'chat-ai')}>
              <div className="chat-who">{m.who === 'you' ? 'You' : 'ArgOS'}</div>
              <div className="chat-msg" style={{ color: m.err ? '#c62828' : undefined }}>{m.text}</div>
              {m.meta && (
                <div className="chat-meta">
                  {m.meta.model && `model ${m.meta.model} · `}
                  {m.meta.elapsedMs != null && `${m.meta.elapsedMs}ms`}
                  {m.meta.runId && <> · <Link to={`/runs/${m.meta.runId}`} style={{ color: '#0b6bcb' }}>查看 Run →</Link></>}
                </div>
              )}
            </div>
          ))}
          {loading && <div className="dim">思考中…</div>}
        </div>

        <div className="command-bar" style={{ marginTop: 16 }}>
          <input
            className="input"
            placeholder="Type something…"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && run()}
          />
          <button className="btn btn-primary" onClick={run} disabled={!message.trim() || loading}>Run →</button>
        </div>
      </div>

      <div className="advanced" style={{ maxWidth: 720, marginTop: 20 }}>
        <div className="advanced-head" onClick={() => setAdvOpen(!advOpen)}>
          <span>Advanced</span>
          <span className="dim">{advOpen ? '▾' : '▸'}</span>
        </div>
        {advOpen && (
          <div className="advanced-body">
            <div className="field">
              <label className="field-label">System Prompt</label>
              <textarea className="textarea" value={system} onChange={(e) => setSystem(e.target.value)} />
            </div>
            <div className="grid grid-2">
              <div className="field">
                <label className="field-label">Max tokens</label>
                <input className="input" type="number" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} />
              </div>
              <div className="field">
                <label className="field-label">Temperature</label>
                <input className="input" type="number" step="0.1" value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} />
              </div>
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label className="field-label">可用模型</label>
              {models === null ? <div className="dim">加载中…</div>
                : models.error && !models.models?.length
                  ? <div className="dim">{models.error || '未配置 API key'}</div>
                  : <div className="dim">{(models.models || []).join(' · ') || '未配置 API key'}{models.current ? `（当前 ${models.current}）` : ''}</div>}
            </div>
          </div>
        )}
      </div>
    </>
  )
}
