import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResearchPanel from '../src/ResearchPanel.vue'
import ReplayPanel from '../src/ReplayPanel.vue'
import type { ResearchReport, ModelReport, ReplayDetail } from '../src/api'

function model(brier: number | null): ModelReport {
  return {
    summary: {
      count: brier == null ? 0 : 735,
      unknown: 0,
      brier,
      reliability: [],
    },
    daily: [],
    by_regime: [],
    by_distance: [],
    by_window: [],
    day_block_brier_95: null,
  }
}
function report(brier: number | null): ResearchReport {
  return {
    run_id: 'run',
    generated_at: '',
    model: 'conditional-calibrated',
    config: { instrument: { base: 'BTC', quote: 'USDT' } },
    models: { 'conditional-calibrated': model(brier) },
    folds: [],
    data: {
      minute_rows: 100,
      minute_gap_count: 0,
      minute_start_us: null,
      minute_end_us: null,
      sample_dates: [],
      trade_rows: 10,
      local_bytes: 100,
    },
    market_context: [],
    latency_ms: { p50: 1, p95: 2, max: 3 },
    out_of_distribution_origins: 0,
    limitations: [],
  }
}
const options = {
  global: {
    stubs: { Chart: true, ReplayPanel: true, ResearchDiagnostics: true },
  },
}
afterEach(() => vi.unstubAllGlobals())
describe('research date selection', () => {
  it('updates displayed probability metrics and restores full-range results', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(report(0.12345))))
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(ResearchPanel, {
      props: { report: report(0.56789) },
      ...options,
    })
    expect(wrapper.text()).toContain('0.56789')
    await wrapper.findAll('input')[0]!.setValue('2026-02-01')
    await wrapper.findAll('input')[1]!.setValue('2026-02-28')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(fetch.mock.calls[0]![0]).toBe(
      '/api/research?start=2026-02-01&end=2026-02-28',
    )
    expect(wrapper.text()).toContain('0.12345')
    expect(wrapper.text()).not.toContain('0.56789')
    await wrapper.get('form button[type="button"]').trigger('click')
    expect(wrapper.text()).toContain('0.56789')
    wrapper.unmount()
  })
  it('rejects reversed bounds and explains a selection with no test origins', async () => {
    const empty = {
      ...report(null),
      selection: { start: '2027-01-01', end: null, origins: 0, dates: 0 },
    }
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(empty)))
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(ResearchPanel, {
      props: { report: report(0.5) },
      ...options,
    })
    await wrapper.findAll('input')[0]!.setValue('2027-01-01')
    await wrapper.findAll('input')[1]!.setValue('2026-01-01')
    await wrapper.get('form').trigger('submit')
    expect(fetch).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('不能晚于')
    await wrapper.findAll('input')[1]!.setValue('')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('所选范围没有样本外预测')
    expect(wrapper.text()).not.toContain('0.50000')
    wrapper.unmount()
  })
})
const frame: ReplayDetail = {
  run_id: 'run',
  model: 'first',
  day: '2026-01-11',
  status: 'ready',
  grid: {
    timestamp_us: 1000000,
    reference_price: '12345',
    prices: [{ lower: '12300', upper: '12400' }],
    windows: [{ start_us: 6000000, end_us: 11000000 }],
  },
  probabilities: [[0.3]],
  labels: [[1]],
}
describe('historical replay', () => {
  it('renders frozen probabilities and labels, and fences late model responses', async () => {
    let late: ((value: Response) => void) | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.startsWith('/api/replay?'))
          return Promise.resolve(
            new Response(
              JSON.stringify({
                run_id: 'run',
                total: 1,
                offset: 0,
                models: ['first', 'slow', 'latest'],
                origins: [
                  {
                    timestamp_us: 1000000,
                    reference_price: '12345',
                    day: '2026-01-11',
                  },
                ],
              }),
            ),
          )
        if (url.includes('model=slow'))
          return new Promise<Response>((resolve) => {
            late = resolve
          })
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...frame,
              model: url.includes('latest') ? 'latest' : 'first',
            }),
          ),
        )
      }),
    )
    const wrapper = mount(ReplayPanel, {
      props: { start: '', end: '', model: 'first', runId: 'run' },
      global: { stubs: { Chart: true } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('参考价 12345')
    const charts = wrapper.findAllComponents({ name: 'Chart' })
    expect(charts).toHaveLength(2)
    expect(charts[0]!.props('option').series[0].data).toEqual([[0, 0, 0.3]])
    expect(charts[1]!.props('option').series[0].data).toEqual([[0, 0, 1]])
    await wrapper.setProps({ model: 'slow' })
    await wrapper.setProps({ model: 'latest' })
    await flushPromises()
    late?.(new Response(JSON.stringify({ ...frame, model: 'slow' })))
    await flushPromises()
    expect(wrapper.text()).toContain('模型 latest')
    expect(wrapper.text()).not.toContain('模型 slow')
    wrapper.unmount()
  })
  it('clears previous results when loading a failing model', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        Promise.resolve(
          url.startsWith('/api/replay?')
            ? new Response(
                JSON.stringify({
                  run_id: 'run',
                  total: 1,
                  origins: [
                    {
                      timestamp_us: 1000000,
                      reference_price: '12345',
                      day: '2026-01-11',
                    },
                  ],
                  models: ['first'],
                }),
              )
            : url.includes('model=bad')
              ? new Response('', { status: 503 })
              : new Response(JSON.stringify(frame)),
        ),
      ),
    )
    const wrapper = mount(ReplayPanel, {
      props: { start: '', end: '', model: 'first', runId: 'run' },
      global: { stubs: { Chart: true } },
    })
    await flushPromises()
    expect(wrapper.findAll('chart-stub')).toHaveLength(2)
    await wrapper.setProps({ model: 'bad' })
    await flushPromises()
    expect(wrapper.findAll('chart-stub')).toHaveLength(0)
    expect(wrapper.get('[role="alert"]').text()).toContain('HTTP 503')
    wrapper.unmount()
  })
})
