// 数据访问层。USE_MOCK = true 时走本地模拟数据（可离线开发）；后端 Plan 1 就绪后置 false，
// 即对接 docs/front-end.md §8 冻结的 REST/WS 契约。
import { EXPERIMENTS } from './mock'

export const USE_MOCK = true

const delay = (ms = 120) => new Promise(r => setTimeout(r, ms))

// GET /api/experiments?status=&cursor=&limit=
export async function listExperiments({ status = 'all' } = {}) {
  if (USE_MOCK) {
    await delay()
    return status === 'all' ? [...EXPERIMENTS] : EXPERIMENTS.filter(r => r.status === status)
  }
  const q = status && status !== 'all' ? `?status=${encodeURIComponent(status)}` : ''
  const res = await fetch(`/api/experiments${q}`)
  if (!res.ok) throw new Error(`GET /api/experiments ${res.status}`)
  return res.json()
}

// GET /api/experiments/{id}
export async function getExperiment(id) {
  if (USE_MOCK) {
    await delay()
    return EXPERIMENTS.find(r => r.id === id) || null
  }
  const res = await fetch(`/api/experiments/${id}`)
  if (!res.ok) throw new Error(`GET /api/experiments/${id} ${res.status}`)
  return res.json()
}

// POST /api/experiments —— 创建实验（5 项配置）
export async function createExperiment(payload) {
  if (USE_MOCK) { await delay(); return { run_id: 'exp-new', status: 'queued' } }
  const res = await fetch('/api/experiments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`POST /api/experiments ${res.status}`)
  return res.json()
}

// POST /api/experiments/{id}/stop
export async function stopExperiment(id) {
  if (USE_MOCK) { await delay(); return { ok: true } }
  const res = await fetch(`/api/experiments/${id}/stop`, { method: 'POST' })
  if (!res.ok) throw new Error(`POST stop ${res.status}`)
  return res.json()
}

// DELETE /api/experiments/{id} —— 软删除
export async function deleteExperiment(id) {
  if (USE_MOCK) { await delay(); return { ok: true } }
  const res = await fetch(`/api/experiments/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`DELETE ${res.status}`)
  return res.json()
}

// GET /api/meta/options —— 表单元数据（allowlist hosts、工具清单、硬上限）
export async function getMetaOptions() {
  if (USE_MOCK) {
    await delay()
    return {
      allowlist: ['10.99.80.160', '10.99.80.161', '10.99.80.162'],
      tools: { scapy: 8, pktgen: 9, trex: 2 },
      hardLimits: { pps: 20000, duration_s: 20, packet_size: 1024, flow_count: 100 },
    }
  }
  const res = await fetch('/api/meta/options')
  return res.json()
}

// WebSocket /ws/{run_id} —— 下行事件流（seq 有序）。后端就绪后实现断线重连 + after_seq 补齐。
export function connectExperimentSocket(runId, handlers = {}) {
  if (USE_MOCK) {
    // 模拟：不建立连接，仅返回一个 no-op 控制器，便于上层统一调用。
    return { close() {} }
  }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws/${runId}`)
  ws.onmessage = ev => {
    const msg = JSON.parse(ev.data)
    handlers[msg.type]?.(msg)
  }
  return { close: () => ws.close() }
}
