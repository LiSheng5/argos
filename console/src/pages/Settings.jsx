import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useConsole } from '../store.jsx'

export default function Settings() {
  const { system, camera, profile, refresh } = useConsole()
  const [llm, setLlm] = useState(null)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [timeout, setTimeout] = useState(20)
  const [llmSaved, setLlmSaved] = useState(false)

  const [camMode, setCamMode] = useState('none')
  const [camUrl, setCamUrl] = useState('')
  const [camIndex, setCamIndex] = useState(0)
  const [camSaved, setCamSaved] = useState(false)

  useEffect(() => {
    api.llmSettings().then((c) => {
      setLlm(c); setBaseUrl(c.baseUrl); setModel(c.model); setTimeout(c.timeout)
    }).catch(() => {})
  }, [])
  useEffect(() => {
    if (camera) { setCamMode(camera.mode || 'none'); setCamUrl(camera.url || ''); setCamIndex(camera.usbIndex || 0) }
  }, [camera])

  const saveLlm = async () => {
    try {
      await api.saveLlmSettings({ baseUrl, model, timeout, apiKey: apiKey || undefined })
      setApiKey(''); setLlmSaved(true)
      refresh()
      setTimeout(() => setLlmSaved(false), 1500)
    } catch (e) { alert('保存失败：' + e.message) }
  }

  const saveCam = async () => {
    try {
      await api.saveCamera({ mode: camMode, url: camUrl || undefined, usbIndex: camIndex })
      setCamSaved(true); refresh()
      setTimeout(() => setCamSaved(false), 1500)
    } catch (e) { alert('保存失败：' + e.message) }
  }

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">Settings</h1>
        <p className="page-sub">本地配置。API key 只存在这台机器的 api_key.txt（已 gitignore），不上传。</p>
      </div>

      <div className="section-head"><span className="section-title">LLM</span></div>
      <div className="card" style={{ maxWidth: 640 }}>
        <div className="field">
          <label className="field-label">API Key</label>
          <input className="input" type="password" placeholder={llm?.maskedKey ? `已配置 ${llm.maskedKey}` : 'sk-…（留空则不变）'}
            value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off" />
          <div className="field-hint">写入仓库根 api_key.txt，与 ArgOS 的读取路径一致，填完立刻生效。</div>
        </div>
        <div className="field">
          <label className="field-label">Base URL</label>
          <input className="input" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </div>
        <div className="grid grid-2">
          <div className="field">
            <label className="field-label">Model</label>
            <input className="input" value={model} onChange={(e) => setModel(e.target.value)} />
          </div>
          <div className="field">
            <label className="field-label">Timeout（秒）</label>
            <input className="input" type="number" value={timeout} onChange={(e) => setTimeout(Number(e.target.value))} />
          </div>
        </div>
        <button className="btn btn-primary" onClick={saveLlm}>{llmSaved ? '已保存' : '保存'}</button>
        <div className="field-hint" style={{ marginTop: 10 }}>
          提醒：LLM 只做措辞与反思，编译 / 落账 / 安全闸永不 LLM 化（铁律）。
        </div>
      </div>

      <div className="section-head" style={{ marginTop: 36 }}><span className="section-title">Camera</span></div>
      <div className="card" style={{ maxWidth: 640 }}>
        <div className="field">
          <label className="field-label">来源</label>
          <select className="select" value={camMode} onChange={(e) => setCamMode(e.target.value)}>
            <option value="none">无（No camera signal）</option>
            <option value="url">外部 MJPEG URL</option>
            <option value="usb">本机 USB 摄像头</option>
          </select>
        </div>
        {camMode === 'url' && (
          <div className="field">
            <label className="field-label">MJPEG 地址</label>
            <input className="input" placeholder="http://192.168.1.x:8080/stream" value={camUrl} onChange={(e) => setCamUrl(e.target.value)} />
          </div>
        )}
        {camMode === 'usb' && (
          <div className="field">
            <label className="field-label">摄像头序号</label>
            <input className="input" type="number" value={camIndex} onChange={(e) => setCamIndex(Number(e.target.value))} />
            <div className="field-hint">需要 opencv（pip install opencv-python）。</div>
          </div>
        )}
        <button className="btn btn-primary" onClick={saveCam}>{camSaved ? '已保存' : '保存'}</button>
      </div>

      <div className="section-head" style={{ marginTop: 36 }}><span className="section-title">About</span></div>
      <div className="card" style={{ maxWidth: 640 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="muted">ArgOS Console</span><span>v{system?.version || '0.1.0'}</span>
        </div>
        <div className="row" style={{ justifyContent: 'space-between', marginTop: 8 }}>
          <span className="muted">Executor</span><span>{system?.executor || '—'}</span>
        </div>
        <div className="row" style={{ justifyContent: 'space-between', marginTop: 8 }}>
          <span className="muted">Uptime</span><span>{system?.uptimeSec != null ? system.uptimeSec + 's' : '—'}</span>
        </div>
        <div className="field-hint" style={{ marginTop: 14 }}>
          Web 是 Observation + Control Layer。所有真实控制（E-stop / 移动 / 取消）都经过现有 SafetyGate。
        </div>
      </div>
    </>
  )
}
