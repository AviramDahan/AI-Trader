import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { API_ORIGIN, useLanguage } from './appShared'

type Dashboard = {
  market: { is_open: boolean }
  paper_only: boolean
  scanner_name: string
  primary_user: Record<string, any>
  visible_users: Record<string, any>[]
  main_portfolio: Record<string, any>
  settings: Record<string, any>
  account: Record<string, any>
  activity: Record<string, any>
  signals: Record<string, any>[]
  trades: Record<string, any>[]
  news: Record<string, any>[]
  news_schedules: Record<string, any>[]
  news_providers: Record<string, any>[]
  news_meta: Record<string, any>
  news_watchlist: Record<string, any>[]
  services: Record<string, any>[]
  strategy_comparison: Record<string, any>[]
  rejected: Record<string, any>[]
  legacy_unverified_count: number
  legacy_positions: Record<string, any>
  lifecycle_verification: Record<string, any>
}

const fmtPrice = (value: any) => value != null && value !== '' && Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : '—'
const fmtPct = (value: any) => Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : '—'
const fmtMove = (entry: any, target: any) => {
  const from = Number(entry)
  const to = Number(target)
  if (!Number.isFinite(from) || !Number.isFinite(to) || from <= 0) return '—'
  const change = (to / from - 1) * 100
  return `${change >= 0 ? '+' : ''}${change.toFixed(1)}%`
}

export function ScannerDashboard({ token }: { token: string | null }) {
  const { language } = useLanguage()
  const he = language === 'he'
  const location = useLocation()
  const navigate = useNavigate()
  const requestedTab = new URLSearchParams(location.search).get('tab') || 'signals'
  const tab = ['signals', 'trades', 'results', 'news', 'status'].includes(requestedTab) ? requestedTab : 'signals'
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [tickerFilter, setTickerFilter] = useState('')
  const [sentimentFilter, setSentimentFilter] = useState('all')
  const [materialityFilter, setMaterialityFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [scopeFilter, setScopeFilter] = useState('all')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [timeFilter, setTimeFilter] = useState('168')
  const [watchTicker, setWatchTicker] = useState('')
  const [watchStatus, setWatchStatus] = useState('')
  const [watchBusy, setWatchBusy] = useState(false)
  const [quoteInfo, setQuoteInfo] = useState<Record<string, any> | null>(null)

  const load = async () => {
    try {
      const response = await fetch(`${API_ORIGIN}/api/scanner/dashboard`, { cache: 'no-store', signal: AbortSignal.timeout(12000) })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setData(await response.json())
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unavailable')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    const interval = window.setInterval(() => void load(), 30000)
    return () => window.clearInterval(interval)
  }, [])

  useEffect(() => {
    const loadQuotes = async () => {
      try {
        const response = await fetch(`${API_ORIGIN}/api/scanner/quotes`, { cache: 'no-store', signal: AbortSignal.timeout(8000) })
        if (!response.ok) return
        const payload = await response.json()
        const quotes = new Map((payload.quotes || []).map((quote: Record<string, any>) => [quote.ticker, quote]))
        setQuoteInfo(payload)
        setData(current => current ? {
          ...current,
          signals: current.signals.map(signal => {
            const quote: any = quotes.get(signal.ticker)
            return quote ? { ...signal, current_price: quote.price, price_as_of: quote.as_of, price_source: quote.source, price_stale: quote.stale } : signal
          }),
          trades: current.trades.map(trade => {
            const quote: any = quotes.get(trade.ticker)
            return quote ? { ...trade, current_price: quote.price, price_as_of: quote.as_of, price_source: quote.source, price_stale: quote.stale } : trade
          }),
        } : current)
      } catch {
        // Keep the last successful quote. The main connection status remains independent.
      }
    }
    void loadQuotes()
    const interval = window.setInterval(() => void loadQuotes(), 10000)
    return () => window.clearInterval(interval)
  }, [])

  const text = (hebrew: string, english: string) => he ? hebrew : english
  const stamp = (value: any) => value ? new Date(value).toLocaleString(he ? 'he-IL' : 'en-GB') : '—'
  const providerName = (name: string) => he ? ({ sec_edgar: 'SEC EDGAR', federal_reserve: 'הפדרל ריזרב', bls: 'הלשכה לסטטיסטיקת עבודה (BLS)', fda: 'מנהל המזון והתרופות (FDA)', ftc: 'נציבות הסחר הפדרלית (FTC)', doj: 'משרד המשפטים האמריקאי (DOJ)', eia: 'מנהל מידע האנרגיה (EIA)', yahoo_priority: 'Yahoo — מניות בעדיפות', existing_market: 'חדשות השוק הקיימות' } as Record<string, string>)[name] || name : name
  const providerStatus = (status: string) => he ? ({ ok: 'תקין', no_new: 'אין ידיעות חדשות', not_modified: 'ללא שינוי (304)', degraded: 'תקין חלקית', backoff_not_checked: 'לא נבדק — המתנה', rate_limited: 'מוגבל קצב', error: 'תקלה', config_required: 'דורש הגדרה', waiting: 'ממתין' } as Record<string, string>)[status] || status : status
  const providerCounters = (provider: Record<string, any>) => text(
    `התקבלו: ${provider.last_received_count || 0} · נקלטו: ${provider.last_ingested_count || 0} · כפילויות: ${provider.last_duplicate_count || 0} · נדחו בשיוך: ${provider.last_rejected_assignment_count || 0} · נדחו בתאריך: ${provider.last_rejected_date_count || 0}`,
    `Received: ${provider.last_received_count || 0} · ingested: ${provider.last_ingested_count || 0} · duplicates: ${provider.last_duplicate_count || 0} · rejected assignment: ${provider.last_rejected_assignment_count || 0} · rejected date: ${provider.last_rejected_date_count || 0}`)
  const providerCoverage = (provider: Record<string, any>) => {
    if (!he) return provider.coverage
    const fixed: Record<string, string> = {
      sec_edgar: 'עד 100 דיווחי EDGAR אחרונים; רק שיוכי CIK/סימול שאומתו ביקום הסריקה. מטא־דאטה בלבד.',
      federal_reserve: 'פיד רשמי משותף של הודעות הפדרל ריזרב; ללא גוף כתבה מלא.',
      bls: 'פידי תעסוקה, מדד המחירים לצרכן ו־JOLTS; ללא גוף כתבה מלא.',
      fda: 'פיד רשמי של הודעות FDA; חדשות ענף/רגולציה ללא שיוך מניה כפוי וללא התראות אוטומטיות.',
      ftc: 'פידי הודעות FTC, הגנת צרכן ותחרות; ללא שיוך מניה כפוי וללא התראות אוטומטיות.',
      doj: 'עד 50 הודעות DOJ אחרונות בכל בקשה; ללא שיוך מניה כפוי וללא התראות אוטומטיות.',
      eia: 'Today in Energy והודעות EIA רשמיות; חדשות ענף/מאקרו ללא התראות אוטומטיות.',
      existing_market: 'צילומי החדשות האחרונים ממנגנון חדשות השוק הקיים.',
    }
    if (provider.provider === 'yahoo_priority') {
      const counts = String(provider.coverage || '').match(/(\d+) open-position, (\d+) watchlist, (\d+) active-signal and (\d+) rotating candidate/)
      return counts ? `${counts[1]} פוזיציות פתוחות, ${counts[2]} מניות במעקב, ${counts[3]} סיגנלים פעילים ו־${counts[4]} מועמדים מתחלפים במחזור האחרון. לא כיסוי מלא של כל המניות.` : 'מניות בעדיפות: פוזיציות פתוחות, רשימת מעקב, סיגנלים פעילים ומועמדים מתחלפים.'
    }
    return fixed[provider.provider] || provider.coverage
  }
  const serviceName = (component: string) => he ? ({
    monitor: 'ניטור עסקאות', news: 'תרגום חדשות', news_ai: 'ניתוח חדשות ב־AI',
    news_feed: 'איסוף חדשות', ollama: 'Ollama', position_news: 'חדשות לפוזיציות',
    prices: 'נתוני מחיר', quotes: 'מחיר נוכחי', scan: 'סריקת מניות',
    telegram: 'שליחת Telegram', telegram_status: 'עדכון נושאי Telegram',
  } as Record<string, string>)[component] || component : component
  const serviceStatus = (status: string) => he ? ({
    ok: 'תקין', idle: 'ממתין', market_closed: 'השוק סגור', no_signals: 'אין סיגנלים',
    backoff: 'ממתין למחזור הבא', not_modified: 'ללא שינוי', no_new: 'אין מידע חדש',
    degraded: 'תקין חלקית', error: 'תקלה', rate_limited: 'מוגבל קצב',
    config_required: 'דורש הגדרה', waiting: 'ממתין',
  } as Record<string, string>)[status] || status : status
  const serviceDetail = (service: Record<string, any>) => {
    const detail = String(service.detail || '')
    if (!he) return detail || '—'
    if (service.status === 'error') return 'אירעה תקלה ברכיב. המערכת תנסה שוב אוטומטית.'
    if (service.status === 'rate_limited') return 'הספק הגביל את קצב הבקשות. המערכת ממתינה ותנסה שוב אוטומטית.'
    if (service.status === 'config_required') return 'הרכיב דורש הגדרה בצד השרת.'
    const numbers = (pattern: RegExp) => detail.match(pattern)?.slice(1) || []
    if (service.component === 'monitor') {
      const [bars = '0'] = numbers(/Processed (\d+) complete/)
      return service.status === 'market_closed'
        ? `עובדו ${bars} נרות מלאים של 5 דקות; ניטור המחיר ממתין לפתיחת השוק.`
        : `עובדו ${bars} נרות מלאים של 5 דקות; ניטור העסקאות פעיל.`
    }
    if (service.component === 'news') {
      const [count = '0'] = numbers(/Translated (\d+)/)
      return `תורגמו ${count} כותרות מהמטמון.`
    }
    if (service.component === 'news_ai') return 'אין כרגע ידיעות חדשות שממתינות לניתוח.'
    if (service.component === 'news_feed') {
      const [checked = '0', inserted = '0'] = numbers(/checked=(\d+) inserted=(\d+)/)
      return `נבדקו ${checked} ספקים ונקלטו ${inserted} ידיעות; האיסוף הבא יבוצע לפי לוח הזמנים.`
    }
    if (service.component === 'ollama') return 'התגובה המובנית האחרונה התקבלה בהצלחה.'
    if (service.component === 'position_news') return 'אין כרגע פוזיציות שהגיע מועד סקירת החדשות שלהן.'
    if (service.component === 'prices') {
      const [tickers = '0', bars = '0'] = numbers(/tickers=(\d+) bars=(\d+)/)
      return `${tickers} סימולים במעקב; עובדו ${bars} נרות חדשים.`
    }
    if (service.component === 'quotes') {
      const [updated = '0', total = '0'] = numbers(/updated=(\d+)\/(\d+)/)
      return `עודכנו מחירים עבור ${updated} מתוך ${total} סימולים.`
    }
    if (service.component === 'scan') {
      const [universe = '0', fresh = '0', technical = '0', news = '0', ai = '0', signals = '0'] = numbers(/universe=(\d+) data=(\d+) technical=(\d+) news=(\d+) ai=(\d+) signals=(\d+)/)
      return `יקום ${universe}; נתונים תקינים ${fresh}; עברו סינון ${technical}; חדשות ${news}; נותחו ב־AI ${ai}; אושרו ${signals}.`
    }
    if (service.component === 'telegram') {
      const [sent = '0', retry = '0'] = numbers(/sent=(\d+) retry=(\d+)/)
      return `נשלחו ${sent} הודעות; ${retry} ממתינות לניסיון חוזר.`
    }
    if (service.component === 'telegram_status') return 'מצב התיק והסיגנלים עודכן בנושאי Telegram.'
    return detail || '—'
  }
  const categoryName = (category: string) => he ? ({company: 'חברה', industry: 'ענף ורגולציה', macro: 'מאקרו'} as Record<string, string>)[category] || category : category
  const isActiveSignal = (item: Record<string, any>) => {
    if (item.legacy_unverified || !['ACTIVE', 'PENDING_ENTRY', 'ENTERED'].includes(item.status)) return false
    if (item.status === 'ENTERED') return true
    const validUntil = new Date(item.valid_until).getTime()
    return Number.isFinite(validUntil) && validUntil > Date.now()
  }
  const activity = data?.activity || {}
  const primaryName = he ? (data?.primary_user?.display_name_he || 'סיגנלים פעילים') : (data?.primary_user?.display_name || 'Active Signals')
  const activeSignals = (data?.signals || []).filter(isActiveSignal)
  const historicSignals = (data?.signals || []).filter(item => !item.legacy_unverified && !isActiveSignal(item))
  const filteredNews = useMemo(() => (data?.news || []).filter(item => {
    const tickerOk = !tickerFilter || [item.ticker, ...(item.verified_tickers || [])].join(' ').toUpperCase().includes(tickerFilter.toUpperCase())
    const sentimentOk = sentimentFilter === 'all' || item.sentiment === sentimentFilter || item.impact === sentimentFilter
    const materialityOk = materialityFilter === 'all' || item.materiality === materialityFilter
    const sourceOk = sourceFilter === 'all' || item.provider === sourceFilter || item.publisher === sourceFilter
    const scopeOk = scopeFilter === 'all' || item.scope === scopeFilter
    const categoryOk = categoryFilter === 'all' || item.news_category === categoryFilter
    const cutoff = timeFilter === 'all' ? 0 : Date.now() - Number(timeFilter) * 3600000
    const timeOk = !cutoff || new Date(item.published_at).getTime() >= cutoff
    return tickerOk && sentimentOk && materialityOk && sourceOk && scopeOk && categoryOk && timeOk
  }), [data, tickerFilter, sentimentFilter, materialityFilter, sourceFilter, scopeFilter, categoryFilter, timeFilter])
  const sourceOptions = useMemo(() => Array.from(new Set((data?.news || []).map(item => item.provider || item.publisher).filter(Boolean))).sort(), [data])

  const tabs = [
    ['signals', text('סיגנלים', 'Signals')], ['trades', text('עסקאות דמו', 'Demo trades')],
    ['results', text('תוצאות', 'Results')], ['news', text('חדשות', 'News')],
    ['status', text('מצב הסורק', 'Scanner status')],
  ]

  const changeStrategy = async (strategy: 'single' | 'staged') => {
    if (!token) return
    const response = await fetch(`${API_ORIGIN}/api/scanner/settings/exit-strategy`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ strategy }),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    await load()
  }

  const updateWatchlist = async (ticker: string, remove = false) => {
    if (!token || watchBusy) return
    const normalized = ticker.trim().toUpperCase().replace('.', '-')
    if (!/^[A-Z][A-Z0-9-]{0,9}$/.test(normalized)) {
      setWatchStatus(text('סימול אינו תקין.', 'Invalid ticker.'))
      return
    }
    setWatchBusy(true)
    try {
      const response = await fetch(`${API_ORIGIN}/api/scanner/news-watchlist${remove ? `/${normalized}` : ''}`, {
        method: remove ? 'DELETE' : 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: remove ? undefined : JSON.stringify({ ticker: normalized }),
      })
      if (!response.ok) {
        if (response.status === 401) throw new Error('AUTH_REQUIRED')
        if (response.status === 403) throw new Error('SCANNER_PERMISSION_REQUIRED')
        throw new Error(`HTTP ${response.status}`)
      }
      setWatchTicker('')
      setWatchStatus(remove ? text(`${normalized} הוסר מרשימת המעקב.`, `${normalized} removed from watchlist.`) : text(`${normalized} נוסף. איסוף החדשות יתבצע במחזור הקרוב.`, `${normalized} added. News will be collected on the next cycle.`))
      await load()
    } catch (reason) {
      const code = reason instanceof Error ? reason.message : ''
      setWatchStatus(code === 'AUTH_REQUIRED'
        ? text('ההתחברות פגה. יש להתחבר מחדש.', 'Your session expired. Please sign in again.')
        : code === 'SCANNER_PERMISSION_REQUIRED'
          ? text('למשתמש המחובר אין הרשאת ניהול לסורק.', 'The signed-in user does not have scanner management permission.')
          : text('העדכון נכשל עקב שגיאת שרת או חיבור. נסה שוב.', 'Update failed due to a server or connection error. Please retry.'))
    } finally {
      setWatchBusy(false)
    }
  }

  if (loading && !data) return <div className="scanner-empty">{text('טוען את דשבורד הסורק…', 'Loading scanner dashboard…')}</div>

  return <section className="scanner-dashboard" dir={he ? 'rtl' : 'ltr'}>
    <header className="scanner-hero">
      <div>
        <p className="scanner-kicker">{text('סורק מניות ארה״ב', 'US STOCK SCANNER')}</p>
        <h1>{tabs.find(([key]) => key === tab)?.[1] || primaryName}</h1>
        <p>{text('S&P 500 + Nasdaq 100 · סריקה אוטומטית', 'S&P 500 + Nasdaq 100 · Automatic scanner')}</p>
        <small className="signal-price-time">{data?.market ? text(data.market.is_open ? 'השוק פתוח' : 'השוק סגור', data.market.is_open ? 'Market open' : 'Market closed') : text('מצב שוק לא זמין', 'Market status unavailable')} · {text('סריקה אחרונה', 'Last scan')}: {activity.last_scan_at ? stamp(activity.last_scan_at * 1000) : '—'}</small>
      </div>
      <strong className="paper-only">{text('מסחר מדומה בלבד', 'PAPER TRADING ONLY')}</strong>
    </header>

    {error && <div className="scanner-inline-error">{text('נתוני הסורק אינם זמינים כרגע', 'Scanner data is temporarily unavailable')}: {error} <button onClick={() => void load()}>{text('בדיקה מחדש', 'Retry')}</button></div>}

    <details className="signal-scan-details" open={tab === 'status'}><summary>{text('פרטי הסריקה האחרונה', 'Latest scan details')}</summary>
    <div className="scanner-stage-grid" aria-label={text('שלבי הסריקה האחרונה', 'Latest scan stages')}>
      {[
        [text('יקום', 'Universe'), activity.universe_count],
        [text('נתונים תקינים', 'Fresh data'), activity.data_count],
        [text('עברו סינון', 'Passed filters'), activity.technical_candidates_count],
        [text('חדשות נבדקו', 'News enriched'), activity.shortlist_count],
        [text('נותחו ב־AI', 'AI reviewed'), activity.ai_candidates_count],
        [text('סיגנלים אושרו', 'Approved signals'), activity.signals_published],
      ].map(([label, value]) => <div className="scanner-stat" key={String(label)}><span>{label}</span><strong>{Number(value || 0).toLocaleString()}</strong></div>)}
    </div>

    </details>
    <nav className="scanner-tabs" aria-label={text('ניווט בדשבורד', 'Dashboard navigation')}>
      {tabs.map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => navigate(`/market?tab=${key}`)}>{label}</button>)}
    </nav>

    {tab === 'signals' && <div className="scanner-section">
      <h2>{text('סיגנלים פעילים', 'Active signals')} <small>{activeSignals.length}</small></h2>
      {!activeSignals.length && <Empty text={text('אין כרגע סיגנלים חזקים פעילים — זה מצב תקין והמסננים לא הוחלשו.', 'No strong active signals right now — this is normal and filters were not weakened.')} />}
      {[['pending', text('ממתינים לכניסה', 'Awaiting entry')], ['entered', text('כניסה בוצעה', 'Entry filled')]].map(([group, label]) => {
        const signals = activeSignals.filter(signal => (signal.status === 'ENTERED') === (group === 'entered'))
        return <section className="signal-group" key={group}><h3>{label} <small>{signals.length}</small></h3>
          <div className="signal-list">{signals.map(signal => <SignalCard key={signal.id} signal={signal} he={he} />)}</div>
        </section>
      })}
      <details className="signal-history"><summary>{text('היסטוריה', 'History')} · {historicSignals.length}</summary>
        <div className="signal-list">{historicSignals.map(signal => <SignalCard key={signal.id} signal={signal} he={he} />)}</div>
      </details>
    </div>}

    {tab === 'trades' && <div className="scanner-section">
      <h2>{text(`תיק דמו ראשי — ${primaryName}`, `Main demo portfolio — ${primaryName}`)}</h2>
      <div className="scanner-account-grid">
        <Stat label={text('פוזיציות פתוחות', 'Open positions')} value={String(data?.main_portfolio?.open_position_count ?? 0)} />
      </div>
      <p className="scanner-note">{text('יצירת סיגנל אינה ביצוע. הוראת LIMIT נכנסת רק לאחר שנר מחיר מאומת נוגע במחיר הכניסה.', 'A signal is not a fill. A LIMIT entry fills only after a verified price bar reaches entry.')}</p>
      {(data?.trades || []).filter(trade => !trade.is_shadow).map(trade => <TradeCard key={trade.id} trade={trade} schedules={data?.news_schedules || []} he={he} />)}
      {!(data?.trades || []).some(trade => !trade.is_shadow) && <Empty text={text('אין עדיין עסקאות דמו מאומתות.', 'No verified demo trades yet.')} />}
      {!!data?.legacy_unverified_count && <p className="scanner-warning">{text(`${data.legacy_unverified_count} רשומות ישנות נשמרו בנפרד ואינן נכללות בסטטיסטיקה המאומתת.`, `${data.legacy_unverified_count} legacy records are preserved separately and excluded from verified statistics.`)}</p>}
      {!!data?.legacy_positions?.adopted_count && <p className="scanner-note">{text(`כל ${data.main_portfolio.open_position_count} הפוזיציות מוצגות בתיק הראשי של “${primaryName}”. מתוכן ${data.main_portfolio.verified_position_count} מאומתות חשבונאית ו־${data.main_portfolio.legacy_position_count} מסומנות Legacy ומנוטרות מההעברה ואילך. ל־Legacy לא משוחזרת היסטוריה חסרה, ולכן היא אינה מעורבבת במזומן ובסטטיסטיקה המאומתים.`, `All ${data.main_portfolio.open_position_count} positions appear in the “${primaryName}” main portfolio. ${data.main_portfolio.verified_position_count} are accounting-verified and ${data.main_portfolio.legacy_position_count} are marked Legacy and monitored from adoption onward. Missing Legacy history is not reconstructed, so it remains excluded from verified cash and statistics.`)}</p>}
      {!!data?.legacy_positions?.unmanaged_count && <p className="scanner-warning">{text(`${data.legacy_positions.unmanaged_count} פוזיציות ישנות עדיין דורשות טיפול ואינן מנוהלות.`, `${data.legacy_positions.unmanaged_count} legacy positions still require attention and are unmanaged.`)}</p>}
    </div>}

    {tab === 'results' && <div className="scanner-section">
      <h2>{text('השוואת אסטרטגיות יציאה', 'Exit strategy comparison')}</h2>
      <p className="scanner-note">{text(`האסטרטגיה הפעילה לעסקאות חדשות: ${data?.settings?.active_strategy === 'staged' ? 'מימוש מדורג' : 'יעד יחיד'}. אסטרטגיית Shadow אינה משפיעה על המזומן או על Telegram.`, `Active for new trades: ${data?.settings?.active_strategy || 'single'}. Shadow results never affect cash or Telegram.`)}</p>
      {token && <div className="scanner-strategy-controls"><button disabled={data?.settings?.active_strategy === 'single'} onClick={() => void changeStrategy('single')}>{text('הפעל יעד יחיד לעסקאות חדשות', 'Use single target for new trades')}</button><button disabled={data?.settings?.active_strategy === 'staged'} onClick={() => void changeStrategy('staged')}>{text('הפעל מימוש מדורג לעסקאות חדשות', 'Use staged exits for new trades')}</button></div>}
      <div className="scanner-table-wrap"><table className="scanner-table"><thead><tr>{[text('אסטרטגיה', 'Strategy'), text('עסקאות', 'Trades'), text('תוחלת R', 'Expectancy R'), text('הצלחה', 'Win rate'), 'TP1', 'TP2', 'TP3'].map(value => <th key={value}>{value}</th>)}</tr></thead>
        <tbody>{(data?.strategy_comparison || []).map(row => <tr key={row.strategy}><td>{row.strategy}</td><td>{row.trades} ({row.closed_trades} {text('סגורות', 'closed')})</td><td>{Number(row.expectancy_r || 0).toFixed(2)}R</td><td>{fmtPct(row.win_rate)}</td><td>{fmtPct(row.tp1_rate)}</td><td>{fmtPct(row.tp2_rate)}</td><td>{fmtPct(row.tp3_rate)}</td></tr>)}</tbody></table></div>
      <div className="scanner-comparison-cards">{(data?.strategy_comparison || []).map(row => <article key={row.strategy} className="scanner-comparison-card">
        <header><strong>{row.strategy === 'single' ? text('יעד יחיד', 'Single target') : text('מימוש מדורג (Shadow)', 'Staged exits (Shadow)')}</strong><span>{row.trades} {text('עסקאות', 'trades')} · {row.closed_trades} {text('סגורות', 'closed')}</span></header>
        <dl>
          <div><dt>{text('תוחלת', 'Expectancy')}</dt><dd>{Number(row.expectancy_r || 0).toFixed(2)}R</dd></div>
          <div><dt>{text('שיעור הצלחה', 'Win rate')}</dt><dd>{fmtPct(row.win_rate)}</dd></div>
          <div><dt>TP1</dt><dd>{fmtPct(row.tp1_rate)}</dd></div><div><dt>TP2</dt><dd>{fmtPct(row.tp2_rate)}</dd></div><div><dt>TP3</dt><dd>{fmtPct(row.tp3_rate)}</dd></div>
        </dl>
      </article>)}</div>
      {(data?.strategy_comparison || []).some(row => row.sample_warning) && <p className="scanner-warning">{text('המדגם קטן מ־30 עסקאות סגורות; אין בסיס להכריז על יתרון לאחת האסטרטגיות.', 'The sample has fewer than 30 closed trades; no strategy advantage can be claimed.')}</p>}
    </div>}

    {tab === 'news' && <div className="scanner-section">
      <h2>{text('חדשות — מהחדש לישן', 'News — newest first')}</h2>
      <section className="scanner-watchlist"><h3>{text('רשימת מעקב לחדשות Telegram', 'Telegram news watchlist')}</h3>
        <p>{text('חדשות חדשות, קשורות ומהותיות ינותחו ויישלחו גם ללא פוזיציה. הרשימה אינה יוצרת סיגנלים או עסקאות.', 'New, relevant, material news is analyzed and alerted even without a position. This list creates no signals or trades.')}</p>
        {token ? <div className="scanner-watchlist-form"><input aria-label={text('סימול להוספה', 'Ticker to add')} value={watchTicker} maxLength={10} onChange={event => setWatchTicker(event.target.value.toUpperCase())} onKeyDown={event => { if (event.key === 'Enter') void updateWatchlist(watchTicker) }} placeholder="AAPL"/><button disabled={watchBusy || !watchTicker.trim()} onClick={() => void updateWatchlist(watchTicker)}>{text('הוסף למעקב', 'Add to watchlist')}</button></div> : <p className="scanner-warning">{text('הוספה והסרה דורשות התחברות עם הרשאת ניהול לסורק; הקריאה ברשימה נשארת ציבורית.', 'Adding and removing require a login with scanner management permission; viewing remains public.')}</p>}
        {!!watchStatus && <p className="scanner-note">{watchStatus}</p>}
        <div className="scanner-watchlist-items">{(data?.news_watchlist || []).map(item => <span key={item.ticker}><b>{item.ticker}</b>{item.company && item.company !== item.ticker ? ` · ${item.company}` : ''}{token && <button aria-label={`${text('הסר', 'Remove')} ${item.ticker}`} disabled={watchBusy} onClick={() => void updateWatchlist(item.ticker, true)}>×</button>}</span>)}</div>
        {!(data?.news_watchlist || []).length && <small>{text('הרשימה ריקה.', 'Watchlist is empty.')}</small>}
      </section>
      <div className="scanner-filters"><input value={tickerFilter} onChange={event => setTickerFilter(event.target.value)} placeholder={text('סינון לפי סימול', 'Filter ticker')} />
        <select value={sourceFilter} onChange={event => setSourceFilter(event.target.value)}><option value="all">{text('כל המקורות', 'All sources')}</option>{sourceOptions.map(source => <option value={source} key={source}>{source}</option>)}</select>
        <select value={sentimentFilter} onChange={event => setSentimentFilter(event.target.value)}><option value="all">{text('כל הסנטימנטים', 'All sentiment')}</option><option value="positive">{text('חיובי', 'Positive')}</option><option value="negative">{text('שלילי', 'Negative')}</option><option value="mixed">{text('מעורב', 'Mixed')}</option><option value="neutral">{text('ניטרלי', 'Neutral')}</option></select>
        <select value={materialityFilter} onChange={event => setMaterialityFilter(event.target.value)}><option value="all">{text('כל רמות המהותיות', 'All materiality')}</option><option value="high">{text('מהותיות גבוהה', 'High')}</option><option value="medium">{text('מהותיות בינונית', 'Medium')}</option><option value="low">{text('מהותיות נמוכה', 'Low')}</option></select>
        <select value={scopeFilter} onChange={event => setScopeFilter(event.target.value)}><option value="all">{text('כל סוגי הכיסוי', 'All coverage')}</option><option value="open_position">{text('עסקאות פתוחות', 'Open positions')}</option><option value="watchlist">{text('רשימת מעקב', 'Watchlist')}</option><option value="active_signal">{text('סיגנלים פעילים', 'Active signals')}</option><option value="universe">{text('יקום הסריקה', 'Scanner universe')}</option><option value="market">{text('שוק כללי', 'Broad market')}</option></select>
        <select value={categoryFilter} onChange={event => setCategoryFilter(event.target.value)}><option value="all">{text('כל קטגוריות החדשות', 'All news categories')}</option><option value="company">{text('חברה', 'Company')}</option><option value="industry">{text('ענף ורגולציה', 'Industry and regulation')}</option><option value="macro">{text('מאקרו', 'Macro')}</option></select>
        <select value={timeFilter} onChange={event => setTimeFilter(event.target.value)}><option value="24">{text('24 שעות', '24 hours')}</option><option value="168">{text('7 ימים', '7 days')}</option><option value="all">{text('כל הזמנים', 'All time')}</option></select></div>
      <p className="scanner-note">{text(`איסוף מחזורי, לא זרם בזמן אמת. פידים רשמיים משותפים נבדקים כל ${Math.round(Number(data?.news_meta?.requested_refresh_seconds || 300) / 60)} דקות; Yahoo מכסה בעדיפות עסקאות פתוחות, סיגנלים פעילים ומדגם מתחלף של מועמדים — לא את כל ${activity.universe_count || 0} המניות בכל מחזור.`, `Periodic collection, not a real-time wire. Shared official feeds are checked every ${Math.round(Number(data?.news_meta?.requested_refresh_seconds || 300) / 60)} minutes; Yahoo prioritizes open positions, active signals and a rotating candidate sample—not all ${activity.universe_count || 0} stocks each cycle.`)}</p>
      <p className="scanner-news-meta">{text('רענון תצוגה', 'Screen refresh')}: {stamp(data?.news_meta?.screen_generated_at)} · {text('בדיקת ספק אחרונה', 'Last provider check')}: {stamp(data?.news_meta?.last_collected_at)} · {text('ידיעה אחרונה שנאספה', 'Latest collected item')}: {stamp(data?.news_meta?.latest_item_collected_at)}</p>
      <div className="scanner-status-grid">{(data?.news_providers || []).map(provider => <article key={provider.provider} className={`scanner-status ${provider.status}`}><h3>{providerName(provider.provider)}</h3><strong>{providerStatus(provider.status)}</strong><p>{providerCoverage(provider)}</p><small>{providerCounters(provider)}<br/>{text('הצלחה אחרונה', 'Last success')}: {stamp(provider.last_success_at)}<br/>{text('בדיקה הבאה', 'Next check')}: {stamp(provider.next_check_at)}</small></article>)}</div>
      {(['market', 'watchlist', 'active_signal', 'universe', 'open_position'] as const).map(scope => {
        const rows = filteredNews.filter(item => item.scope === scope)
        if (!rows.length) return null
        const label = scope === 'market' ? text('חדשות שוק רחבות', 'Broad market news') : scope === 'open_position' ? text('חדשות לעסקאות פתוחות', 'Open-position news') : scope === 'watchlist' ? text('חדשות מרשימת המעקב', 'Watchlist news') : scope === 'active_signal' ? text('חדשות לסיגנלים פעילים', 'Active-signal news') : text('חדשות מניות ביקום הסריקה', 'Scanner-universe news')
        return <div key={scope}><h3>{label}</h3>{rows.map(item => <article className="scanner-news-card" key={item.id}>
          <div>{[item.ticker, ...(item.verified_tickers || [])].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).map(ticker => <b key={ticker}>{ticker} </b>)}</div>
          <h3>{he ? (item.title_he || item.summary_he || item.title) : item.title}</h3>
          {item.summary_he && <p><b>{text('תקציר בעברית', 'Hebrew summary')}:</b> {item.summary_he}</p>}
          <p className="scanner-source-fact"><b>{text('מידע מהמקור', 'Source information')}:</b> {item.title}{item.source_facts?.source_excerpt ? ` — ${item.source_facts.source_excerpt}` : ` — ${text('זמינה כותרת/מטא־דאטה בלבד; גוף הכתבה לא נותח.', 'Headline/metadata only; the full article was not analyzed.')}`}</p>
          {item.interpretation_he && <p className="scanner-ai-interpretation"><b>{text('פרשנות AI', 'AI interpretation')}:</b> {item.interpretation_he}</p>}
          <p>{text('סנטימנט', 'Sentiment')}: {item.analysis_status === 'analyzed' ? item.sentiment : text('לא נותח', 'Not analyzed')} · {text('מהותיות', 'Materiality')}: {item.analysis_status === 'analyzed' ? item.materiality : text('לא נותחה', 'Not analyzed')}</p>
          <footer>{text('קטגוריה', 'Category')}: {categoryName(item.news_category || 'company')} · {text('מפרסם מקורי', 'Original publisher')}: {item.original_publisher || item.publisher} · {text('פורסם', 'Published')}: {stamp(item.published_at)} · {text('נאסף לראשונה', 'First collected')}: {stamp(item.collected_at || item.fetched_at)}{item.publication_time_corrected && <> · {text('זמן הפרסום עודכן מאוחר יותר על־ידי המקור', 'The source revised its publication timestamp later')}</>} · <a href={item.url} target="_blank" rel="noreferrer">{text('מקור ישיר', 'Direct source')}</a>{item.signal_id && <> · <a href={`/market?tab=signals#signal-${item.signal_id}`}>{text('לסיגנל', 'Signal')}</a></>}{item.trade_ids?.[0] && <> · <a href={`/market?tab=trades#trade-${item.trade_ids[0]}`}>{text('לעסקה', 'Trade')}</a></>}{item.alternate_sources?.length > 1 && <details><summary>{text('מקורות נוספים', 'Additional sources')} ({item.alternate_sources.length - 1})</summary>{item.alternate_sources.slice(1).map((source: any) => <a key={`${source.provider}-${source.url}`} href={source.url} target="_blank" rel="noreferrer">{source.publisher}</a>)}</details>}</footer>
        </article>)}</div>
      })}
      {!filteredNews.length && <Empty text={text('אין חדשות תואמות. תקלה בספק תוצג בלשונית מצב הסורק ואינה מסומנת כ״אין חדשות״.', 'No matching news. Provider failures appear under Scanner status and are not labeled “no news”.')} />}
    </div>}

    {tab === 'status' && <div className="scanner-section">
      <details className="scanner-rejected"><summary>{text('מועמדים שנדחו', 'Rejected candidates')} ({data?.rejected?.length || 0})</summary>
        {(data?.rejected || []).map(item => <p key={item.id}><b>{item.ticker}</b> · {item.reason || text('לא עבר את כל התנאים', 'Did not pass all conditions')} · {stamp(item.created_at)}</p>)}
      </details>
      <h2>{text('מצב רכיבי הסורק', 'Scanner component health')}</h2>
      <h3>{text('אימות מחזור עסקה חי', 'Live lifecycle verification')}</h3>
      <p>{text('עסקאות חדשות בלבד; Legacy ו־Shadow אינם הוכחה למחזור חי חדש. אפס פירושו שטרם נצפה האירוע.', 'Native trades only; legacy and shadow are not proof of a new live lifecycle. Zero means not yet observed.')}</p>
      <div className="scanner-stage-grid">{Object.entries(data?.lifecycle_verification?.stages || {}).map(([key, value]) => <Stat key={key} label={he ? ({signal: 'סיגנל', entry: 'כניסה', tp: 'מימוש יעד', stop: 'יציאה בסטופ', closed: 'סיום עסקה', news_review: 'בדיקת חדשות', six_hour_review: 'סקירה לאחר 6 שעות', telegram_buy_signal: 'Telegram אות קנייה', telegram_sell_signal: 'Telegram אות מכירה', telegram_entry: 'התראת כניסה', telegram_exit: 'התראת יציאה'} as Record<string, string>)[key] || key : key.replace(/_/g, ' ')} value={String(value)} />)}</div>
      <p>{text('התאמת כמויות ומזומן', 'Quantity and cash reconciliation')}: {data?.lifecycle_verification?.accounting_ok ? text('תקינה', 'OK') : text('דורשת בדיקה', 'Needs attention')} · {text('אימות חי מלא', 'Full live verification')}: {data?.lifecycle_verification?.live_e2e_complete ? text('הושלם', 'Complete') : text('ממתין לאירועים אמיתיים', 'Awaiting real events')}</p>
      <div className="scanner-status-grid">{(data?.services || []).map(service => <article key={service.component} className={`scanner-status ${service.status}`}><h3>{serviceName(service.component)}</h3><strong>{serviceStatus(service.status)}</strong><p>{serviceDetail(service)}</p><small>{text('הצלחה אחרונה', 'Last success')}: {stamp(service.last_success_at)}</small></article>)}</div>
      <h3>{text('מצב ספקי החדשות', 'News provider status')}</h3>
      <div className="scanner-status-grid">{(data?.news_providers || []).map(provider => <article key={provider.provider} className={`scanner-status ${provider.status}`}><h3>{providerName(provider.provider)}</h3><strong>{providerStatus(provider.status)}</strong><p>{providerCoverage(provider)}</p><small>{providerCounters(provider)}<br/>{text('הצלחה אחרונה', 'Last success')}: {stamp(provider.last_success_at)}<br/>{text('בדיקה הבאה', 'Next check')}: {stamp(provider.next_check_at)}</small></article>)}</div>
      <h3>{text('תפעול וטריות', 'Operations and freshness')}</h3>
      <p>{text('סריקה אחרונה', 'Last scan')}: {activity.last_scan_at ? stamp(activity.last_scan_at * 1000) : '—'} · {text('סריקה הבאה', 'Next scan')}: {activity.next_scan_at ? stamp(activity.next_scan_at * 1000) : '—'}</p>
      <p>{text('ספק מחירים', 'Price provider')}: Yahoo Finance/yfinance · {text('המחירים עשויים להיות מושהים. סיגנל לא מתפרסם ללא מחיר תוך־יומי בן פחות מ־12 דקות.', 'Quotes may be delayed. No signal is published without an intraday quote fresher than 12 minutes.')}</p>
      <p>{text('רענון מחיר לתצוגה', 'Display quote refresh')}: {quoteInfo?.refresh_seconds || data?.settings?.quote_refresh_seconds || 30}s · {text('הדפדפן בודק את מטמון השרת כל 10 שניות. זהו מחיר דקה אחרון מספק חינמי, לא פיד בורסה מובטח בזמן אמת; מחיר אחרון נשמר גם בתקלה או כשהשוק סגור.', 'The browser checks the server cache every 10 seconds. This is the latest 1-minute quote from a free provider, not guaranteed exchange real-time; the last value is retained on failure or while the market is closed.')}</p>
      <p>{text('מטמון היסטורי', 'History cache')}: {activity.history_cache?.status || '—'} · {text('גיל', 'age')} {Math.round((activity.history_cache?.age_seconds || 0) / 3600)}h</p>
      <p>{text('המשתמש והתיק הראשיים', 'Primary user and portfolio')}: <b>{primaryName}</b> · {text('המשתמש היחיד שמוצג בדשבורד', 'the only user exposed in the dashboard')}</p>
      <p>{text('מפתח טכני יציב', 'Stable technical key')}: <code>{data?.primary_user?.key || data?.scanner_name}</code> · Ollama: <code>{activity.model || '—'}</code></p>
    </div>}
  </section>
}

function Empty({ text }: { text: string }) { return <div className="scanner-empty">{text}</div> }
function Stat({ label, value }: { label: string, value: string }) { return <div className="scanner-stat"><span>{label}</span><strong>{value}</strong></div> }

function SignalCard({ signal, he }: { signal: Record<string, any>, he: boolean }) {
  const news = Array.isArray(signal.news_json) ? signal.news_json : []
  const basis = signal.confidence_basis || {}
  const plan = signal.technical_json?.target_plan
  const movementEntry = signal.actual_entry ?? signal.planned_entry
  const [opened, setOpened] = useState(false)
  const activeTargets = [1, 2, 3].filter(i => Number(signal[`operational_tp${i}_pct`] ?? signal[`tp${i}_pct`] ?? 0) > 0)
  const statusLabels: Record<string, string> = he ? {ENTERED:'כניסה בוצעה', ACTIVE:'ממתין לכניסה', PENDING_ENTRY:'ממתין לכניסה', EXPIRED:'פג תוקף', CLOSED:'נסגר', RISK_BLOCKED:'נחסם בסיכון', DUPLICATE_BLOCKED:'כפילות נחסמה', BEARISH_ONLY:'איתות דובי', COMPLETED:'הושלם'} : {ENTERED:'Entry filled', ACTIVE:'Awaiting entry', PENDING_ENTRY:'Awaiting entry', EXPIRED:'Expired', CLOSED:'Closed', RISK_BLOCKED:'Risk blocked', DUPLICATE_BLOCKED:'Duplicate blocked', BEARISH_ONLY:'Bearish signal', COMPLETED:'Completed'}
  const horizon = he ? String(signal.time_horizon || '—').replace(/weeks?/gi, 'שבועות').replace(/days?/gi, 'ימים').replace(/hours?/gi, 'שעות') : signal.time_horizon
  const stamp = (value: any) => value ? new Date(value).toLocaleString(he ? 'he-IL' : 'en-GB') : '—'
  return <details className="scanner-signal-card signal-focused" id={`signal-${signal.id}`} onToggle={event => setOpened(event.currentTarget.open)}>
    <summary className="scanner-signal-summary">
      <span className="scanner-signal-identity"><b className="scanner-ticker" dir="ltr">{signal.ticker}</b><span>{signal.company}</span></span>
      <span className="scanner-signal-summary-meta"><span className={`scanner-action ${String(signal.action).toLowerCase()}`}>{he ? ({BUY:'קנייה',SELL:'מכירה',HOLD:'המתנה'} as Record<string,string>)[signal.action] || signal.action : signal.action}</span><span className="scanner-signal-chevron" aria-hidden="true">⌄</span></span>
    </summary>
    <div className="scanner-signal-body">
      <em className="signal-status-label">{statusLabels[signal.status] || signal.status}</em>
      <span className="signal-summary-levels">
        <span><small>{he ? 'מחיר אחרון' : 'Last price'}{signal.price_stale ? (he ? ' · ישן' : ' · stale') : ''}</small><b dir="ltr">{fmtPrice(signal.current_price)}</b></span>
        <span><small>{he ? 'כניסה' : 'Entry'}</small><b dir="ltr">{fmtPrice(movementEntry)}</b></span>
        <span><small>{he ? 'יעד פעיל' : 'Active target'}</small><b dir="ltr">{activeTargets.length ? fmtPrice(signal[`tp${activeTargets[0]}`]) : '—'}</b></span>
        <span><small>{he ? 'סטופ' : 'Stop'}</small><b dir="ltr">{fmtPrice(signal.current_stop)}</b></span>
      </span>
    <p className="signal-price-time">{he ? 'זמן המחיר' : 'Quote time'}: {stamp(signal.price_as_of)} · {he ? 'נתוני Yahoo עשויים להיות מושהים' : 'Yahoo data may be delayed'}</p>
    {opened && <LevelChart record={signal} kind="signal" he={he} initiallyOpen />}
    <h3>{he ? 'תוכנית המימוש הפעילה' : 'Active exit plan'}</h3>
    <TargetRows record={signal} entry={movementEntry} strategy={signal.operational_strategy || 'single'} he={he} indices={activeTargets} />
    <details className="signal-secondary"><summary>{he ? 'יעדי השוואה — Shadow' : 'Comparison targets — Shadow'}</summary>
      <TargetRows record={signal} entry={movementEntry} strategy={signal.operational_strategy || 'single'} he={he} indices={[1,2,3].filter(i => !activeTargets.includes(i))} />
    </details>
    <details className="signal-secondary"><summary>{he ? 'פרטי כניסה וחישוב יעדים' : 'Entry and target calculation'}</summary>
    <div className="scanner-levels"><span>{he ? 'כניסה מתוכננת' : 'Planned entry'}<b>{fmtPrice(signal.planned_entry)}</b></span><span>{he ? 'כניסה בפועל' : 'Actual entry'}<b>{fmtPrice(signal.actual_entry)}</b></span><span>{he ? 'סטופ מקורי' : 'Original stop'}<b>{fmtPrice(signal.original_stop)}</b></span><span>{he ? 'סטופ נוכחי' : 'Current stop'}<b>{fmtPrice(signal.current_stop)}</b></span></div>
    <TargetPlanDetails plan={plan} he={he} />
    </details>
    <p><b>{he ? 'ציון איכות מודל לא־מכויל' : 'Uncalibrated model quality score'}:</b> {fmtPct(signal.confidence)} · {he ? 'תוכנית משוקללת' : 'Weighted plan'} {Number(signal.weighted_rr).toFixed(1)}R</p>
    <details className="signal-secondary"><summary>{he ? 'מקור הציון — אינו הסתברות להצלחה' : 'Score basis — not a probability of success'}</summary><dl>{Object.entries(basis).filter(([key,value]) => key !== 'label' && value != null && typeof value !== 'object').map(([key,value]) => <div key={key}><dt>{he ? ({model:'ציון המודל', calibrated:'מכויל', source:'מקור', technical_score:'ציון טכני', combined_rank_score:'דירוג משולב', news_sentiment:'סנטימנט חדשות', news_relevance:'רלוונטיות חדשות', model_confidence:'ציון המודל'} as Record<string,string>)[key] || key.replace(/_/g,' ') : key.replace(/_/g,' ')}</dt><dd>{typeof value === 'boolean' ? (value ? (he ? 'כן' : 'Yes') : (he ? 'לא' : 'No')) : String(value)}</dd></div>)}</dl></details>
    <details className="signal-secondary"><summary>{he ? 'הניתוח המלא וחדשות המקור' : 'Full analysis and source news'}</summary>
      <p>{(he && signal.reason_he) || signal.reason}</p>
      {!!news.length && <ul>{news.map((item: any, index: number) => <li key={`${item.url}-${index}`}><a href={item.url} target="_blank" rel="noreferrer">{(he && item.title_he) || item.title}</a> · {item.publisher} · {stamp(item.published_at)}</li>)}</ul>}
    </details>
      <footer>{he ? 'טווח זמן' : 'Horizon'}: {horizon}{signal.actual_entry == null && <> · {he ? 'כניסה עד' : 'Entry valid until'}: {stamp(signal.valid_until)}</>} · {he ? 'עודכן' : 'Updated'}: {stamp(signal.updated_at)}</footer>
    </div>
  </details>
}

function TradeCard({ trade, schedules, he }: { trade: Record<string, any>, schedules: Record<string, any>[], he: boolean }) {
  const schedule = schedules.find(item => item.ticker === trade.ticker)
  const plan = trade.settings?.target_plan
  const currentPrice = trade.current_price ?? trade.last_price
  const currentPriceAt = trade.price_as_of ?? trade.last_bar_at
  const stamp = (value: any) => value ? new Date(value).toLocaleString(he ? 'he-IL' : 'en-GB') : '—'
  return <article className="scanner-trade-card" id={`trade-${trade.id}`}><header><div><b>{trade.ticker}</b> · {trade.company}</div><span>{trade.status}</span></header>
    {!!trade.legacy_position_id && <p className="scanner-warning">{he ? 'Legacy — היסטוריה לא מאומתת; ניהול החל מ־' : 'Legacy — unverified history; managed from '}{stamp(trade.managed_from)}. {he ? 'עלויות כניסה היסטוריות אינן כלולות; לא נספר בסטטיסטיקה המאומתת.' : 'Historical entry costs excluded; not counted in verified statistics.'}</p>}
    <p>{he ? 'כניסה' : 'Entry'}: {fmtPrice(trade.entry_price)} · {he ? 'סטופ' : 'Stop'}: {fmtPrice(trade.current_stop)}</p>
    <p className="scanner-note">{trade.strategy === 'single'
      ? (he ? 'אסטרטגיה פעילה: יעד יחיד. אם TP2 יבוצע, כל הכמות שנותרה תיסגר. ‏TP1 ו־TP3 הם יעדי Shadow להשוואה בלבד ואינם מוכרים מניות.' : 'Active strategy: single target. If TP2 fills, the entire remaining quantity closes. TP1 and TP3 are Shadow comparison levels and sell no shares.')
      : (he ? 'אסטרטגיית Shadow מדורגת: מימוש חלקי ב־TP1/TP2 וסגירת היתרה ב־TP3.' : 'Staged Shadow strategy: partial exits at TP1/TP2 and final exit at TP3.')}</p>
    <TargetRows record={trade} entry={trade.entry_price} strategy={trade.strategy} he={he} />
    <p className={trade.price_stale ? 'scanner-warning' : 'scanner-note'}><b>{he ? (trade.price_stale ? 'מחיר אחרון ידוע — לא עדכני' : 'מחיר נוכחי אחרון') : (trade.price_stale ? 'Last known price — stale' : 'Latest current price')}: {fmtPrice(currentPrice)}</b><br/>{he ? 'זמן נתוני המחיר' : 'Price timestamp'}: {stamp(currentPriceAt)} · {trade.price_source || '—'}{trade.price_stale && <><br/>{he ? 'המחיר נשמר ומוצג, אך אינו מוצג כמחיר חי כאשר השוק סגור או שהנתון ישן.' : 'The stored price remains visible, but is not presented as live while the market is closed or the quote is old.'}</>}</p>
    <TargetPlanDetails plan={plan} he={he} />
    {trade.status === 'open' && <LevelChart record={trade} kind="trade" he={he} />}
    <p>{he ? 'חדשות — בדיקה אחרונה' : 'News — last check'}: {stamp(schedule?.last_success_at)} · {he ? 'הבאה' : 'next'}: {stamp(schedule?.next_due_at)} · {schedule?.status || '—'}</p>
    {schedule?.summary_he && <p className="scanner-ai-interpretation"><b>{he ? 'סקירת חדשות אחרונה' : 'Latest news review'}:</b> {schedule.summary_he}</p>}
    {!!trade.news?.length && <details><summary>{he ? 'היסטוריית הערכות חדשות' : 'News assessment history'}</summary>{trade.news.map((item: any) => <p key={item.id}><b>{stamp(item.published_at)}</b> · {item.impact}/{item.materiality} · {item.interpretation_he}<br/><a href={item.url} target="_blank" rel="noreferrer">{item.publisher}</a></p>)}</details>}
    <details><summary>{he ? 'אירועי עסקה' : 'Trade events'} ({trade.fills?.length || 0})</summary>{(trade.fills || []).map((fill: any) => <p key={fill.id}>{fill.fill_type}{fill.target_index ? ` TP${fill.target_index}` : ''} · {fmtPrice(fill.price)} · {stamp(fill.bar_at)}</p>)}</details>
  </article>
}

function TargetRows({ record, entry, strategy, he, indices = [1,2,3] }: { record: Record<string, any>, entry: any, strategy: string, he: boolean, indices?: number[] }) {
  return <div className="scanner-targets">{indices.map(index => {
    const allocation = Number(record[`operational_tp${index}_pct`] ?? record[`tp${index}_pct`] ?? 0)
    const rr = Number(record[`rr${index}`])
    const execution = allocation > 0
      ? strategy === 'single'
        ? (he ? 'יעד פעיל — סגירה מלאה' : 'Active target — full exit')
        : (he ? 'יעד פעיל — מימוש מדורג' : 'Active target — staged exit')
      : (he ? 'Shadow בלבד — אין מימוש בפועל' : 'Shadow only — no actual exit')
    return <span key={index}>TP{index}: <b>{fmtPrice(record[`tp${index}`])}</b> · {he ? 'תשואה מהכניסה' : 'Return from entry'} {fmtMove(entry, record[`tp${index}`])} · {execution}{Number.isFinite(rr) && <> · {rr.toFixed(1)}R</>}</span>
  })}</div>
}

function LevelChart({ record, kind, he, initiallyOpen = false }: { record: Record<string, any>, kind: 'signal' | 'trade', he: boolean, initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen)
  const [expanded, setExpanded] = useState(false)
  const isSignal = kind === 'signal'
  const version = encodeURIComponent([
    record.actual_entry ?? record.planned_entry ?? record.entry_price, record.current_stop,
    record.tp1, record.tp2, record.tp3, record.operational_strategy ?? record.strategy, record.updated_at ?? record.last_bar_at,
  ].join('|'))
  const src = `${API_ORIGIN}/api/scanner/${isSignal ? 'signals' : 'trades'}/${record.id}/chart?v=${version}`
  const description = he
    ? `גרף יומי של ${record.ticker} עם ${isSignal && record.actual_entry == null ? 'כניסה מתוכננת שטרם בוצעה' : 'כניסה בפועל'}, סטופ ויעדי TP1, TP2 ו־TP3`
    : `${record.ticker} daily chart with ${isSignal && record.actual_entry == null ? 'planned entry not yet filled' : 'actual entry'}, stop, TP1, TP2 and TP3 levels`
  useEffect(() => {
    if (!expanded) return
    const previousOverflow = document.body.style.overflow
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false)
    }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [expanded])
  return <details className="scanner-position-chart" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{he ? 'גרף כניסה, סטופ ויעדים' : 'Entry, stop and target chart'}</summary>
    {open && <>
      <button type="button" className="scanner-chart-preview" onClick={() => setExpanded(true)} aria-label={he ? `פתח גרף מוגדל של ${record.ticker}` : `Open enlarged ${record.ticker} chart`}>
        <img src={src} alt={description} />
        <span>{he ? 'לחץ על הגרף להגדלה' : 'Tap chart to enlarge'}</span>
      </button>
      <small>{he ? `${isSignal && record.actual_entry == null ? 'המשולש מסמן כניסה מתוכננת שטרם בוצעה. ' : ''}נרות יומיים מ־Yahoo Finance, שעשויים להיות מושהים. קו מלא הוא יעד פעיל; קו מקווקו הוא יעד Shadow להשוואה בלבד.` : `${isSignal && record.actual_entry == null ? 'The triangle marks a planned entry that has not filled. ' : ''}Daily Yahoo Finance candles may be delayed. A solid line is an active target; a dashed line is a Shadow comparison target only.`}</small>
      {expanded && <div className="scanner-chart-modal" role="presentation" onMouseDown={() => setExpanded(false)}>
        <section role="dialog" aria-modal="true" aria-label={description} className="scanner-chart-modal-content" onMouseDown={event => event.stopPropagation()}>
          <header><strong>{record.ticker} · {he ? (isSignal ? 'גרף תוכנית סיגנל' : 'גרף פוזיציית דמו') : (isSignal ? 'Signal plan chart' : 'Paper position chart')}</strong><button type="button" autoFocus onClick={() => setExpanded(false)} aria-label={he ? 'סגור גרף' : 'Close chart'}>×</button></header>
          <img src={src} alt={description} />
        </section>
      </div>}
    </>}
  </details>
}

function TargetPlanDetails({ plan, he }: { plan: Record<string, any> | undefined, he: boolean }) {
  if (!plan) return <details><summary>{he ? 'כיצד חושבו היעדים?' : 'How were targets calculated?'}</summary><p>{he ? 'תוכנית Legacy או תוכנית קודמת ללא ראיות מבנה שמורות.' : 'Legacy or earlier plan without stored structural evidence.'}</p></details>
  const objectives = Array.isArray(plan.objectives) ? plan.objectives : Array.isArray(plan.zones) ? plan.zones.map((zone: any) => ({ source: 'confirmed_daily_resistance', zone })) : []
  const revised = plan.method === 'daily_resistance_and_measured_move_v1'
  return <details><summary>{he ? 'כיצד חושבו היעדים?' : 'How were targets calculated?'}</summary>
    <p>{revised
      ? (he ? 'נבחרו יעדי גרף קדמיים: התנגדויות יומיות מאומתות קיבלו עדיפות; כאשר אין שלוש התנגדויות מעל המחיר, נוספו יעדי תנועה מדודה מטווח 20 ימי מסחר. יעד תנועה מדודה הוא השלכה מהגרף ולא התנגדות מוכחת או תחזית.' : 'Forward chart objectives: confirmed daily resistance was preferred; when fewer than three overhead levels exist, 20-session measured-move objectives fill the gaps. A measured move is a chart projection, not proven resistance or a forecast.')
      : (he ? 'רמות שיא/שפל יומיות מאומתות, מאוחדות לאזורים. היעד מוקם לפני האזור באמצעות מרווח ATR.' : 'Confirmed daily swing zones, clustered into price areas; the target is placed before the zone using an ATR buffer.')}</p>
    {plan.data_as_of && <p>{he ? 'נתוני גרף עד' : 'Chart data through'}: {plan.data_as_of} · ATR: {Number(plan.atr || 0).toFixed(2)}</p>}
    {objectives.map((item: any, index: number) => item.source === 'confirmed_daily_resistance'
      ? <p key={index}>TP{index + 1}: {he ? 'התנגדות מאומתת' : 'Confirmed resistance'} {fmtPrice((item.zone || item).low)}–{fmtPrice((item.zone || item).high)} · {he ? 'נגיעות' : 'Touches'}: {(item.zone || item).touches || item.touches || 1}</p>
      : <p key={index}>TP{index + 1}: {he ? 'תנועה מדודה' : 'Measured move'} · {Number(item.ratio || 0).toFixed(3)}× · {he ? 'טווח בסיס' : 'Base range'} {fmtPrice(item.range_low)}–{fmtPrice(item.range_high)}</p>)}
  </details>
}
