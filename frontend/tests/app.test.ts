import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { fetchHealth } from '../src/api'

const healthy = {
  status: 'ok',
  service: 'pripre-api',
  version: '0.1.0',
  stage: 'scaffold',
}

afterEach(() => vi.unstubAllGlobals())

describe('service status', () => {
  it('shows backend connectivity while explicitly marking research as unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(healthy))),
    )
    const wrapper = mount(App)
    expect(wrapper.get('[role="status"]').text()).toContain('正在连接')
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toContain('后端已连接')
    expect(wrapper.text()).toContain('尚未接入行情')
    wrapper.unmount()
  })

  it('shows a failure and recovers on retry', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockRejectedValueOnce(new Error('offline'))
        .mockResolvedValueOnce(new Response(JSON.stringify(healthy))),
    )
    const wrapper = mount(App)
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toContain('暂时不可用')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toContain('后端已连接')
    wrapper.unmount()
  })

  it('rejects an HTTP failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('', { status: 503 })),
    )
    await expect(fetchHealth()).rejects.toThrow('HTTP 503')
  })

  it('rejects an unrelated or malformed successful response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' }))),
    )
    await expect(fetchHealth()).rejects.toThrow('Invalid health response')
  })
})
