import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button, Icon, StatusBadge } from '../components/ui'
import { RttChart, HttpChart, TrafficChart } from '../components/charts'
import HitlModal from '../components/HitlModal'

const ATTACKS = [
  { tool: 'Pktgen UDP 泛洪', eng: 'pktgen_udp_flood', hitl: 'ok', params: [['rate', '80%'], ['dur', '10s'], ['窗口成功率', '12%', true], ['est', '1.2 Gbps']] },
  { tool: 'TCP SYN 洪水', eng: 'pktgen_tcp_flood', hitl: 'ok', warn: true, params: [['rate', '60%'], ['dur', '8s'], ['窗口成功率', '41%', true], ['flags', 'SYN']] },
  { tool: 'ICMP 泛洪', eng: 'pktgen_icmp_flood', hitl: 'pending', params: [['rate', '90%'], ['dur', '10s'], ['窗口成功率', '—']] },
]

const REASONING = [
  { kind: 'reasoning', text: '观察到第一次 UDP 泛洪后成功率骤降至 12%，说明目标在 pps 较高时已出现拥塞，应进一步…', full: '观察到第一次 UDP 泛洪后成功率骤降至 12%，说明目标在 pps 较高时已出现拥塞。进一步对比 60%/80%/90% 三档 rate 发现 RTT 与 rate 近似线性上升，判定为带宽耗尽型拥塞。下一步尝试叠加 TCP SYN 洪水，观察是否触发目标协议栈异常与丢包率进一步上升。' },
  { kind: 'ai_message', text: '当前 RTT 已升至 142ms、成功率 12%，拥塞明显。尝试提高 Pktgen UDP 泛洪的 rate 到 90%，观察是否继续恶化。' },
  { kind: 'tool_call', call: 'pktgen_udp_flood({ rate: 90, duration_ms: 10000, dst_ip: "10.99.80.160" })' },
  { kind: 'hitl_request', text: '等待人工审批：将实发 Pktgen UDP 泛洪（rate 90% · 10s）到 10.99.80.160' },
  { kind: 'hitl_response', ok: true, text: '✓ 已批准（操作员 22:44:31）' },
  { kind: 'tool_result', dim: true, text: 'avg_rtt_ms=189.4 · loss_pct=74% · covers_attack_window=true · 已发送 45,000,000 包' },
]

const NODE = { reasoning: 'reasoning', ai_message: 'ai', tool_call: 'tool', tool_result: 'tool', hitl_request: 'hitl', hitl_response: 'hitl' }

function ReasoningItem({ ev }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="ev">
      <div className="rail">
        <div className={`node ${NODE[ev.kind]}`} />
        <div className="bar" />
      </div>
      <div className="body">
        <div className="kind">{ev.kind}</div>
        {ev.call
          ? <div className="call"><span className="k">{ev.call.split('(')[0]}</span>({ev.call.slice(ev.call.indexOf('(') + 1)}</div>
          : <div className={`text${ev.dim ? ' dim' : ''}`} style={ev.ok ? { color: 'var(--lime)' } : undefined}>
              {open ? ev.full : ev.text}
            </div>}
        {ev.full && <span className="collapse" onClick={() => setOpen(!open)}>{open ? '收起' : '展开全文'}</span>}
      </div>
    </div>
  )
}

function ChartPanel({ title, children }) {
  return (
    <div className="panel chart-wrap">
      <div className="chart-glow" />
      <div className="panel-head" style={{ position: 'relative' }}>
        <h2>{title}</h2>
        <div className="range-chips">
          <span className="chip">30s</span><span className="chip active">1m</span><span className="chip">5m</span><span className="chip">全部</span>
        </div>
      </div>
      <div className="panel-body">{children}</div>
    </div>
  )
}

export default function ExperimentDetail() {
  const { id } = useParams()
  const [hitl, setHitl] = useState(false)

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            实验 <span className="id">#{id}</span> <StatusBadge status="running" />
          </h1>
          <div className="desc">目标 <span className="mono" style={{ color: 'var(--text)' }}>10.99.80.160</span> · 创建 11-20 22:41:07 · 已运行 3m 12s</div>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <Link to="/" className="btn ghost"><Icon name="back" size={15} />返回列表</Link>
          <Link to={`/experiments/${id}/summary`} className="btn ghost"><Icon name="health" size={15} />实验总结</Link>
          <Button variant="danger" icon="stop" onClick={() => alert('设计稿：停止实验')}>停止</Button>
        </div>
      </div>

      <div className="detail-layout">
        <div className="charts-col">
          <ChartPanel title="攻击流量 · 清洗前 / 清洗后">
            <TrafficChart height={150} />
          </ChartPanel>
          <ChartPanel title="RTT 拨测 · RTT / 丢包率">
            <RttChart height={150} />
          </ChartPanel>
          <ChartPanel title="HTTP 拨测 · 成功率 / TTFB">
            <HttpChart height={150} />
          </ChartPanel>
        </div>

        <div className="side-col">
          <div className="panel">
            <div className="panel-head"><h2>攻击时间线</h2><span className="meta">3 次</span></div>
            <div className="panel-body">
              <div className="attacks">
                {ATTACKS.map((a, i) => (
                  <div key={i} className={`atk-card${a.warn ? ' warn' : ''}`}>
                    <div className="atk-top">
                      <span className="atk-type">{a.tool} <span className="eng">{a.eng}</span></span>
                      <span className={`hitl-tag ${a.hitl === 'ok' ? 'ok' : 'wait'}`}>{a.hitl === 'ok' ? '✓ 已批准' : '⏳ 待审批'}</span>
                    </div>
                    <div className="atk-meta">
                      {a.params.map(([k, v, down], j) => <span key={j}>{k} <b className={down ? 'down' : ''}>{v}</b></span>)}
                    </div>
                    {a.warn && <div className="hint" style={{ marginTop: 7, color: 'var(--amber)' }}>⚠ covers_attack_window = false</div>}
                    {a.hitl === 'pending' && <div style={{ marginTop: 9 }}><Button variant="primary" size="sm" onClick={() => setHitl(true)}>审批</Button></div>}
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>智能体推理流</h2><span className="meta">按 seq 时序 · 思考链折叠</span></div>
            <div className="panel-body">
              <div className="stream">
                {REASONING.map((ev, i) => <ReasoningItem key={i} ev={ev} />)}
              </div>
            </div>
          </div>
        </div>
      </div>

      <HitlModal open={hitl} onClose={() => setHitl(false)} />
    </div>
  )
}
