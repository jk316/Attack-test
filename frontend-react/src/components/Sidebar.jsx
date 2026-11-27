import { useState } from 'react'
import { useLocation, Link } from 'react-router-dom'
import { Icon } from './ui'

export default function Sidebar() {
  const { pathname } = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const onList = pathname === '/' || pathname.startsWith('/experiments/')
  const onMonitor = pathname === '/monitor'

  return (
    <aside className={`sidebar${collapsed ? ' collapsed' : ''}`}>
      <div className="brand">
        <div className="logo">攻</div>
        {!collapsed && (
          <div>
            <div className="name">攻防实验控制台</div>
            <div className="sub">ATTACK LAB CONSOLE</div>
          </div>
        )}
      </div>
      <nav className="nav">
        <Link to="/" className={onList ? 'active' : ''} title="实验列表">
          <Icon name="list" />{!collapsed && <span>实验列表</span>}
        </Link>
        <Link to="/monitor" className={onMonitor ? 'active' : ''} title="实时观测">
          <Icon name="activity" />{!collapsed && <span>实时观测</span>}
        </Link>
      </nav>
      <div className="foot">
        {!collapsed && <div className="warn">⚠ 仅限可信内网 · 无鉴权</div>}
        <button
          type="button"
          className="collapse-btn"
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? '展开导航' : '收起导航'}
        >
          <Icon name="panel" />
        </button>
      </div>
    </aside>
  )
}
