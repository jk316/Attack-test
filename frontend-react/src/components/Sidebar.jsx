import { useLocation, Link } from 'react-router-dom'
import { Icon } from './ui'

export default function Sidebar() {
  const { pathname } = useLocation()
  const onList = pathname === '/' || pathname.startsWith('/experiments/')
  const onMonitor = pathname === '/monitor'

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="logo">攻</div>
        <div>
          <div className="name">攻防实验控制台</div>
          <div className="sub">ATTACK LAB CONSOLE</div>
        </div>
      </div>
      <nav className="nav">
        <Link to="/" className={onList ? 'active' : ''}><Icon name="list" />实验列表</Link>
        <Link to="/monitor" className={onMonitor ? 'active' : ''}><Icon name="activity" />实时观测</Link>
      </nav>
      <div className="foot">
        <div className="warn">⚠ 仅限可信内网 · 无鉴权</div>
        <div>v0.2 · React 重构</div>
      </div>
    </aside>
  )
}
