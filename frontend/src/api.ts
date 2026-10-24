export interface Health {
  status: 'ok'
  service: 'pripre-api'
  version: string
  stage: 'scaffold'
}

export async function fetchHealth(): Promise<Health> {
  const response = await fetch('/api/health', {
    signal: AbortSignal.timeout(5000),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const data: unknown = await response.json()
  if (
    typeof data !== 'object' ||
    data === null ||
    !('status' in data) ||
    data.status !== 'ok' ||
    !('service' in data) ||
    data.service !== 'pripre-api' ||
    !('stage' in data) ||
    data.stage !== 'scaffold' ||
    !('version' in data) ||
    typeof data.version !== 'string'
  )
    throw new Error('Invalid health response')
  return data as Health
}
