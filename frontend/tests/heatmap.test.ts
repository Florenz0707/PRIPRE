// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { init, use } from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, VisualMapComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { heatmapTooltip, probabilityVisualMap } from '../src/heatmap'

use([HeatmapChart, GridComponent, VisualMapComponent, SVGRenderer])

function colors(values: number[]) {
  const chart = init(null, undefined, {
    renderer: 'svg',
    ssr: true,
    width: 1000,
    height: 650,
  })
  try {
    chart.setOption({
      animation: false,
      xAxis: { type: 'category', data: values.map((_, i) => String(i)) },
      yAxis: { type: 'category', data: ['price'] },
      visualMap: probabilityVisualMap(),
      series: [{ type: 'heatmap', data: values.map((p, x) => [x, 0, p]) }],
    })
    return values.map((_, dataIndex) =>
      chart.getVisual({ seriesIndex: 0, dataIndex }, 'color'),
    )
  } finally {
    chart.dispose()
  }
}

describe('fixed probability color encoding', () => {
  it('covers every boundary including zero and one, with eight ordered bands', () => {
    const edges = [0, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 1]
    const lower = colors(edges.slice(0, -1))
    const upper = colors(edges.slice(1).map((p) => p - 1e-8))
    expect(lower).toEqual(upper)
    expect(new Set(lower).size).toBe(8)
    expect(colors([1])[0]).toBe(lower.at(-1))
  })

  it('keeps the same absolute probability color when the frame range changes', () => {
    expect(colors([0.002, 0.04, 0.06, 0.98]).slice(0, 3)).toEqual(
      colors([0.002, 0.04, 0.06]),
    )
    expect(new Set(colors([0.002, 0.04, 0.06])).size).toBe(3)
    expect(probabilityVisualMap().selectedMode).toBe(false)
  })

  it('shows probability percentages and the complete half-open price and time ranges', () => {
    const tooltip = heatmapTooltip({
      timestamp_us: 1e6,
      reference_price: '100',
      prices: [{ lower: '50', upper: '150' }],
      windows: [{ start_us: 6e6, end_us: 11e6 }],
    })
    if (typeof tooltip.formatter !== 'function')
      throw new Error('missing tooltip')
    const params = {
      componentType: 'series',
      componentSubType: 'heatmap',
      componentIndex: 0,
      name: '',
      dataIndex: 0,
      data: [0, 0, 0.002014306698558258],
      value: [0, 0, 0.002014306698558258],
      $vars: [],
    }
    const content = tooltip.formatter(params, '', () => {})
    expect(content).toContain('价格 [50, 150)')
    expect(content).toContain('未来窗口 [+5s, +10s)')
    expect(content).toContain('触达概率：0.20%')
    expect(tooltip.renderMode).toBe('richText')
  })
})
