/** Display-only reads: one request, bounded time, immediate foreground recovery. */
export function createReadPoller<T>(options: {
  url: string; intervalMs: number; timeoutMs?: number
  onData: (data: T) => void; onError: (error: string) => void; onSettled?: () => void
}) {
  let stopped = true, pending = false, flight: Promise<void> | null = null
  let controller: AbortController | null = null, interval: ReturnType<typeof setInterval> | undefined
  const refresh = (afterCurrent = false): Promise<void> => {
    if (stopped || document.visibilityState === 'hidden') return Promise.resolve()
    if (flight) { pending ||= afterCurrent; return flight }
    const request = new AbortController()
    controller = request
    let quiet = false, timeout: ReturnType<typeof setTimeout>
    const abort = new Promise<never>((_, reject) => {
      request.signal.addEventListener('abort', () => {
        quiet = stopped || document.visibilityState === 'hidden'
        reject(new Error('Refresh timed out'))
      }, { once: true })
      timeout = setTimeout(() => request.abort(), options.timeoutMs ?? 20000)
    })
    flight = (async () => {
      try {
        const data = await Promise.race([abort, (async () => {
          const response = await fetch(options.url, { cache: 'no-store', signal: request.signal })
          if (!response.ok) throw new Error(`HTTP ${response.status}`)
          return await response.json() as T
        })()])
        if (!stopped && !request.signal.aborted) options.onData(data)
      } catch (error) {
        if (!stopped && !quiet) options.onError(error instanceof Error ? error.message : 'Unavailable')
      } finally {
        clearTimeout(timeout!)
        if (!stopped && !quiet) options.onSettled?.()
        controller = null; flight = null
        if (pending && !stopped) { pending = false; void refresh() }
      }
    })()
    return flight
  }
  const visible = () => {
    if (document.visibilityState === 'hidden') controller?.abort()
    else void refresh(true)
  }
  return {
    refresh,
    start() {
      if (!stopped) return
      stopped = false
      document.addEventListener('visibilitychange', visible)
      interval = setInterval(() => void refresh(), options.intervalMs)
      void refresh()
    },
    stop() {
      stopped = true; pending = false; controller?.abort()
      clearInterval(interval); document.removeEventListener('visibilitychange', visible)
    },
  }
}
