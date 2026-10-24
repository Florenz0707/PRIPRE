import { shallowRef, watch, type Ref } from 'vue'

// The watcher owns request cancellation, stale-result fencing and scope cleanup.
export function useRemoteJSON<T>(url: Readonly<Ref<string | null>>) {
  const data = shallowRef<T | null>(null)
  const pending = shallowRef(false)
  const error = shallowRef('')
  watch(
    url,
    async (path, _previous, onCleanup) => {
      const controller = new AbortController()
      let current = true
      onCleanup(() => {
        current = false
        controller.abort()
      })
      data.value = null
      error.value = ''
      pending.value = !!path
      if (!path) return
      try {
        const response = await fetch(path, {
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(30000),
          ]),
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const result = (await response.json()) as T
        if (current) data.value = result
      } catch (cause) {
        if (current)
          error.value = cause instanceof Error ? cause.message : '请求失败'
      } finally {
        if (current) pending.value = false
      }
    },
    { immediate: true },
  )
  return { data, pending, error }
}
