import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { API_ORIGIN, useLanguage } from './appShared'

type Dashboard = {
  paper_only: boolean
  scanner_name: string
  settings: Record<string, any>
  account: Record<string, any>
  activity: Record<string, any>
  signals: Record<string, any>[]
  trades: Record<string, any>[]
  news: Record<string, any>[]
  news_schedules: Record<string, any>[]
  services: Record<string, any>[]
  strategy_comparison: Record<string, any>[]
  rejected: Record<string, any>[]
  legacy_unverified_count: number
}

const fmtPrice = (value: any) => Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : '—'
const fmtPct = (value: any) => Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : '—'

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
  const [timeFilter, setTimeFilter] = useState('168')

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

  const text = (hebrew: string, english: string) => he ? hebrew : english
  const stamp = (value: any) => value ? new Date(value).toLocaleString(he ? 'he-IL' : 'en-GB') : '—'
  const activity = data?.activity || {}
  const activeSignals = (data?.signals || []).filter(item => !['CLOSED', 'EXPIRED'].includes(item.status))
  const historicSignals = (data?.signals || []).filter(item => ['CLOSED', 'EXPIRED'].includes(item.status))
  const filteredNews = useMemo(() => (data?.news || []).filter(item => {
    const tickerOk = !tickerFilter || String(item.ticker || '').toUpperCase().includes(tickerFilter.toUpperCase())
    const sentimentOk = sentimentFilter === 'all' || item.sentiment === sentimentFilter || item.impact === sentimentFilter
    const cutoff = timeFilter === 'all' ? 0 : Date.now() - Number(timeFilter) * 3600000
    const timeOk = !cutoff || new Date(item.published_at).getTime() >= cutoff
    return tickerOk && sentimentOk && timeOk
  }), [data, tickerFilter, sentimentFilter, timeFilter])

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

  if (loading && !data) return <div className="scanner-empty">{text('טוען את דשבורד הסורק…', 'Loading scanner dashboard…')}</div>

  return <section className="scanner-dashboard" dir={he ? 'rtl' : 'ltr'}>
    <header className="scanner-hero">
      <div>
        <p className="scanner-kicker">US STOCK SCANNER</p>
        <h1>{text('דשבורד סורק המניות', 'Stock scanner dashboard')}</h1>
        <p>{text('סריקה אוטומטית של S&P 500 ו־Nasdaq 100. אין צורך לבחור משתמש או להזין סימול.', 'Automatic S&P 500 + Nasdaq 100 scan. No user or ticker input required.')}</p>
      </div>
      <strong className="paper-only">{text('מסחר מדומה בלבד', 'PAPER TRADING ONLY')}</strong>
    </header>

    {error && <div className="scanner-inline-error">{text('נתוני הסורק אינם זמינים כרגע', 'Scanner data is temporarily unavailable')}: {error} <button onClick={() => void load()}>{text('בדיקה מחדש', 'Retry')}</button></div>}

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

    <nav className="scanner-tabs" aria-label={text('ניווט בדשבורד', 'Dashboard navigation')}>
      {tabs.map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => navigate(`/market?tab=${key}`)}>{label}</button>)}
    </nav>

    {tab === 'signals' && <div className="scanner-section">
      <h2>{text('סיגנלים פעילים', 'Active signals')} <small>{activeSignals.length}</small></h2>
      {!activeSignals.length && <Empty text={text('אין כרגע סיגנלים חזקים פעילים — זה מצב תקין והמסננים לא הוחלשו.', 'No strong active signals right now — this is normal and filters were not weakened.')} />}
      <div className="scanner-card-grid">{activeSignals.map(signal => <SignalCard key={signal.id} signal={signal} he={he} />)}</div>
      <h2>{text('היסטוריית סיגנלים', 'Signal history')} <small>{historicSignals.length}</small></h2>
      <div className="scanner-card-grid">{historicSignals.map(signal => <SignalCard key={signal.id} signal={signal} he={he} />)}</div>
      <details className="scanner-rejected"><summary>{text('מועמדים שנדחו', 'Rejected candidates')} ({data?.rejected?.length || 0})</summary>
        {(data?.rejected || []).map(item => <p key={item.id}><b>{item.ticker}</b> · {item.reason || text('לא עבר את כל התנאים', 'Did not pass all conditions')} · {stamp(item.created_at)}</p>)}
      </details>
    </div>}

    {tab === 'trades' && <div className="scanner-section">
      <div className="scanner-account-grid">
        <Stat label={text('מזומן', 'Cash')} value={fmtPrice(data?.account?.cash)} />
        <Stat label={text('חשיפה פתוחה', 'Open exposure')} value={fmtPrice(data?.account?.open_exposure)} />
        <Stat label={text('רווח ממומש', 'Realized P/L')} value={fmtPrice(data?.account?.realized_pnl)} />
        <Stat label={text('רווח לא ממומש', 'Unrealized P/L')} value={fmtPrice(data?.account?.unrealized_pnl)} />
      </div>
      <p className="scanner-note">{text('יצירת סיגנל אינה ביצוע. הוראת LIMIT נכנסת רק לאחר שנר מחיר מאומת נוגע במחיר הכניסה.', 'A signal is not a fill. A LIMIT entry fills only after a verified price bar reaches entry.')}</p>
      {(data?.trades || []).filter(trade => !trade.is_shadow).map(trade => <TradeCard key={trade.id} trade={trade} schedules={data?.news_schedules || []} he={he} />)}
      {!(data?.trades || []).some(trade => !trade.is_shadow) && <Empty text={text('אין עדיין עסקאות דמו מאומתות.', 'No verified demo trades yet.')} />}
      {!!data?.legacy_unverified_count && <p className="scanner-warning">{text(`${data.legacy_unverified_count} רשומות ישנות נשמרו בנפרד ואינן נכללות בסטטיסטיקה המאומתת.`, `${data.legacy_unverified_count} legacy records are preserved separately and excluded from verified statistics.`)}</p>}
    </div>}

    {tab === 'results' && <div className="scanner-section">
      <h2>{text('השוואת אסטרטגיות יציאה', 'Exit strategy comparison')}</h2>
      <p className="scanner-note">{text(`האסטרטגיה הפעילה לעסקאות חדשות: ${data?.settings?.active_strategy === 'staged' ? 'מימוש מדורג' : 'יעד יחיד'}. אסטרטגיית Shadow אינה משפיעה על המזומן או על Telegram.`, `Active for new trades: ${data?.settings?.active_strategy || 'single'}. Shadow results never affect cash or Telegram.`)}</p>
      {token && <div className="scanner-strategy-controls"><button disabled={data?.settings?.active_strategy === 'single'} onClick={() => void changeStrategy('single')}>{text('הפעל יעד יחיד לעסקאות חדשות', 'Use single target for new trades')}</button><button disabled={data?.settings?.active_strategy === 'staged'} onClick={() => void changeStrategy('staged')}>{text('הפעל מימוש מדורג לעסקאות חדשות', 'Use staged exits for new trades')}</button></div>}
      <div className="scanner-table-wrap"><table className="scanner-table"><thead><tr>{[text('אסטרטגיה', 'Strategy'), text('עסקאות', 'Trades'), text('רווח נטו מסומן', 'Marked net'), text('תוחלת R', 'Expectancy R'), text('הצלחה', 'Win rate'), text('Drawdown', 'Drawdown'), 'TP1', 'TP2', 'TP3'].map(value => <th key={value}>{value}</th>)}</tr></thead>
        <tbody>{(data?.strategy_comparison || []).map(row => <tr key={row.strategy}><td>{row.strategy}</td><td>{row.trades} ({row.closed_trades} {text('סגורות', 'closed')})</td><td>{fmtPrice(row.marked_net)}</td><td>{Number(row.expectancy_r || 0).toFixed(2)}R</td><td>{fmtPct(row.win_rate)}</td><td>{fmtPrice(row.current_drawdown)}</td><td>{fmtPct(row.tp1_rate)}</td><td>{fmtPct(row.tp2_rate)}</td><td>{fmtPct(row.tp3_rate)}</td></tr>)}</tbody></table></div>
      {(data?.strategy_comparison || []).some(row => row.sample_warning) && <p className="scanner-warning">{text('המדגם קטן מ־30 עסקאות סגורות; אין בסיס להכריז על יתרון לאחת האסטרטגיות.', 'The sample has fewer than 30 closed trades; no strategy advantage can be claimed.')}</p>}
    </div>}

    {tab === 'news' && <div className="scanner-section">
      <h2>{text('חדשות — מהחדש לישן', 'News — newest first')}</h2>
      <div className="scanner-filters"><input value={tickerFilter} onChange={event => setTickerFilter(event.target.value)} placeholder={text('סינון לפי סימול', 'Filter ticker')} />
        <select value={sentimentFilter} onChange={event => setSentimentFilter(event.target.value)}><option value="all">{text('כל הסנטימנטים', 'All sentiment')}</option><option value="positive">{text('חיובי', 'Positive')}</option><option value="negative">{text('שלילי', 'Negative')}</option><option value="mixed">{text('מעורב', 'Mixed')}</option><option value="neutral">{text('ניטרלי', 'Neutral')}</option></select>
        <select value={timeFilter} onChange={event => setTimeFilter(event.target.value)}><option value="24">{text('24 שעות', '24 hours')}</option><option value="168">{text('7 ימים', '7 days')}</option><option value="all">{text('כל הזמנים', 'All time')}</option></select></div>
      <p className="scanner-note">{text(`הכיסוי בפועל כולל חדשות למועמדי הרשימה הקצרה ולעסקאות פתוחות; אינו פיד מלא לכל ${activity.universe_count || 0} המניות.`, `Actual coverage includes shortlisted candidates and open positions; it is not a complete feed for all ${activity.universe_count || 0} stocks.`)}</p>
      {(['market', 'universe', 'open_position'] as const).map(scope => {
        const rows = filteredNews.filter(item => item.scope === scope)
        if (!rows.length) return null
        const label = scope === 'market' ? text('חדשות שוק רחבות', 'Broad market news') : scope === 'open_position' ? text('חדשות לעסקאות פתוחות', 'Open-position news') : text('חדשות מניות ביקום הסריקה', 'Scanner-universe news')
        return <div key={scope}><h3>{label}</h3>{rows.map(item => <article className="scanner-news-card" key={item.id}><div>{item.ticker && <b>{item.ticker}</b>}</div><h3>{item.summary_he && he ? item.summary_he : item.title}</h3><p>{item.interpretation_he || ''}</p><footer>{item.publisher} · {stamp(item.published_at)} · {item.sentiment || item.impact || text('לא נותח', 'Not analyzed')} · <a href={item.url} target="_blank" rel="noreferrer">{text('למקור', 'Source')}</a>{item.signal_id && <> · <a href={`/market?tab=signals#signal-${item.signal_id}`}>{text('לסיגנל', 'Signal')}</a></>}{item.trade_ids?.[0] && <> · <a href={`/market?tab=trades#trade-${item.trade_ids[0]}`}>{text('לעסקה', 'Trade')}</a></>}</footer></article>)}</div>
      })}
      {!filteredNews.length && <Empty text={text('אין חדשות תואמות. תקלה בספק תוצג בלשונית מצב הסורק ואינה מסומנת כ״אין חדשות״.', 'No matching news. Provider failures appear under Scanner status and are not labeled “no news”.')} />}
    </div>}

    {tab === 'status' && <div className="scanner-section">
      <h2>{text('מצב רכיבי הסורק', 'Scanner component health')}</h2>
      <div className="scanner-status-grid">{(data?.services || []).map(service => <article key={service.component} className={`scanner-status ${service.status}`}><h3>{service.component}</h3><strong>{service.status}</strong><p>{service.detail || '—'}</p><small>{text('הצלחה אחרונה', 'Last success')}: {stamp(service.last_success_at)}</small></article>)}</div>
      <h3>{text('תפעול וטריות', 'Operations and freshness')}</h3>
      <p>{text('סריקה אחרונה', 'Last scan')}: {activity.last_scan_at ? stamp(activity.last_scan_at * 1000) : '—'} · {text('סריקה הבאה', 'Next scan')}: {activity.next_scan_at ? stamp(activity.next_scan_at * 1000) : '—'}</p>
      <p>{text('ספק מחירים', 'Price provider')}: Yahoo Finance/yfinance · {text('המחירים עשויים להיות מושהים. סיגנל לא מתפרסם ללא מחיר תוך־יומי בן פחות מ־12 דקות.', 'Quotes may be delayed. No signal is published without an intraday quote fresher than 12 minutes.')}</p>
      <p>{text('מטמון היסטורי', 'History cache')}: {activity.history_cache?.status || '—'} · {text('גיל', 'age')} {Math.round((activity.history_cache?.age_seconds || 0) / 3600)}h</p>
      <p>{text('מזהה סורק יציב', 'Stable scanner identity')}: <code>{data?.scanner_name}</code> · Ollama: <code>{activity.model || '—'}</code></p>
    </div>}
  </section>
}

function Empty({ text }: { text: string }) { return <div className="scanner-empty">{text}</div> }
function Stat({ label, value }: { label: string, value: string }) { return <div className="scanner-stat"><span>{label}</span><strong>{value}</strong></div> }

function SignalCard({ signal, he }: { signal: Record<string, any>, he: boolean }) {
  const news = Array.isArray(signal.news_json) ? signal.news_json : []
  const basis = signal.confidence_basis || {}
  const stamp = (value: any) => value ? new Date(value).toLocaleString(he ? 'he-IL' : 'en-GB') : '—'
  return <article className="scanner-signal-card" id={`signal-${signal.id}`}>
    <header><div><b className="scanner-ticker">{signal.ticker}</b><span>{signal.company}</span></div><span className={`scanner-action ${String(signal.action).toLowerCase()}`}>{signal.action}</span></header>
    <div className="scanner-levels"><span>{he ? 'כניסה מתוכננת' : 'Planned entry'}<b>{fmtPrice(signal.planned_entry)}</b></span><span>{he ? 'כניסה בפועל' : 'Actual entry'}<b>{fmtPrice(signal.actual_entry)}</b></span><span>{he ? 'סטופ מקורי' : 'Original stop'}<b>{fmtPrice(signal.original_stop)}</b></span><span>{he ? 'סטופ נוכחי' : 'Current stop'}<b>{fmtPrice(signal.current_stop)}</b></span></div>
    <div className="scanner-targets">{[1, 2, 3].map(index => <span key={index}>TP{index}: <b>{fmtPrice(signal[`tp${index}`])}</b> · {fmtPct(signal[`tp${index}_pct`])} · {Number(signal[`rr${index}`]).toFixed(1)}R</span>)}</div>
    <p><b>{he ? 'ציון איכות מודל לא־מכויל' : 'Uncalibrated model quality score'}:</b> {fmtPct(signal.confidence)} · {he ? 'תוכנית משוקללת' : 'Weighted plan'} {Number(signal.weighted_rr).toFixed(1)}R</p>
    <details><summary>{he ? 'פירוט מקור הציון' : 'Score basis'}</summary><pre>{JSON.stringify(basis, null, 2)}</pre></details>
    <p><b>{he ? 'סיבה' : 'Reason'}:</b> {(he && signal.reason_he) || signal.reason}</p>
    {!!news.length && <ul>{news.map((item: any, index: number) => <li key={`${item.url}-${index}`}><a href={item.url} target="_blank" rel="noreferrer">{(he && item.title_he) || item.title}</a> · {item.publisher} · {stamp(item.published_at)}</li>)}</ul>}
    <footer>{signal.status} · {he ? 'אופק' : 'Horizon'}: {signal.time_horizon} · {he ? 'בתוקף עד' : 'Valid until'}: {stamp(signal.valid_until)} · {he ? 'עודכן' : 'Updated'}: {stamp(signal.updated_at)}</footer>
  </article>
}

function TradeCard({ trade, schedules, he }: { trade: Record<string, any>, schedules: Record<string, any>[], he: boolean }) {
  const schedule = schedules.find(item => item.ticker === trade.ticker)
  const stamp = (value: any) => value ? new Date(value).toLocaleString(he ? 'he-IL' : 'en-GB') : '—'
  return <article className="scanner-trade-card" id={`trade-${trade.id}`}><header><div><b>{trade.ticker}</b> · {trade.company}</div><span>{trade.status}</span></header>
    <p>{he ? 'אסטרטגיה' : 'Strategy'}: {trade.strategy} · {he ? 'כמות מקורית' : 'Original qty'}: {Number(trade.original_quantity).toFixed(6)} · {he ? 'נותרה' : 'Remaining'}: {Number(trade.remaining_quantity).toFixed(6)}</p>
    <p>{he ? 'כניסה' : 'Entry'}: {fmtPrice(trade.entry_price)} · R: {fmtPrice(trade.original_r)} · {he ? 'סטופ' : 'Stop'}: {fmtPrice(trade.current_stop)}</p>
    <p>{he ? 'ממומש נטו לפני סגירה מלאה' : 'Realized before final close'}: {fmtPrice(Number(trade.realized_pnl) - Number(trade.fees))} · {he ? 'לא ממומש' : 'Unrealized'}: {fmtPrice(trade.unrealized_pnl)}</p>
    <p>{he ? 'חדשות — בדיקה אחרונה' : 'News — last check'}: {stamp(schedule?.last_success_at)} · {he ? 'הבאה' : 'next'}: {stamp(schedule?.next_due_at)} · {schedule?.status || '—'}</p>
    {!!trade.news?.length && <details><summary>{he ? 'היסטוריית הערכות חדשות' : 'News assessment history'}</summary>{trade.news.map((item: any) => <p key={item.id}><b>{stamp(item.published_at)}</b> · {item.impact}/{item.materiality} · {item.interpretation_he}<br/><a href={item.url} target="_blank" rel="noreferrer">{item.publisher}</a></p>)}</details>}
    <details><summary>{he ? 'ביצועים' : 'Fills'} ({trade.fills?.length || 0})</summary>{(trade.fills || []).map((fill: any) => <p key={fill.id}>{fill.fill_type}{fill.target_index ? ` TP${fill.target_index}` : ''} · {Number(fill.quantity).toFixed(6)} @ {fmtPrice(fill.price)} · {stamp(fill.bar_at)}</p>)}</details>
  </article>
}
