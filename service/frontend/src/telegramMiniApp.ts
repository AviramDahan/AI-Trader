// Display-only Telegram integration. Launch parameters never grant API access.
export const TELEGRAM_SDK = 'https://telegram.org/js/telegram-web-app.js?64'

type Insets = Partial<Record<'top' | 'bottom' | 'left' | 'right', number>>
type WebApp = {
  ready: () => void
  expand: () => void
  viewportStableHeight?: number
  safeAreaInset?: Insets
  contentSafeAreaInset?: Insets
  onEvent?: (name: string, callback: () => void) => void
  offEvent?: (name: string, callback: () => void) => void
  BackButton?: { show: () => void; hide: () => void; onClick: (cb: () => void) => void; offClick: (cb: () => void) => void }
}
type TelegramWindow = Window & { Telegram?: { WebApp?: WebApp } }

export function isMiniAppEntry(search: string): boolean {
  return new URLSearchParams(search).get('miniapp') === '1'
}

export function preserveMiniApp(path: string, search: string, hash: string): string {
  return isMiniAppEntry(search) ? `${path}${path.includes('?') ? '&' : '?'}miniapp=1${hash}` : path
}

export function mountTelegramMiniApp(win: TelegramWindow = window, doc: Document = document): () => void {
  // Ordinary website visits do not load a third-party SDK. These parameters
  // indicate a display environment, NOT authenticated identity or authority.
  const params = new URLSearchParams(win.location.hash.slice(1))
  if (!isMiniAppEntry(win.location.search) || !params.has('tgWebAppPlatform') || !params.has('tgWebAppVersion')) return () => {}
  let active = true, app: WebApp | undefined
  const root = doc.documentElement
  const events = ['viewportChanged', 'safeAreaChanged', 'contentSafeAreaChanged']
  const dimension = (value: unknown, max: number) => typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(value, max)) : 0
  const sync = () => {
    if (!active || !app) return
    for (const edge of ['top', 'bottom', 'left', 'right'] as const) {
      root.style.setProperty(`--miniapp-safe-${edge}`, `${dimension(app.safeAreaInset?.[edge], 200) + dimension(app.contentSafeAreaInset?.[edge], 200)}px`)
    }
    const height = dimension(app.viewportStableHeight, 10000)
    if (height > 0) root.style.setProperty('--miniapp-height', `${height}px`)
  }
  const connect = () => {
    if (!active || app || !win.Telegram?.WebApp) return
    app = win.Telegram.WebApp
    root.classList.add('telegram-miniapp')
    sync()
    // Older clients may lack inset events; ordinary responsive rendering still works.
    try { for (const event of events) app.onEvent?.(event, sync) } catch { /* Optional display API only. */ }
    try { app.ready(); app.expand() } catch { /* SDK failure must not block the website. */ }
    win.dispatchEvent?.(new Event('ai-trader:miniapp-ready'))
  }
  let script: HTMLScriptElement | undefined
  if (win.Telegram?.WebApp) connect()
  else {
    script = doc.createElement('script')
    script.src = TELEGRAM_SDK
    script.async = true
    script.onload = connect
    doc.head.appendChild(script)
  }
  return () => {
    active = false
    if (script) { script.onload = null; script.remove() }
    try { for (const event of events) app?.offEvent?.(event, sync) } catch { /* Optional display API only. */ }
    root.classList.remove('telegram-miniapp')
    for (const key of ['height', 'safe-top', 'safe-bottom', 'safe-left', 'safe-right']) root.style.removeProperty(`--miniapp-${key}`)
  }
}

/** Navigation only, including SDK loaded after React mounted. No launch identity is used. */
export function installMiniAppBackButton(back: () => void, win: TelegramWindow = window): () => void {
  let button: WebApp['BackButton']
  const attach = () => {
    if (button || !isMiniAppEntry(win.location.search)) return
    button = win.Telegram?.WebApp?.BackButton
    try { button?.onClick(back); button?.show() } catch { /* On-screen back remains available. */ }
  }
  attach()
  win.addEventListener?.('ai-trader:miniapp-ready', attach)
  return () => {
    win.removeEventListener?.('ai-trader:miniapp-ready', attach)
    try { button?.offClick(back); button?.hide() } catch { /* Optional display API. */ }
  }
}
