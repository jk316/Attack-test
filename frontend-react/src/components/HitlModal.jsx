import { Modal, Button, Icon } from './ui'

export default function HitlModal({ open, onClose }) {
  return (
    <Modal open={open} onClose={onClose} title="HITL 审批 · 实发参数确认"
      footer={<><Button variant="danger" onClick={onClose}>✕ 拒绝</Button><Button variant="primary" onClick={() => { onClose(); alert('设计稿：已批准并落库审计') }}>✓ 批准执行</Button></>}>
      <div className="danger-note" style={{ marginBottom: 14 }}>
        <Icon name="warn" size={16} />
        以下流量将真实发送，请确认目标在授权范围内。
      </div>
      <div className="kv">
        <dt>工具</dt><dd>pktgen_icmp_flood</dd>
        <dt>目标 IP</dt><dd>10.99.80.160</dd>
        <dt>rate</dt><dd>90%</dd>
        <dt>duration</dt><dd>10 s</dd>
        <dt>est 吞吐</dt><dd>~1.6 Gbps</dd>
      </div>
      <div className="field">
        <label>脚本预览（TRex 示例）</label>
        <div className="code-block">{`def main():
    c = STLClient(server="10.99.80.222")
    c.connect(); c.reset()
    c.push_pcap(pkts=["icmp_flood"], ...)
    c.start(ports=[0,1], mult="90%", duration=10)`}</div>
      </div>
    </Modal>
  )
}
