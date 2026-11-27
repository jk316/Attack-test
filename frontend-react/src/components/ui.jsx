import { useEffect, useState } from 'react'
import { STATUS_META } from '../lib/mock'

// Lucide 风格线性图标（1.75 stroke，16–18px）
const ICONS = {
  list: <><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" /></>,
  plus: <><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></>,
  activity: <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  trash: <><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></>,
  back: <polyline points="15 18 9 12 15 6" />,
  warn: <><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></>,
  x: <><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></>,
  switch: <><rect x="2" y="2" width="20" height="20" rx="5" /><path d="M7 9v6M12 6v12M17 9v6" /></>,
  health: <><circle cx="12" cy="12" r="10" /><path d="M8 12h8" /></>,
  panel: <><rect x="3" y="3" width="18" height="18" rx="2" /><line x1="9" y1="3" x2="9" y2="21" /></>,
}

export function Icon({ name, size = 17 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      {ICONS[name]}
    </svg>
  )
}

export function Button({ variant, size, icon, children, onClick, title, type = 'button' }) {
  const cls = ['btn', variant && variant !== 'default' ? variant : '', size === 'sm' ? 'btn-sm' : ''].filter(Boolean).join(' ')
  return (
    <button type={type} className={cls} onClick={onClick} title={title}>
      {icon && <Icon name={icon} size={15} />}{children}
    </button>
  )
}

export function IconButton({ icon, title, danger, onClick }) {
  return (
    <button className={`icon-btn${danger ? ' del' : ''}`} title={title} onClick={onClick}>
      <Icon name={icon} size={16} />
    </button>
  )
}

export function StatusBadge({ status }) {
  const { label, cls } = STATUS_META[status] || STATUS_META.stopped
  return <span className={`badge ${cls}`}><span className="dot" />{label}</span>
}

export function Modal({ open, onClose, title, children, footer }) {
  if (!open) return null
  return (
    <div className="overlay show" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head"><h3>{title}</h3><button className="icon-btn" onClick={onClose}><Icon name="x" size={18} /></button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

// KPI 数字 count-up（900ms easeOutCubic）
export function AnimatedNumber({ value, decimals }) {
  const [display, setDisplay] = useState('0')
  useEffect(() => {
    const target = parseFloat(value)
    const dec = decimals !== undefined ? decimals : (String(value).split('.')[1] || '').length
    const t0 = performance.now(), dur = 900
    let raf
    const step = now => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3)
      const v = (target * e).toFixed(dec)
      setDisplay(p < 1 ? v : String(target))
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [value, decimals])
  return <span>{display}</span>
}
