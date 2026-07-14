import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'
import type { EChartsOption } from 'echarts'

interface ChartProps {
  option: EChartsOption
  className?: string
  ariaLabel: string
}

export function Chart({ option, className = '', ariaLabel }: ChartProps) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' })
    chart.setOption(option)
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(ref.current)
    return () => {
      resize.disconnect()
      chart.dispose()
    }
  }, [option])

  return <div ref={ref} className={`chart ${className}`} role="img" aria-label={ariaLabel} />
}
