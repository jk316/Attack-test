// 模拟数据 —— 后端 Plan 1（SQLite + REST/WS 契约）就绪后，由 src/lib/api.js 切换到真实接口。
// 字段对齐 docs/front-end.md §2/§8。

export const EXPERIMENTS = [
  { id: 'exp-9f3a', targetIp: '10.99.80.160', status: 'running', createdAt: '11-20 22:41:07',
    summary: { rtt: null, succ: null, attacks: 3 } },
  { id: 'exp-8c12', targetIp: '10.99.80.160', status: 'queued', createdAt: '11-20 22:40:52', summary: null },
  { id: 'exp-7b04', targetIp: '10.99.80.161', status: 'completed', createdAt: '11-20 21:58:33',
    summary: { rtt: '142.6ms', succ: '34%', succDown: true, attacks: 12 } },
  { id: 'exp-6d88', targetIp: '10.99.80.160', status: 'completed', createdAt: '11-20 20:15:10',
    summary: { rtt: '18.3ms', succ: '96%', succUp: true, attacks: 5 } },
  { id: 'exp-5c31', targetIp: '10.99.80.162', status: 'error', createdAt: '11-20 19:44:02',
    summary: { stopReason: 'pktgen 连接超时' } },
  { id: 'exp-4a09', targetIp: '10.99.80.160', status: 'interrupted', createdAt: '11-20 18:30:47',
    summary: { rtt: '56.1ms', succ: '71%', attacks: 7 } },
]

// 状态徽章六态（对应 spec §5）：running/queued/completed/stopped/error/interrupted
export const STATUS_META = {
  running: { label: '运行中', cls: 'running' },
  queued: { label: '排队中', cls: 'queued' },
  completed: { label: '已完成', cls: 'completed' },
  stopped: { label: '已停止', cls: 'stopped' },
  error: { label: '失败', cls: 'error' },
  interrupted: { label: '中断', cls: 'interrupted' },
}

export const STATUS_FILTERS = [
  ['all', '全部'],
  ['running', '运行中'],
  ['queued', '排队中'],
  ['completed', '已完成'],
  ['error', '失败'],
  ['interrupted', '中断'],
]
