import type {
  PiecewiseVisualMapComponentOption,
  ContinuousVisualMapComponentOption,
  TooltipComponentOption,
} from 'echarts'
import type { Grid } from './api'

// A fixed square-root color scale gives low probabilities more visual resolution.
// Keep the original probability in dimension 2 for tooltips and auditability.
const reds = [
  '#fff5f0',
  '#fee0d2',
  '#fcbba1',
  '#fc9272',
  '#fb6a4a',
  '#ef3b2c',
  '#cb181d',
  '#a50f15',
  '#67000d',
]
export const probabilityGradient = `linear-gradient(to right, ${reds.join(', ')})`
export const probabilityTicks = [0, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 1].map(
  (p) => ({ label: `${p * 100}%`, position: `${Math.sqrt(p) * 100}%` }),
)

export function probabilityHeatmapData(matrix: number[][]): number[][] {
  return matrix.flatMap((row, y) => row.map((p, x) => [x, y, p, Math.sqrt(p)]))
}

export function probabilityVisualMap(): ContinuousVisualMapComponentOption {
  return {
    type: 'continuous',
    min: 0,
    max: 1,
    dimension: 3,
    show: false,
    calculable: false,
    inRange: { color: [...reds] },
  }
}

export function labelVisualMap(): PiecewiseVisualMapComponentOption {
  return {
    type: 'piecewise',
    dimension: 2,
    orient: 'horizontal',
    left: 'center',
    bottom: 8,
    selectedMode: false,
    hoverLink: false,
    textStyle: { color: '#172e38' },
    pieces: [
      { value: 0, label: '0 · 未触达', color: '#fee2e2' },
      { value: 1, label: '1 · 已触达', color: '#991b1b' },
    ],
  }
}

export function heatmapTooltip(
  grid: Grid,
  labels = false,
): TooltipComponentOption {
  return {
    trigger: 'item',
    renderMode: 'richText',
    confine: true,
    backgroundColor: '#172e38',
    borderWidth: 0,
    textStyle: { color: '#ffffff', fontSize: 13 },
    formatter(params) {
      const item = Array.isArray(params) ? params[0] : params
      if (!item || !Array.isArray(item.value)) return ''
      const [x, y, value] = item.value.map(Number)
      const price = grid.prices[y!]
      const window = grid.windows[x!]
      if (!price || !window || value === undefined) return ''
      const start = (window.start_us - grid.timestamp_us) / 1e6
      const end = (window.end_us - grid.timestamp_us) / 1e6
      const result = labels
        ? `实际标签：${value === 1 ? '1 · 已触达' : '0 · 未触达'}`
        : `触达概率：${(value * 100).toFixed(2)}%`
      return `价格 [${price.lower}, ${price.upper})\n未来窗口 [+${start}s, +${end}s)\n${result}`
    },
  }
}
