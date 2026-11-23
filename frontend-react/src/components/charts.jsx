import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'

const MONO = 'JetBrains Mono'
const C = {
  line: '#1F2833', muted: '#8B98A8', faint: '#5A6675', text: '#E6EDF3',
  lime: '#C6FF3D', amber: '#FFB547', cyan: '#3AC6E0', panel: '#161D26', strong: '#2A3542',
}

function base() {
  return {
    grid: { left: 50, right: 20, top: 38, bottom: 26 },
    tooltip: { trigger: 'axis', backgroundColor: C.panel, borderColor: C.strong, textStyle: { color: C.text, fontFamily: MONO, fontSize: 11 } },
    xAxis: { type: 'time', axisLine: { lineStyle: { color: C.line } }, axisLabel: { color: C.faint, fontSize: 10, fontFamily: MONO }, splitLine: { show: false } },
  }
}

// 详情页：RTT + 成功率双轴曲线，攻击窗口 markArea 高亮
export function RttChart({ height = 340 }) {
  const ref = useRef(null)
  useEffect(() => {
    const chart = echarts.init(ref.current)
    const N = 60, t0 = Date.now() - (N - 1) * 1000
    const attacks = [[8, 20], [34, 46], [52, 58]]
    const inAtk = i => attacks.some(([a, b]) => i >= a && i <= b)
    const rtt = [], succ = []
    for (let i = 0; i < N; i++) {
      const ts = t0 + i * 1000
      rtt.push([ts, +(inAtk(i) ? 80 + Math.random() * 240 : 4 + Math.random() * 5).toFixed(1)])
      succ.push([ts, +(inAtk(i) ? Math.max(0, 60 - Math.random() * 55) : 100 - Math.random() * 2).toFixed(1)])
    }
    chart.setOption({
      ...base(),
      backgroundColor: 'transparent',
      animationDuration: 1200, animationEasing: 'cubicOut',
      legend: { data: ['RTT (ms)', '成功率 (%)'], textStyle: { color: C.muted, fontFamily: 'Inter', fontSize: 12 }, top: 6, icon: 'roundRect', itemWidth: 14, itemHeight: 3 },
      yAxis: [
        { type: 'value', name: 'RTT (ms)', nameTextStyle: { color: C.muted, fontFamily: MONO }, axisLabel: { color: C.faint, fontFamily: MONO, fontSize: 11 }, splitLine: { lineStyle: { color: C.line } } },
        { type: 'value', name: '成功率 (%)', min: 0, max: 100, nameTextStyle: { color: C.muted, fontFamily: MONO }, axisLabel: { color: C.faint, fontFamily: MONO, fontSize: 11 }, splitLine: { show: false } },
      ],
      series: [
        { name: 'RTT (ms)', type: 'line', showSymbol: false, smooth: true, data: rtt, lineStyle: { width: 2.5, color: C.lime }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(198,255,61,0.22)' }, { offset: 1, color: 'rgba(198,255,61,0)' }] } }, markArea: { silent: true, itemStyle: { color: 'rgba(255,181,71,0.10)', borderColor: 'rgba(255,181,71,0.28)', borderWidth: 1 }, data: attacks.map(([a, b]) => [{ name: '攻击窗口', xAxis: t0 + a * 1000 }, { xAxis: t0 + b * 1000 }]) } },
        { name: '成功率 (%)', type: 'line', yAxisIndex: 1, showSymbol: false, smooth: true, data: succ, lineStyle: { width: 2.5, color: C.amber } },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); chart.dispose() }
  }, [])
  return <div ref={ref} style={{ width: '100%', height }} />
}

// 滚动时间窗（每 step ms 推进一个点），用于实时观测
function useRollingSeries(genFns, n = 48, step = 2000) {
  const [series, setSeries] = useState(() => {
    const t0 = Date.now() - (n - 1) * step
    return genFns.map(g => Array.from({ length: n }, (_, i) => [t0 + i * step, g()]))
  })
  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now()
      setSeries(prev => prev.map((data, i) => {
        const next = data.slice(1)
        next.push([now, genFns[i]()])
        return next
      }))
    }, step)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return series
}

// 实时观测通用折线图：seriesCfg = [{ name, color, area, gen }]
export function LiveChart({ series: seriesCfg, yName, yMax, height = 250 }) {
  const genFns = seriesCfg.map(s => s.gen)
  const series = useRollingSeries(genFns)
  const ref = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    chartRef.current = echarts.init(ref.current)
    return () => { chartRef.current && chartRef.current.dispose() }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.setOption({
      ...base(),
      backgroundColor: 'transparent',
      animation: false,
      legend: { data: seriesCfg.map(s => s.name), textStyle: { color: C.muted, fontFamily: 'Inter', fontSize: 11 }, top: 2, icon: 'roundRect', itemWidth: 12, itemHeight: 3 },
      yAxis: { type: 'value', name: yName, min: 0, max: yMax, nameTextStyle: { color: C.muted, fontFamily: MONO }, axisLabel: { color: C.faint, fontFamily: MONO, fontSize: 10 }, splitLine: { lineStyle: { color: C.line } } },
      series: series.map((data, i) => ({
        name: seriesCfg[i].name, type: 'line', showSymbol: false, smooth: true, data,
        lineStyle: { width: 2, color: seriesCfg[i].color },
        areaStyle: seriesCfg[i].area ? { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: seriesCfg[i].color + '33' }, { offset: 1, color: seriesCfg[i].color + '00' }] } } : null,
      })),
    })
  }, [series, seriesCfg, yName, yMax])

  return <div ref={ref} style={{ width: '100%', height }} />
}
