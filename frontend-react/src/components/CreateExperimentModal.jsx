import { useState } from 'react'
import { Modal, Button } from './ui'

const INITIAL = {
  ip: '10.99.80.160',
  prompt: '重点探索 UDP 洪水对 RTT 的影响',
  pps: '1000', duration: '10', size: '512', flow: '20',
  scapy: true, pktgen: true, trex: true,
}

export default function CreateExperimentModal({ open, onClose }) {
  const [form, setForm] = useState(INITIAL)
  const set = k => e => setForm({ ...form, [k]: e.target.value })
  const toggle = k => e => setForm({ ...form, [k]: e.target.checked })

  const submit = () => {
    onClose()
    alert('设计稿：提交后跳转到详情页')
  }

  return (
    <Modal open={open} onClose={onClose} title="新建实验"
      footer={<><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="primary" onClick={submit}>开始测试 →</Button></>}>
      <div className="field">
        <label>① 攻击 IP <span className="req">*</span></label>
        <select className="input" value={form.ip} onChange={set('ip')}>
          <option>10.99.80.160（allowlist）</option>
          <option>10.99.80.161（allowlist）</option>
          <option>10.99.80.162（allowlist）</option>
        </select>
        <div className="hint">从 allowlist.json 读取，后端强校验</div>
      </div>

      <div className="field">
        <label>② 用户提示词 <span className="req">*</span></label>
        <textarea className="input" rows="3" placeholder="例如：重点探索 UDP 洪水对 RTT 的影响" value={form.prompt} onChange={set('prompt')} />
        <div className="hint">注入 user message 与 system prompt</div>
      </div>

      <div className="field">
        <label>③ 攻击工具上限</label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div><label>每秒发包数 <span className="lim">上限 20000</span></label><input className="input" value={form.pps} onChange={set('pps')} /></div>
          <div><label>持续时间 <span className="lim">上限 20 秒</span></label><input className="input" value={form.duration} onChange={set('duration')} /></div>
          <div><label>包大小 <span className="lim">上限 1024 字节</span></label><input className="input" value={form.size} onChange={set('size')} /></div>
          <div><label>流数量 <span className="lim">上限 100</span></label><input className="input" value={form.flow} onChange={set('flow')} /></div>
        </div>
        <div className="hint">超出上限的值会被后端钳制（clamp）</div>
      </div>

      <div className="field">
        <label>④ 工具开关</label>
        <div style={{ display: 'flex', gap: 18, fontSize: 13, color: 'var(--text)' }}>
          <label><input type="checkbox" checked={form.scapy} onChange={toggle('scapy')} style={{ accentColor: 'var(--lime)', marginRight: 5 }} />Scapy <span className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>8</span></label>
          <label><input type="checkbox" checked={form.pktgen} onChange={toggle('pktgen')} style={{ accentColor: 'var(--lime)', marginRight: 5 }} />Pktgen <span className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>9</span></label>
          <label><input type="checkbox" checked={form.trex} onChange={toggle('trex')} style={{ accentColor: 'var(--lime)', marginRight: 5 }} />TRex <span className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>2</span></label>
        </div>
        <div className="hint">未勾选的工具不注册进 agent 图</div>
      </div>

      <div className="field">
        <label>⑤ 业务 PCAP 上传 <span className="lim">上限 50 MB · 可选</span></label>
        <div className="input" style={{ borderStyle: 'dashed', textAlign: 'center', color: 'var(--faint)', cursor: 'pointer' }}>点击或拖拽上传 .pcap / .pcapng</div>
      </div>
    </Modal>
  )
}
