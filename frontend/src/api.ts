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
  by_regime: (GroupMetrics & { regime: string })[]
  by_phase?: GroupMetrics[]
  by_event?: GroupMetrics[]
  by_anomaly?: GroupMetrics[]
  live_policy?: {
    suppressed_origins: number
    suppression_ratio: number
    published: Metrics
  }
  by_distance: (GroupMetrics & { distance_steps: number })[]
  by_window: (GroupMetrics & { start_seconds: number })[]
  day_block_brier_95: [number, number] | null
}
export interface ResearchReport {
  run_id?: string
  dataset_fingerprint?: string
  origin_stride_seconds?: number
  selection?: {
    start: string | null
    end: string | null
    origins: number
    dates: number
  }
  origin_audit?: {
    candidate_origins: number
    accepted_origins: number
    excluded_origins: number
    excluded_by_reason: Record<string, number>
  }
  stage_analysis?: {
    event_dates: string[]
    sampled_event_dates: string[]
    phase_dates: Record<string, string[]>
  }
  config: { instrument: { base: string; quote: string } }
  warmup_dates?: string[]
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
    missing_minute_rows?: number
    sampled_seconds?: number
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

export interface GroupMetrics extends Metrics {
  regime?: string
  distance_steps?: number
  start_seconds?: number
  origins?: number
  dates?: number
  day_block_brier_95?: [number, number] | null
}
export interface ReplayPage {
  run_id: string
  total: number
  offset: number
  origins: { timestamp_us: number; reference_price: string; day: string }[]
  models: string[]
}
export interface ReplayDetail {
  run_id: string
  model: string
  day: string
  grid: Grid
  probabilities: number[][]
  labels: (number | null)[][]
  status: string
}
export interface ExperimentReport {
  dataset_fingerprint: string
  train_dates: string[]
  validation_dates: string[]
  untouched_test_dates: string[]
  validation_origins: number
  variants: {
    count: number
    seed: number
    fraction: number
    minimum: number
    mapping: string
    horizon: number
    stride: number
    origins: number
    brier: number
    mean_ms: number
    rmse_vs_4096_paths: number
  }[]
  monte_carlo: {
    paths: number
    seeds: number
    mean_cell_std: number
    max_cell_std: number
  }[]
  limitations: string[]
}
