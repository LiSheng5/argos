import { NavLink, Route, Routes } from 'react-router-dom'
import { ConsoleProvider, useConsole } from './store.jsx'
import Overview from './pages/Overview.jsx'
import Runs from './pages/Runs.jsx'
import RunDetail from './pages/RunDetail.jsx'
import Robot from './pages/Robot.jsx'
import Memory from './pages/Memory.jsx'
import Playground from './pages/Playground.jsx'
import Settings from './pages/Settings.jsx'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/runs', label: 'Runs' },
  { to: '/robot', label: 'Robot' },
  { to: '/memory', label: 'Memory' },
  { to: '/playground', label: 'Playground' },
  { to: '/settings', label: 'Settings' },
]

function Sidebar() {
  const { connected, system } = useConsole()
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">ARGOS</div>
        <div className="brand-sub">EMBODIED AI RUNTIME</div>
      </div>
      <nav className="nav">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === '/'}
            className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}
          >
            {n.label}
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-foot">
        <div className="row" style={{ marginBottom: 4 }}>
          <span className={'dot ' + (connected ? 'dot-green' : 'dot-gray')} />
          <span>{connected ? 'Live' : 'Offline'}</span>
        </div>
        <div>{system?.executor ? `executor · ${system.executor}` : ''}</div>
      </div>
    </aside>
  )
}

export default function App() {
  return (
    <ConsoleProvider>
      <div className="layout">
        <Sidebar />
        <main className="main">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/runs" element={<Runs />} />
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/robot" element={<Robot />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="/playground" element={<Playground />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </ConsoleProvider>
  )
}
