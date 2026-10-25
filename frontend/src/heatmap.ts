import type {
  PiecewiseVisualMapComponentOption,
  TooltipComponentOption,
} from 'echarts'
import type { Grid } from './api'

// Fixed, non-uniform probability bands; colors sampled from Viridis in order.
// The values stay on their original 0–1 scale, including at band boundaries.
export function probabilityVisualMap(): PiecewiseVisualMapComponentOption {
  return {
    type: 'piecewise',
    dimension: 2,
    orient: 'horizontal',
    left: 'center',
    bottom: 8,
    selectedMode: false,
    hoverLink: false,
    itemWidth: 18,
    itemHeight: 12,
    itemGap: 12,
    textStyle: { color: '#172e38', fontSize: 11 },
    pieces: [
      { gte: 0, lt: 0.01, label: '0–<1%', color: '#440154' },
      { gte: 0.01, lt: 0.05, label: '1–<5%', color: '#46327e' },
      { gte: 0.05, lt: 0.1, label: '5–<10%', color: '#365c8d' },
      { gte: 0.1, lt: 0.25, label: '10–<25%', color: '#277f8e' },
      { gte: 0.25, lt: 0.5, label: '25–<50%', color: '#1fa187' },
      { gte: 0.5, lt: 0.75, label: '50–<75%', color: '#4ac16d' },
      { gte: 0.75, lt: 0.9, label: '75–<90%', color: '#a0da39' },
      { gte: 0.9, lte: 1, label: '90–100%', color: '#fde725' },
    ],
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
      { value: 0, label: '0 · 未触达', color: '#dce3eb' },
      { value: 1, label: '1 · 已触达', color: '#176858' },
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
