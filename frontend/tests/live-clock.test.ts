import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createLiveConnection } from '../src/live'

class Socket {
  static instances: Socket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor() {
    Socket.instances.push(this)
  }
  close() {
    this.onclose?.()
  }
  emit(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) })
  }
}
function frame(sequence: number, utc: number, elapsed: number) {
  return {
    status: 'ready',
    timestamp_us: utc,
    stream_id: 'test-stream',
    frame_sequence: sequence,
    frame_elapsed_us: elapsed,
    frame_age_ms: 20,
    grid: {
      timestamp_us: utc,
      reference_price: '1000',
      prices: [{ lower: '950', upper: '1050' }],
      windows: [{ start_us: utc + 5e6, end_us: utc + 10e6 }],
    },
    probabilities: [[0.5]],
  }
}
beforeEach(() => {
  Socket.instances = []
  vi.stubGlobal('WebSocket', Socket)
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
describe('source time corrections and frame freshness', () => {
  it('keeps new frames valid across a backward UTC correction', () => {
    const timer = vi.spyOn(performance, 'now').mockReturnValue(0)
    const live = createLiveConnection()
    live.connect()
    const socket = Socket.instances[0]!
    socket.emit(frame(1, 100e6, 10e6))
    timer.mockReturnValue(1000)
    socket.emit(frame(2, 93e6, 11e6))
    expect(live.snapshot.value?.status).toBe('ready')
    live.stop()
  })
  it('does not accumulate browser clock slew into false expiry', () => {
    const timer = vi.spyOn(performance, 'now').mockReturnValue(0)
    const live = createLiveConnection()
    live.connect()
    const socket = Socket.instances[0]!
    for (let second = 0; second <= 300; second++) {
      timer.mockReturnValue(second * 1030)
      socket.emit(frame(second + 1, (100 + second) * 1e6, second * 1e6))
      expect(live.snapshot.value?.status).toBe('ready')
    }
    live.stop()
  })
})

it('expires repeated frames, reconnects, and ignores late frames from the old socket', () => {
  vi.useFakeTimers()
  const live = createLiveConnection()
  live.connect()
  const old = Socket.instances[0]!
  old.emit(frame(1, 100e6, 10e6))
  for (let i = 0; i < 3; i++) {
    vi.advanceTimersByTime(1000)
    old.emit(frame(1, 100e6, 10e6))
  }
  vi.advanceTimersByTime(600)
  expect(live.snapshot.value?.status).toBe('connection_stale')
  vi.advanceTimersByTime(3000)
  const current = Socket.instances[1]!
  current.emit(frame(10, 101e6, 15e6))
  old.emit(frame(100, 200e6, 200e6))
  expect(live.snapshot.value?.timestamp_us).toBe(101e6)
  expect(live.snapshot.value?.status).toBe('ready')
  live.stop()
})
it('rejects a delayed progressing frame and a frame already old in the server queue', () => {
  const timer = vi.spyOn(performance, 'now').mockReturnValue(0)
  const live = createLiveConnection()
  live.connect()
  const socket = Socket.instances[0]!
  socket.emit(frame(1, 100e6, 10e6))
  timer.mockReturnValue(10000)
  socket.emit(frame(2, 101e6, 11e6))
  expect(live.snapshot.value?.status).toBe('connection_stale')
  live.stop()
  const other = createLiveConnection()
  other.connect()
  Socket.instances
    .at(-1)!
    .emit({ ...frame(1, 100e6, 10e6), frame_age_ms: 4000 })
  expect(other.snapshot.value?.status).toBe('connection_stale')
  other.stop()
})
