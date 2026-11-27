import { Link, useParams } from 'react-router-dom'
import { Icon, AnimatedNumber } from '../components/ui'

const SUMMARY_KPIS = [
  { cls: 'c-rtt', label: '最终 RTT', value: 189.4, unit: 'ms', trend: <>峰值 <b>189.4</b> · 基线 <b>4.8</b></> },
  { cls: 'c-loss', label: '最终丢包率', value: 74, unit: '%', trend: <>攻击窗口内</> },
  { cls: 'c-succ', label: '拨测成功率', value: 12, unit: '%', trend: <>攻击窗口内</> },
  { cls: 'c-http', label: 'HTTP 成功率', value: 28, unit: '%', trend: <>TTFB <b>1200ms</b></> },
  { cls: 'c-atk', label: '攻击次数', value: 3, trend: <>3 轮 · 全部已批准</> },
]

const BASIC_INFO = [
  ['目标 IP', '10.99.80.160'],
  ['用户提示词', '重点探索 UDP 洪水对 RTT 的影响'],
  ['攻击参数上限', 'pps 2000 · duration 10s · packet_size 256 · flow_count 4'],
  ['工具开关', 'Scapy 全开 · Pktgen 全开 · TRex 开'],
  ['业务 PCAP', '无'],
  ['迭代预算', 'max_iters 20 · no_improve_limit 5'],
  ['运行模式', 'dry_run（Pktgen / TRex 编译校验，未实发）'],
]

const ATTACK_PROCESS = [
  { round: '第 1 轮', tool: 'Pktgen UDP 泛洪', detail: 'rate 80% · 10s。RTT 从 4.8ms 升至 189.4ms，丢包 74%，判定为带宽耗尽型拥塞，是本次最有效的一轮。' },
  { round: '第 2 轮', tool: 'TCP SYN 洪水', detail: 'rate 60% · 8s。拨测成功率降至 41%，对面向连接的 HTTP 业务造成明显半连接压力。' },
  { round: '第 3 轮', tool: 'ICMP 泛洪', detail: 'rate 90% · 10s。效果有限——目标对 ICMP 有防护，RTT 仅小幅波动，不作为主攻手段。' },
]

const LESSONS = [
  { title: '最有效手段：UDP 泛洪', text: '对目标 10.99.80.160（业务服务器），Pktgen UDP 泛洪效果最显著——rate≥80% 时 RTT 飙升近 40 倍、丢包 74%，属带宽耗尽型拥塞，是首选攻击手段。' },
  { title: '次选：TCP SYN 洪水', text: 'TCP SYN 洪水能明显拉低拨测成功率（41%），适合攻击面向连接的 HTTP 业务；但目标有半连接防护，效果略逊于 UDP。' },
  { title: 'ICMP 泛洪效果有限', text: '目标对 ICMP 有防护，ICMP 泛洪仅小幅波动 RTT，不建议作为主攻手段。' },
  { title: '下次实验建议', text: '优先 UDP 泛洪 rate≥80%、持续≥10s，并开启 HTTP 拨测观察业务成功率与 TTFB 退化；可叠加 TCP SYN 洪水进一步压制业务。' },
]

export default function ExperimentSummary() {
  const { id } = useParams()
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            实验总结 <span className="id">#{id}</span>
          </h1>
          <div className="desc">目标 <span className="mono" style={{ color: 'var(--text)' }}>10.99.80.160</span> · 已完成 · 11-20 22:52:30</div>
        </div>
        <Link to={`/experiments/${id}`} className="btn ghost"><Icon name="back" size={15} />返回详情</Link>
      </div>

      <div className="kpis">
        {SUMMARY_KPIS.map(k => (
          <div key={k.label} className={`kpi panel ${k.cls || ''}`}>
            <div className="label">{k.label}</div>
            <div className="value"><AnimatedNumber value={k.value} />{k.unit && <small>{k.unit}</small>}</div>
            <div className="trend">{k.trend}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-head"><h2>实验基本信息</h2></div>
        <div className="panel-body">
          <dl className="kv">
            {BASIC_INFO.flatMap(([k, v]) => [
              <dt key={k}>{k}</dt>,
              <dd key={`${k}-v`}>{v}</dd>,
            ])}
          </dl>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>攻击过程说明</h2></div>
        <div className="panel-body">
          <div className="proc-list">
            {ATTACK_PROCESS.map((a, i) => (
              <div key={i} className="proc">
                <div className="proc-round">{a.round}</div>
                <div className="proc-body">
                  <div className="proc-tool">{a.tool}</div>
                  <div className="proc-detail">{a.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>经验教训总结</h2></div>
        <div className="panel-body">
          <div className="lesson-list">
            {LESSONS.map((l, i) => (
              <div key={i} className="lesson">
                <div className="lesson-title">{l.title}</div>
                <div className="lesson-text">{l.text}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
