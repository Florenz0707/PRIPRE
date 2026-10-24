import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { fetchHealth, parseSnapshot } from '../src/api'

const healthy = {
  status: 'ok',
  service: 'pripre-api',
  version: '0.1.0',
  stage: 'research',
}
const sockets: Socket[] = []
class Socket {
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor() {
    sockets.push(this)
  }
  close() {
    this.onclose?.()
  }
  emit(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) })
  }
}
const options = { global: { stubs: { Chart: true, ResearchPanel: true } } }
beforeEach(() => {
  sockets.length = 0
  vi.stubGlobal('WebSocket', Socket)
})
afterEach(() => vi.unstubAllGlobals())

function setupFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) => {
      if (path === '/api/health')
        return Promise.resolve(new Response(JSON.stringify(healthy)))
      if (path === '/api/config')
        return Promise.resolve(
          new Response(
            JSON.stringify({
              grid: {
                price_step: '100',
                half_width: 10,
                first_window_seconds: 5,
                window_seconds: 5,
                horizon_seconds: 180,
              },
              runtime: { max_clients: 50, paths: 512, live_enabled: false },
            }),
          ),
        )
      return Promise.resolve(new Response('', { status: 404 }))
    }),
  )
}
describe('research workspace', () => {
  it('separates process health from unavailable live predictions and missing research', async () => {
    setupFetch()
    const wrapper = mount(App, options)
    await flushPromises()
    sockets[0]!.emit({
      status: 'disabled',
      timestamp_us: 1000000,
      probabilities: null,
    })
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toContain('后端已连接')
    expect(wrapper.text()).toContain('实时采集尚未启用')
    await wrapper.findAll('nav button')[1]!.trigger('click')
    expect(wrapper.text()).toContain('尚无可用研究报告')
    wrapper.unmount()
  })

  it('clears a previously valid matrix on stale data', async () => {
    setupFetch()
    const wrapper = mount(App, options)
    await flushPromises()
    const grid = {
      timestamp_us: Date.now() * 1000,
      reference_price: '1000',
      prices: [{ lower: '950', upper: '1050' }],
      windows: [{ start_us: 6000000, end_us: 11000000 }],
    }
    sockets[0]!.emit({
      status: 'ready',
      timestamp_us: Date.now() * 1000,
      reference_price: '1000',
      grid,
      probabilities: [[0.5]],
    })
    await flushPromises()
    expect(wrapper.find('chart-stub').exists()).toBe(true)
    sockets[0]!.emit({
      status: 'stale',
      timestamp_us: 2000000,
      probabilities: [[0.5]],
    })
    await flushPromises()
    expect(wrapper.find('chart-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('行情已过期')
    wrapper.unmount()
  })

  it('rejects buffered frames using monotonic time rather than the host clock', async () => {
    setupFetch()
    const wrapper = mount(App, options)
    await flushPromises()
    const timestamp = Date.now() * 1000 - 10_000_000
    const timer = vi.spyOn(performance, 'now').mockReturnValue(0)
    const buffered = {
      status: 'ready',
      timestamp_us: timestamp,
      grid: {
        timestamp_us: timestamp,
        reference_price: '1000',
        prices: [{ lower: '950', upper: '1050' }],
        windows: [{ start_us: timestamp + 5e6, end_us: timestamp + 10e6 }],
      },
      probabilities: [[0.5]],
    }
    sockets[0]!.emit(buffered)
    await flushPromises()
    expect(wrapper.find('chart-stub').exists()).toBe(true)
    timer.mockReturnValue(10000)
    sockets[0]!.emit(buffered)
    await flushPromises()
    expect(wrapper.find('chart-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('推送已过期')
    wrapper.unmount()
  })

  it('rejects invalid matrix dimensions and probabilities', () => {
    expect(() =>
      parseSnapshot({ status: 'ready', probabilities: [[2]] }),
    ).toThrow('Invalid probability matrix')
  })

  it('rejects an HTTP failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('', { status: 503 })),
    )
    await expect(fetchHealth()).rejects.toThrow('HTTP 503')
  })

  it('rejects an unrelated successful health response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' }))),
    )
    await expect(fetchHealth()).rejects.toThrow('Invalid health response')
  })
})
