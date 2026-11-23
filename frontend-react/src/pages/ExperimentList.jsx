import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listExperiments } from '../lib/api'
import { EXPERIMENTS, STATUS_FILTERS } from '../lib/mock'
import { Button, Icon, IconButton, StatusBadge } from '../components/ui'
import CreateExperimentModal from '../components/CreateExperimentModal'

const counts = EXPERIMENTS.reduce((acc, r) => {
  acc[r.status] = (acc[r.status] || 0) + 1
  return acc
}, { all: EXPERIMENTS.length })

function SummaryCell({ summary }) {
  if (!summary) return <span className="muted">等待中…</span>
  if (summary.stopReason) return <span>停止原因 <b>{summary.stopReason}</b></span>
  const succCls = summary.succUp ? 'up' : summary.succDown ? 'down' : ''
  return (
    <div className="summary">
      {summary.rtt != null && <span>最终 RTT <b>{summary.rtt}</b></span>}
      {summary.succ && <span>成功率 <b className={succCls}>{summary.succ}</b></span>}
      {summary.attacks != null && <span>攻击 <b>{summary.attacks}</b></span>}
    </div>
  )
}

export default function ExperimentList() {
  const [rows, setRows] = useState([])
  const [filter, setFilter] = useState('all')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    let alive = true
    const load = () => listExperiments({ status: filter }).then(r => { if (alive) setRows(r) })
    load()
    const timer = setInterval(load, 5000)
    return () => { alive = false; clearInterval(timer) }
  }, [filter])

  // 便于直接预览弹窗：/#create
  useEffect(() => {
    if (window.location.hash === '#create') setCreating(true)
  }, [])

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>实验列表</h1>
          <div className="desc">历史与运行中的攻防实验 · 每 5s 自动刷新</div>
        </div>
        <Button variant="primary" icon="plus" onClick={() => setCreating(true)}>新建实验</Button>
      </div>

      <div className="banner"><Icon name="warn" size={15} />本工具仅用于授权的网络攻防实验与教学环境，所有流量工具均已设置 allowlist 与硬上限。</div>

      <div className="chips">
        {STATUS_FILTERS.map(([key, label]) => (
          <span key={key} className={`chip${filter === key ? ' active' : ''}`} onClick={() => setFilter(key)}>
            {label} <span className="n">{key === 'all' ? counts.all : (counts[key] || 0)}</span>
          </span>
        ))}
      </div>

      <div className="panel" style={{ padding: '8px 0 0' }}>
        <table className="list">
          <thead>
            <tr><th>实验 ID</th><th>目标 IP</th><th>状态</th><th>创建时间</th><th>结果摘要</th><th className="r">操作</th></tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id}>
                <td><span className="id">#{r.id}</span></td>
                <td><span className="ip">{r.targetIp}</span></td>
                <td><StatusBadge status={r.status} /></td>
                <td className="time">{r.createdAt}</td>
                <td><SummaryCell summary={r.summary} /></td>
                <td className="r">
                  <div className="row-actions">
                    <Link to={`/experiments/${r.id}`} className="btn btn-sm lime">详情</Link>
                    {r.status === 'running'
                      ? <IconButton icon="stop" title="停止" onClick={() => alert('设计稿：停止实验')} />
                      : <IconButton icon="trash" danger title={r.status === 'queued' ? '取消' : '删除'} onClick={() => alert('设计稿：软删除')} />}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding: '13px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--line)' }}>
          <span className="live"><span className="tick" />5s 轮询刷新中</span>
          <span className="muted" style={{ font: '400 11.5px var(--font-mono)' }}>游标分页 · 共 {rows.length} 条</span>
        </div>
      </div>

      <CreateExperimentModal open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}
