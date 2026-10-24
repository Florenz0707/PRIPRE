import { ref } from 'vue'
import { parseSnapshot, type Snapshot } from './api'

export function createLiveConnection() {
  const snapshot = ref<Snapshot | null>(null)
  const connected = ref(false)
  let socket: WebSocket | undefined
  let reconnect: ReturnType<typeof setTimeout> | undefined
  let expiry: ReturnType<typeof setTimeout> | undefined
  let stopped = false

  function connect() {
    if (stopped) return
    socket = new WebSocket(
      `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/stream`,
    )
    socket.onopen = () => {
      connected.value = true
    }
    socket.onmessage = (event) => {
      try {
        snapshot.value = parseSnapshot(JSON.parse(String(event.data)))
        if (expiry) clearTimeout(expiry)
        expiry = setTimeout(() => {
          snapshot.value = {
            status: 'connection_stale',
            timestamp_us: Date.now() * 1000,
            probabilities: null,
          }
        }, 3500)
      } catch {
        snapshot.value = {
          status: 'invalid_response',
          timestamp_us: Date.now() * 1000,
          probabilities: null,
        }
      }
    }
    socket.onclose = () => {
      connected.value = false
      snapshot.value = {
        status: 'connection_lost',
        timestamp_us: Date.now() * 1000,
        probabilities: null,
      }
      if (!stopped) reconnect = setTimeout(connect, 3000)
    }
    socket.onerror = () => {
      socket?.close()
    }
  }

  function stop() {
    stopped = true
    if (reconnect) clearTimeout(reconnect)
    if (expiry) clearTimeout(expiry)
    socket?.close()
  }

  return { snapshot, connected, connect, stop }
}
