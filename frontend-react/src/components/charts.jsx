import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'

const MONO = 'JetBrains Mono'
const C = {
  line: '#1F2833', muted: '#8B98A8', faint: '#5A6675', text: '#E6EDF3',
  lime: '#C6FF3D', amber: '#FFB547', cyan: '#3AC6E0', red: '#FF5470', green: '#3ADF6E',
  panel: '#161D26', strong: '#2A3542',
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
    const rtt = [], loss = []
    for (let i = 0; i < N; i++) {
      const ts = t0 + i * 1000
      rtt.push([ts, +(inAtk(i) ? 80 + Math.random() * 240 : 4 + Math.random() * 5).toFixed(1)])
      loss.push([ts, +(inAtk(i) ? 40 + Math.random() * 55 : Math.random() * 2).toFixed(1)])
    }
    chart.setOption({
      ...base(),
      backgroundColor: 'transparent',
      animationDuration: 1200, animationEasing: 'cubicOut',
      legend: { data: ['RTT (ms)', '丢包率 (%)'], textStyle: { color: C.muted, fontFamily: 'Inter', fontSize: 12 }, top: 6, icon: 'roundRect', itemWidth: 14, itemHeight: 3 },
      yAxis: [
        { type: 'value', name: 'RTT (ms)', nameTextStyle: { color: C.muted, fontFamily: MONO }, axisLabel: { color: C.faint, fontFamily: MONO, fontSize: 11 }, splitLine: { lineStyle: { color: C.line } } },
        { type: 'value', name: '丢包率 (%)', min: 0, max: 100, nameTextStyle: { color: C.muted, fontFamily: MONO }, axisLabel: { color: C.faint, fontFamily: MONO, fontSize: 11 }, splitLine: { show: false } },
      ],
      series: [
        { name: 'RTT (ms)', type: 'line', showSymbol: false, smooth: true, data: rtt, color: C.green, lineStyle: { width: 2.5, color: C.green }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(58,223,110,0.22)' }, { offset: 1, color: 'rgba(58,223,110,0)' }] } }, markArea: { silent: true, itemStyle: { color: 'rgba(255,181,71,0.10)', borderColor: 'rgba(255,181,71,0.28)', borderWidth: 1 }, data: attacks.map(([a, b]) => [{ name: '攻击窗口', xAxis: t0 + a * 1000 }, { xAxis: t0 + b * 1000 }]) } },
        { name: '丢包率 (%)', type: 'line', yAxisIndex: 1, showSymbol: false, smooth: true, data: loss, color: C.amber, lineStyle: { width: 2.5, color: C.amber } },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); chart.dispose() }
  }, [])
  return <div ref={ref} style={{ width: '100%', height }} />
}

// 详情页：HTTP 拨测双轴曲线（成功率 + TTFB），攻击窗口 markArea 高亮
export function HttpChart({ height = 300 }) {
  const ref = useRef(null)
  useEffect(() => {
    const chart = echarts.init(ref.current)
    const N = 60, t0 = Date.now() - (N - 1) * 1000
    const attacks = [[8, 20], [34, 46], [52, 58]]
    const inAtk = i => attacks.some(([a, b]) => i >= a && i <= b)
    const httpSucc = [], ttfb = []
    for (let i = 0; i < N; i++) {
      const ts = t0 + i * 1000
      httpSucc.push([ts, +(inAtk(i) ? Math.max(0, 50 - Math.random() * 50) : 99 - Math.random() * 1).toFixed(1)])
      ttfb.push([ts, +(inAtk(i) ? 800 + Math.random() * 2600 : 28 + Math.random() * 18).toFixed(1)])
    }
    chart.setOption({
      ...base(),
      backgroundColor: 'transparent',
      animationDuration: 1200, animationEasing: 'cubicOut',
      legend: { data: ['HTTP 成功率 (%)', 'TTFB (ms)'], textStyle: { color: C.muted, fontFamily: 'Inter', fontSize: 12 }, top: 6, icon: 'roundRect', itemWidth: 14, itemHeight: 3 },
      yAxis: [
        { type: 'value', name: '成功率 (%)', min: 0, max: 100, nameTextStyle: { color: C.muted, fontFamily: MONO }, axisLabel: { color: C.faint, fontFamily: MONO, fontSize: 11 }, splitLine: { lineStyle: { color: C.line } } },
        { type: 'value', name: 'TTFB (ms)', nameTextStyle: { color: C.muted, fontFamily: MONO }, axisLabel: { color: C.faint, fontFamily: MONO, fontSize: 11 }, splitLine: { show: false } },
      ],
      series: [
        { name: 'HTTP 成功率 (%)', type: 'line', showSymbol: false, smooth: true, data: httpSucc, color: C.green, lineStyle: { width: 2.5, color: C.green }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(58,223,110,0.18)' }, { offset: 1, color: 'rgba(58,223,110,0)' }] } }, markArea: { silent: true, itemStyle: { color: 'rgba(255,181,71,0.10)', borderColor: 'rgba(255,181,71,0.28)', borderWidth: 1 }, data: attacks.map(([a, b]) => [{ name: '攻击窗口', xAxis: t0 + a * 1000 }, { xAxis: t0 + b * 1000 }]) } },
        { name: 'TTFB (ms)', type: 'line', yAxisIndex: 1, showSymbol: false, smooth: true, data: ttfb, color: C.amber, lineStyle: { width: 2.5, color: C.amber } },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); chart.dispose() }
  }, [])
  return <div ref={ref} style={{ width: '100%', height }} />
}

// 流量对比图（攻击清洗前 vs 清洗后），双 y 轴 Mbps，攻击窗口 markArea 高亮
export function TrafficChart({ height = 220 }) {
  const ref = useRef(null)
  useEffect(() => {
    const chart = echarts.init(ref.current)
    const N = 60, t0 = Date.now() - (N - 1) * 1000
    const attacks = [[8, 20], [34, 46], [52, 58]]
    const inAtk = i => attacks.some(([a, b]) => i >= a && i <= b)
    const pre = [], post = []
    for (let i = 0; i < N; i++) {
      const ts = t0 + i * 1000
      pre.push([ts, +(inAtk(i) ? 800 + Math.random() * 600 : 8 + Math.random() * 12).toFixed(1)])
      post.push([ts, +(inAtk(i) ? 15 + Math.random() * 35 : 8 + Math.random() * 12).toFixed(1)])
    }
    chart.setOption({
      ...base(),
      backgroundColor: 'transparent',
      animationDuration: 1200, animationEasing: 'cubicOut',
      legend: { data: ['清洗前流量', '清洗后流量'], textStyle: { color: C.muted, fontFamily: 'Inter', fontSize: 12 }, top: 6, icon: 'roundRect', itemWidth: 14, itemHeight: 3 },
      yAxis: [
        { type: 'value', name: '清洗前 (Mbps)', nameTextStyle: { color: C.muted, fontFamily: MONO }, axisLabel: { color: C.faint, fontFamily: MONO, fontSize: 11 }, splitLine: { lineStyle: { color: C.line } } },
        { type: 'value', name: '清洗后 (Mbps)', nameTextStyle: { color: C.muted, fontFamily: MONO }, axisLabel: { color: C.faint, fontFamily: MONO, fontSize: 11 }, splitLine: { show: false } },
      ],
      series: [
        { name: '清洗前流量', type: 'line', showSymbol: false, smooth: true, data: pre, color: C.green, lineStyle: { width: 2.5, color: C.green }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(58,223,110,0.20)' }, { offset: 1, color: 'rgba(58,223,110,0)' }] } }, markArea: { silent: true, itemStyle: { color: 'rgba(255,181,71,0.10)', borderColor: 'rgba(255,181,71,0.28)', borderWidth: 1 }, data: attacks.map(([a, b]) => [{ name: '攻击窗口', xAxis: t0 + a * 1000 }, { xAxis: t0 + b * 1000 }]) } },
        { name: '清洗后流量', type: 'line', yAxisIndex: 1, showSymbol: false, smooth: true, data: post, color: C.amber, lineStyle: { width: 2.5, color: C.amber } },
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
