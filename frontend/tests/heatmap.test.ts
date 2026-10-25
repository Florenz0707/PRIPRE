// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { init, use } from 'echarts/core'
import { color } from 'echarts'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, VisualMapComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import {
  heatmapTooltip,
  probabilityHeatmapData,
  probabilityVisualMap,
} from '../src/heatmap'

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
      series: [{ type: 'heatmap', data: probabilityHeatmapData([values]) }],
    })
    return values.map((_, dataIndex) => {
      const shade = chart.getVisual({ seriesIndex: 0, dataIndex }, 'color')
      if (typeof shade !== 'string') throw new Error('expected a solid color')
      return shade
    })
  } finally {
    chart.dispose()
  }
}

describe('fixed probability color encoding', () => {
  it('provides continuous red shades with increasing darkness instead of eight flat bands', () => {
    const shades = colors(Array.from({ length: 101 }, (_, i) => i / 100))
    expect(new Set(shades).size).toBe(101)
    const brightness = shades.map((shade) => {
      const rgb = color.parse(shade)
      if (!rgb) throw new Error('invalid rendered color')
      expect(rgb[0]).toBeGreaterThanOrEqual(rgb[1]!)
      expect(rgb[0]).toBeGreaterThanOrEqual(rgb[2]!)
      return rgb[0]! * 0.2126 + rgb[1]! * 0.7152 + rgb[2]! * 0.0722
    })
    for (let i = 1; i < brightness.length; i++)
      expect(brightness[i]).toBeLessThan(brightness[i - 1]!)
    expect(new Set(colors([0.002, 0.003, 0.004, 0.005])).size).toBe(4)
    expect(probabilityHeatmapData([[0.002014306698558258]])[0]![2]).toBe(
      0.002014306698558258,
    )
  })

  it('keeps the same absolute probability color when the frame range changes', () => {
    expect(colors([0.002, 0.04, 0.06, 0.98]).slice(0, 3)).toEqual(
      colors([0.002, 0.04, 0.06]),
    )
    expect(new Set(colors([0.002, 0.04, 0.06])).size).toBe(3)
    expect(probabilityVisualMap().calculable).toBe(false)
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
