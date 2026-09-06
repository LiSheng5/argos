// 全部走相对路径 /api —— dev 由 Vite 代理到 127.0.0.1:8766，生产由 FastAPI 托管。
async function req(path, opts = {}) {
  const res = await fetch(path, opts)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      detail = j.detail || j.error || detail
    } catch (_) { /* 非 JSON 响应，用状态码兜底 */ }
    throw new Error(detail)
  }
  return res.json()
}

const post = (path, body) =>
  req(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })

export const api = {
  system: () => req('/api/system'),
  health: () => req('/api/system/health'),

  brain: () => req('/api/brain'),
  robot: () => req('/api/robot'),
  robotState: () => req('/api/robot/state'),
  saveProfile: (data) => post('/api/robot/profile', data),
  uploadImage: async (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return req('/api/robot/image', { method: 'POST', body: fd })
  },
  deleteImage: () => req('/api/robot/image', { method: 'DELETE' }),

  runs: (params = {}) => req('/api/runs?' + new URLSearchParams(params)),
  createRun: (text) => post('/api/runs', { text }),
  run: (id) => req(`/api/runs/${id}`),

  events: (params = {}) => req('/api/events?' + new URLSearchParams(params)),

  tasks: () => req('/api/tasks'),

  safety: () => req('/api/safety'),
  estop: (on) => post('/api/safety/estop', { on }),

  memory: () => req('/api/memory'),
  memorySearch: (q, topK = 10) =>
    req(`/api/memory/search?q=${encodeURIComponent(q)}&top_k=${topK}`),

  models: () => req('/api/llm/models'),
  chat: (payload) => post('/api/llm/chat', payload),
  llmSettings: () => req('/api/settings/llm'),
  saveLlmSettings: (data) => post('/api/settings/llm', data),

  camera: () => req('/api/camera'),
  saveCamera: (data) => post('/api/camera', data),
}
