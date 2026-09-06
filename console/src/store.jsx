// 全局状态：WebSocket 为主，REST 只做首次填充与写操作后的刷新。
// 页面不轮询 —— 需求 §13 要求实时数据靠 WS 推，不是每秒拉一次。
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'

const ConsoleContext = createContext(null)

const EMPTY = {
  system: null, robot: null, brain: null, safety: null,
  profile: null, camera: null, runs: [], events: [],
}

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/api/ws`
}

export function ConsoleProvider({ children }) {
  const [data, setData] = useState(EMPTY)
  const [connected, setConnected] = useState(false)
  const timerRef = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const [system, robotRes, brain, safety, camera, runs, events] =
        await Promise.all([
          api.system(), api.robot(), api.brain(), api.safety(),
          api.camera(), api.runs({ limit: 50 }), api.events({ limit: 60 }),
        ])
      setData((d) => ({
        ...d, system, brain, safety, camera,
        robot: robotRes.state, profile: robotRes.profile,
        runs: runs.runs || [], events: events.events || [],
      }))
    } catch (e) {
      console.warn('[console] refresh failed:', e.message)
    }
  }, [])

  // 事件来了延迟补一次列表刷新（合并短时间内的多条事件，不打爆接口）
  const scheduleRefresh = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(refresh, 250)
  }, [refresh])

  useEffect(() => {
    let closed = false
    let retry = 0
    let ws

    const connect = () => {
      if (closed) return
      ws = new WebSocket(wsUrl())
      ws.onopen = () => { setConnected(true); retry = 0 }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) setTimeout(connect, Math.min(1000 * ++retry, 5000))
      }
      ws.onerror = () => ws?.close()
      ws.onmessage = (m) => {
        let msg
        try { msg = JSON.parse(m.data) } catch { return }
        const t = msg.type
        if (t === 'snapshot') {
          setData((d) => ({ ...d, ...(msg.data || {}) }))
        } else if (t === 'robot.state') {
          setData((d) => ({ ...d, robot: msg.data }))
        } else if (t === 'robot.telemetry') {
          const tm = msg.data || {}
          setData((d) => (d.robot ? {
            ...d,
            robot: { ...d.robot, battery: tm.battery, temperature: tm.temperature, cpu: tm.cpu },
          } : d))
        } else if (t === 'event.created') {
          setData((d) => ({ ...d, events: [msg.data, ...d.events].slice(0, 200) }))
          scheduleRefresh()
        }
      }
    }
    connect()
    refresh()                       // 首次挂载先补一次 REST，WS 慢半拍也不空
    return () => { closed = true; ws?.close() }
  }, [refresh, scheduleRefresh])

  const value = useMemo(
    () => ({ ...data, connected, refresh }), [data, connected, refresh])
  return <ConsoleContext.Provider value={value}>{children}</ConsoleContext.Provider>
}

export function useConsole() {
  const ctx = useContext(ConsoleContext)
  if (!ctx) throw new Error('useConsole 必须在 ConsoleProvider 内使用')
  return ctx
}
