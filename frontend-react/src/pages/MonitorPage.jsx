import { Icon } from '../components/ui'
import { LiveChart } from '../components/charts'

const IP_SERIES = [
  { name: 'RTT (ms)', color: '#C6FF3D', area: true, gen: () => +(4 + Math.random() * 4).toFixed(1) },
]
const SW_SERIES = [
  { name: '入流量', color: '#C6FF3D', area: true, gen: () => +(800 + Math.random() * 600).toFixed(0) },
  { name: '出流量', color: '#FFB547', gen: () => +(500 + Math.random() * 450).toFixed(0) },
]
const HL_SERIES = [
  { name: '核心业务', color: '#C6FF3D', gen: () => +(95 + Math.random() * 5).toFixed(1) },
  { name: '数据库', color: '#3AC6E0', gen: () => +(86 + Math.random() * 12).toFixed(1) },
  { name: '消息队列', color: '#FFB547', gen: () => +(70 + Math.random() * 28).toFixed(1) },
]

export default function MonitorPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>实时观测</h1>
          <div className="desc">目标可达性 · 交换机流量 · 业务健康 · 每 2s 刷新</div>
        </div>
        <span className="badge running" style={{ fontSize: 12.5 }}><span className="dot" />LIVE</span>
      </div>

      <div className="stat-strip">
        <div className="panel stat-pill ok">
          <div className="ic"><Icon name="activity" size={18} /></div>
          <div><div className="t">目标 IP 可达性 · 10.99.80.160</div><div className="v">可达 · 4.2 ms</div></div>
        </div>
        <div className="panel stat-pill ok">
          <div className="ic"><Icon name="switch" size={18} /></div>
          <div><div className="t">三层交换机 · sw-core-01</div><div className="v">入 1.2 G · 出 0.8 G</div></div>
        </div>
        <div className="panel stat-pill warn">
          <div className="ic"><Icon name="health" size={18} /></div>
          <div><div className="t">业务系统健康</div><div className="v">2/3 健康 · 1 降级</div></div>
        </div>
      </div>

      <div className="mon-grid">
        <div className="panel chart-wrap">
          <div className="chart-glow" />
          <div className="panel-head" style={{ position: 'relative' }}><h2>目标 IP 可达性</h2><span className="cur-read">当前 <span className="v">4.2 ms</span> · 可达</span></div>
          <div className="panel-body"><LiveChart series={IP_SERIES} yName="RTT (ms)" /></div>
        </div>
        <div className="panel chart-wrap">
          <div className="chart-glow" />
          <div className="panel-head" style={{ position: 'relative' }}><h2>三层交换机流量</h2><span className="cur-read">入 <span className="v">1.2 G</span> · 出 <span className="v">0.8 G</span></span></div>
          <div className="panel-body"><LiveChart series={SW_SERIES} yName="Mbps" /></div>
        </div>
      </div>

      <div className="panel chart-wrap">
        <div className="chart-glow" />
        <div className="panel-head" style={{ position: 'relative' }}>
          <h2>业务系统健康度</h2>
          <span className="cur-read">核心业务 <span className="v" style={{ color: 'var(--lime)' }}>98</span> · 数据库 <span className="v" style={{ color: 'var(--cyan)' }}>91</span> · 消息队列 <span className="v" style={{ color: 'var(--amber)' }}>76</span></span>
        </div>
        <div className="panel-body"><LiveChart series={HL_SERIES} yName="健康度" yMax={100} height={270} /></div>
      </div>
    </div>
  )
}
