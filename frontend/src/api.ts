export interface Health {
  status: 'ok'
  service: 'pripre-api'
  version: string
  stage: 'research'
}
export interface Grid {
  timestamp_us: number
  reference_price: string
  prices: { lower: string; upper: string }[]
  windows: { start_us: number; end_us: number }[]
}
export interface Snapshot {
  status: string
  timestamp_us: number
  reference_price?: string | null
  trade_timestamp_us?: number | null
  instrument?: string
  source?: string
  grid?: Grid
  probabilities: number[][] | null
  model?: string
  paths?: number
  calculation_ms?: number
  clients?: number
  gaps?: number
}
export interface Reliability {
  count: number
  predicted: number | null
  observed: number | null
}
export interface Metrics {
  count: number
  unknown: number
  brier: number | null
  frequency?: number
  reliability: Reliability[]
}
export interface ModelReport {
  summary: Metrics
  daily: { date: string; brier: number; origins: number }[]
  by_regime: (Metrics & { regime: string })[]
  by_distance: (Metrics & { distance_steps: number })[]
  by_window: (Metrics & { start_seconds: number })[]
  day_block_brier_95: [number, number] | null
}
export interface ResearchReport {
  config: { instrument: { base: string; quote: string } }
  generated_at: string
  model: string
  models: Record<string, ModelReport>
  folds: {
    train_start: string
    train_end: string
    calibration_start: string
    calibration_end: string
    test_start: string
    test_end: string
  }[]
  data: {
    minute_rows: number
    minute_gap_count: number
    minute_start_us: number | null
    minute_end_us: number | null
    sample_dates: string[]
    trade_rows: number
    local_bytes: number
  }
  market_context: {
    date: string
    close: number
    high: number
    low: number
    volatility: number
    minutes: number
  }[]
  latency_ms: { p50: number; p95: number; max: number }
  out_of_distribution_origins: number
  limitations: string[]
}
export interface Settings {
  instrument: { base: string; quote: string }
  source: { provider: string }
  grid: {
    price_step: string
    half_width: number
    first_window_seconds: number
    window_seconds: number
    horizon_seconds: number
  }
  runtime: { live_enabled: boolean; paths: number; max_clients: number }
}

export async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(path, { signal: AbortSignal.timeout(10000) })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json() as Promise<T>
}

export async function fetchHealth(): Promise<Health> {
  const data: unknown = await getJSON('/api/health')
  if (
    typeof data !== 'object' ||
    data === null ||
    !('status' in data) ||
    data.status !== 'ok' ||
    !('service' in data) ||
    data.service !== 'pripre-api' ||
    !('stage' in data) ||
    data.stage !== 'research' ||
    !('version' in data) ||
    typeof data.version !== 'string'
  )
    throw new Error('Invalid health response')
  return data as Health
}

export function parseSnapshot(value: unknown): Snapshot {
  if (
    typeof value !== 'object' ||
    value === null ||
    !('status' in value) ||
    typeof value.status !== 'string'
  ) {
    throw new Error('Invalid matrix response')
  }
  const frame = value as Snapshot
  if (frame.status === 'ready') {
    if (
      !frame.grid ||
      !frame.probabilities ||
      !Number.isFinite(frame.timestamp_us) ||
      frame.probabilities.length !== frame.grid.prices.length ||
      frame.probabilities.some(
        (row) =>
          row.length !== frame.grid!.windows.length ||
          row.some((p) => !Number.isFinite(p) || p < 0 || p > 1),
      )
    ) {
      throw new Error('Invalid probability matrix')
    }
  } else {
    frame.probabilities = null
  }
  return frame
}
