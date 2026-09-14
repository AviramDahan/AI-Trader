// This manifest contains a PUBLIC endpoint only, never a key or bearer token.
let backendOrigin = ''
export function runtimeOrigin() { return backendOrigin }

export async function discoverBackend(): Promise<boolean> {
  if (!import.meta.env.PROD) return false
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}runtime-config.json?t=${Date.now()}`, {
      cache: 'no-store', signal: AbortSignal.timeout(7000),
    })
    if (!response.ok) return false
    const value = await response.json()
    const url = new URL(value.backend_url)
    if (url.protocol !== 'https:' || !/^[a-z0-9-]+\.serveousercontent\.com$/.test(url.hostname)
      || url.username || url.password || url.pathname !== '/') return false
    const changed = !!backendOrigin && url.origin !== backendOrigin
    backendOrigin = url.origin
    return changed
  } catch { return false }
}
