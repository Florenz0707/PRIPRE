import { ref } from 'vue'
import { parseSnapshot, type Snapshot } from './api'

const expiryMs = 3500

export function createLiveConnection() {
  const snapshot = ref<Snapshot | null>(null)
  const connected = ref(false)
  let socket: WebSocket | undefined
  let reconnect: ReturnType<typeof setTimeout> | undefined
  let expiry: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  let progress:
    | { stream?: string; sequence: number; generated: number; received: number }
    | undefined

  function expire() {
    snapshot.value = {
      status: 'connection_stale',
      timestamp_us: snapshot.value?.timestamp_us ?? 0,
      probabilities: null,
    }
    // Reopen the subscription to discard any old transport backlog.
    socket?.close()
  }

  function connect() {
    if (stopped) return
    progress = undefined
    const current = new WebSocket(
      `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/stream`,
    )
    socket = current
    current.onopen = () => {
      if (!stopped && socket === current) connected.value = true
    }
    current.onmessage = (event) => {
      if (stopped || socket !== current) return
      try {
        const next = parseSnapshot(JSON.parse(String(event.data)))
        const received = performance.now()
        const stream = next.stream_id
        // Legacy servers use UTC only to detect progress, never as a fixed local-time anchor.
        const sequence = next.frame_sequence ?? next.timestamp_us
        const generated = next.frame_elapsed_us ?? next.timestamp_us
        const age = next.frame_age_ms ?? 0
        if (age > expiryMs) {
          expire()
          return
        }
        if (!stream && next.status !== 'ready') progress = undefined
        if (progress && progress.stream === stream) {
          if (
            sequence <= progress.sequence ||
            generated <= progress.generated
          ) {
            if (received - progress.received >= expiryMs) expire()
            return // Repeated frames must not renew the expiry timer.
          }
          const delayed =
            received -
            progress.received -
            (generated - progress.generated) / 1000
          if (delayed + age > expiryMs) {
            expire()
            return
          }
        }
        progress = { stream, sequence, generated, received }
        snapshot.value = next
        if (expiry) clearTimeout(expiry)
        expiry = setTimeout(expire, expiryMs - age)
      } catch {
        snapshot.value = {
          status: 'invalid_response',
          timestamp_us: snapshot.value?.timestamp_us ?? 0,
          probabilities: null,
        }
        current.close()
      }
    }
    current.onclose = () => {
      if (socket !== current) return
      connected.value = false
      if (expiry) clearTimeout(expiry)
      socket = undefined
      if (stopped) return
      if (
        !['connection_stale', 'invalid_response'].includes(
          snapshot.value?.status ?? '',
        )
      ) {
        snapshot.value = {
          status: 'connection_lost',
          timestamp_us: snapshot.value?.timestamp_us ?? 0,
          probabilities: null,
        }
      }
      reconnect = setTimeout(connect, 3000)
    }
    current.onerror = () => current.close()
  }

  function stop() {
    stopped = true
    connected.value = false
    if (reconnect) clearTimeout(reconnect)
    if (expiry) clearTimeout(expiry)
    socket?.close()
  }

  return { snapshot, connected, connect, stop }
}
