import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { TopbarControls } from './appChrome'
import { installMiniAppBackButton, preserveMiniApp } from './telegramMiniApp'
import { LABELS, STATE_LABELS, STATIONS, type ActivityItem, type ActivityUpdate, type Row, type Station } from './systemActivityModel'
import './miniAppActivity.css'

type Sheet = { kind: 'station'; station: Station } | { kind: 'stock' | 'journey'; id: string } | { kind: 'info' | 'filters' }
type Props = {
  he: boolean; items: ActivityItem[]; allItems: ActivityItem[]; changed: Set<string>; updates: ActivityUpdate[]
  research: Row | null; dashboard: Row | null; available: boolean; connection: string; error: string
  hours: number; setHours: (hours: number) => void; ticker: string; setTicker: (ticker: string) => void
  followed: string[]; follow: (ticker: string) => void; onlyFollowed: boolean; setOnlyFollowed: (value: boolean) => void
  renderFocus: (item: ActivityItem, close: () => void, details: () => void) => ReactNode
  renderJourney: (item: ActivityItem, close: () => void) => ReactNode
}
const names = (pair: [string, string], he: boolean) => pair[he ? 0 : 1]
const time = (value: unknown, he: boolean) => value ? new Date(String(value)).toLocaleString(he ? 'he-IL' : 'en-GB') : '—'

/** A display-only shell over the same retained evidence as the full website. */
export function MiniAppActivity(p: Props) {
  const { he, items, allItems, research, dashboard, available, changed } = p
  const t = (a: string, b: string) => he ? a : b
  const location = useLocation(), navigate = useNavigate()
  const [view, setView] = useState<'map' | 'stocks' | 'more'>('map')
  const [stack, setStack] = useState<Sheet[]>([])
  const sheet = stack.at(-1)
  const base = useRef<HTMLDivElement>(null), panel = useRef<HTMLDivElement>(null)
  const origin = useRef<HTMLElement | null>(null)
  const titleId = useId()
  const open = (next: Sheet) => {
    if (!stack.length) origin.current = document.activeElement as HTMLElement
    setStack(s => [...s, next])
  }
  const back = () => { if (stack.length) setStack(s => s.slice(0, -1)); else setView('map') }
  const close = () => setStack([])
  useEffect(() => {
    if (!stack.length && view === 'map') return
    return installMiniAppBackButton(back)
  }, [stack.length, view])
  useEffect(() => {
    if (!sheet || !panel.current) { origin.current?.focus({ preventScroll: true }); return }
    const node = panel.current
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    base.current?.setAttribute('inert', '')
    node.focus({ preventScroll: true })
    const keys = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); back(); return }
      if (e.key !== 'Tab') return
      const controls = [...node.querySelectorAll<HTMLElement>('button, input, select, a[href], [tabindex="0"]')].filter(el => el.getClientRects().length && !el.hasAttribute('disabled'))
      const first = controls[0], last = controls.at(-1)
      if (!first) { e.preventDefault(); return }
      if (e.shiftKey && (document.activeElement === first || document.activeElement === node)) { e.preventDefault(); last?.focus() }
      else if (!e.shiftKey && (document.activeElement === last || document.activeElement === node)) { e.preventDefault(); first.focus() }
    }
    node.addEventListener('keydown', keys)
    return () => { node.removeEventListener('keydown', keys); document.body.style.overflow = previousOverflow; base.current?.removeAttribute('inert') }
  }, [sheet])
  const known = !!research && !!dashboard
  const selected = sheet && 'id' in sheet ? allItems.find(i => i.id === sheet.id) : undefined
  const title = sheet?.kind === 'station' ? names(LABELS[sheet.station], he) : selected ? selected.ticker : sheet?.kind === 'filters' ? t('חיפוש וסינון', 'Search and filters') : t('מה רואים כאן?', 'About this view')
  const state = p.error ? t('העדכון מתעכב', 'Refresh delayed') : !known ? t('טוען נתונים…', 'Loading data…') : !available ? t('מידע שמור', 'Retained data') : t('מחובר', 'Connected')
  const list = (rows: ActivityItem[]) => rows.length ? <ul className="mini-stock-list">{rows.map(item => <li key={item.id}>
    <button className="mini-stock-row" type="button" onClick={() => open({ kind: 'stock', id: item.id })} aria-label={`${t('פרטי מניה', 'Stock details')}: ${item.ticker}`}>
      <span><strong><bdi>{item.ticker}</bdi></strong><small><bdi>{item.company || t('שם חברה לא נשמר', 'Company not retained')}</bdi></small></span>
      <span className="mini-stock-state"><span>{names(STATE_LABELS[item.state], he)}</span><small>{names(LABELS[item.station], he)}</small></span>
    </button></li>)}</ul> : <p className="mini-empty">{known ? t('אין רשומות תואמות במדגם הזה.', 'No matching records in this sample.') : t('הנתונים עדיין נטענים. אין להסיק שאין פעילות.', 'Data is loading; this does not indicate inactivity.')}</p>

  return <section className="mini-workspace" dir={he ? 'rtl' : 'ltr'} aria-label={t('המערכת בפעולה', 'System in motion')}>
    <div ref={base} className="mini-base">
      <header className="mini-header"><div><strong><bdi>AI TRADER</bdi></strong><small>{t('תצוגת מערכת · מסחר מדומה', 'System view · paper trading')}</small></div>
        <button type="button" className={`mini-connection ${available ? 'is-connected' : ''}`} onClick={() => open({ kind: 'info' })} aria-label={t('מצב החיבור והסבר', 'Connection status and explanation')}><span />{state}<span aria-hidden="true">ⓘ</span></button>
      </header>
      <div className="mini-map-view" hidden={view !== 'map'}>
        <div className="mini-map-heading"><h1>{t('הכורים', 'Reactors')}</h1><button type="button" onClick={() => open({ kind: 'filters' })}>{p.ticker || p.onlyFollowed ? t('סינון פעיל', 'Filtered') : t('סינון', 'Filter')} <span aria-hidden="true">⌕</span></button></div>
        <MobileReactors he={he} items={items} changed={changed} known={known} openStation={s => open({ kind: 'station', station: s })} openStock={id => open({ kind: 'stock', id })} />
        <div className="mini-map-footnote"><span>{t('לחצו על קובייה לכל המניות והפרטים', 'Tap a card for all stocks and details')}</span><span>{dashboard?.market?.is_open === false ? t('השוק סגור', 'Market closed') : dashboard?.market?.is_open === true ? t('השוק פתוח', 'Market open') : t('מצב שוק לא זמין', 'Market status unavailable')}</span></div>
      </div>
      {view === 'stocks' && <div className="mini-page"><h1>{t('מניות במדגם', 'Sampled stocks')}</h1><label className="mini-search">{t('חיפוש', 'Search')}<input type="search" placeholder={t('סימול או חברה', 'Ticker or company')} value={p.ticker} onChange={e => p.setTicker(e.target.value)} /></label>{list(items)}</div>}
      {view === 'more' && <div className="mini-page"><h1>{t('עוד במערכת', 'More')}</h1><div className="mini-more-links">
        {([['signals','סיגנלים ופוזיציות','Signals and positions'],['research','מחקר סיגנלים','Signal research'],['results','תוצאות','Results'],['news','חדשות','News'],['status','מצב הסורק','Scanner status']] as const).map(([tab, a, b]) => <button key={tab} type="button" onClick={() => navigate(preserveMiniApp(`/market?tab=${tab}`, location.search, location.hash))}>{t(a,b)}<span aria-hidden="true">‹</span></button>)}
        <button type="button" onClick={() => open({ kind: 'info' })}>{t('איך לקרוא את התצוגה?', 'How to read this view')}<span aria-hidden="true">ⓘ</span></button>
      </div><TopbarControls /><p className="mini-small-note">{t('צפייה בלבד. אין שינוי בסורק או במסחר.', 'Read-only. No scanner or trading changes.')}</p></div>}
      <nav className="mini-bottom-nav" aria-label={t('ניווט ראשי', 'Main navigation')}>
        {(['map','stocks','more'] as const).map((key,n) => <button type="button" key={key} aria-current={view === key ? 'page' : undefined} onClick={() => setView(key)}><span aria-hidden="true">{['◉','▥','•••'][n]}</span>{names(([['כורים','Reactors'],['מניות','Stocks'],['עוד','More']] as [string,string][])[n], he)}</button>)}
      </nav>
    </div>
    {sheet && <div className="mini-sheet-layer">
      <button type="button" className="mini-sheet-backdrop" onClick={close} aria-label={t('סגירת הפרטים', 'Close details')} tabIndex={-1} />
      <div className="mini-sheet" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={panel}>
        <header className="mini-sheet-header"><button type="button" onClick={back} aria-label={stack.length > 1 ? t('חזרה', 'Back') : t('סגירה', 'Close')}>{stack.length > 1 ? '↪' : '×'}</button><h2 id={titleId}><bdi>{title}</bdi></h2>{stack.length > 1 && <button type="button" onClick={close} aria-label={t('סגירת כל הפרטים', 'Close all details')}>×</button>}</header>
        <div className="mini-sheet-content">
          {!available && sheet.kind !== 'info' && <p className="mini-retained-note">{known ? t('מידע אחרון שנשמר — לא פעילות חדשה.', 'Last retained data, not new activity.') : t('ממתין לנתונים.', 'Waiting for data.')}</p>}
          {sheet.kind === 'station' && <><p className="mini-small-note">{t('רשומות לפי התחנה האחרונה שתועדה; לא הוכחה שכל השלבים עברו.', 'Records by latest retained station; not proof that all earlier stages passed.')}</p>{list(items.filter(i => i.station === sheet.station))}</>}
          {sheet.kind === 'stock' && selected && <>{p.renderFocus(selected, back, () => open({ kind: 'journey', id: selected.id }))}<button className="mini-follow" type="button" aria-pressed={p.followed.includes(selected.ticker)} onClick={() => p.follow(selected.ticker)}>{p.followed.includes(selected.ticker) ? '★' : '☆'} {t('מעקב בתצוגה בלבד', 'Visual follow only')}</button></>}
          {sheet.kind === 'journey' && selected && p.renderJourney(selected, back)}
          {(sheet.kind === 'stock' || sheet.kind === 'journey') && !selected && <p>{t('הרשומה כבר אינה במדגם. אין בכך הוכחה שהפוזיציה נסגרה.', 'Record left the sample; this does not prove closure.')}</p>}
          {sheet.kind === 'filters' && <div className="mini-filters"><label>{t('חיפוש מניה', 'Find a stock')}<input type="search" value={p.ticker} placeholder={t('סימול או חברה', 'Ticker or company')} onChange={e => p.setTicker(e.target.value)} /></label>
            <label>{t('חלון מחקר', 'Research window')}<select value={p.hours} onChange={e => p.setHours(Number(e.target.value))}>{[24,48,168].map(v => <option key={v} value={v}>{v}h</option>)}</select></label>
            <label className="mini-check"><input type="checkbox" checked={p.onlyFollowed} onChange={e => p.setOnlyFollowed(e.target.checked)} />{t('רק מניות במעקב בתצוגה', 'Visually followed only')}</label>
            <button type="button" onClick={() => { p.setTicker(''); p.setOnlyFollowed(false) }}>{t('ניקוי סינון', 'Clear filters')}</button><button className="mini-primary" type="button" onClick={close}>{t('הצגת התוצאות', 'Show results')}</button></div>}
          {sheet.kind === 'info' && <div className="mini-info"><p className="mini-info-status">{p.connection}</p><p>{t('מיקום המניה נקבע לפי התיעוד האחרון. הוא אינו מציג Worker שמטפל בה כרגע או אישור מעבר בתחנות קודמות.', 'Stocks are located by their latest retained evidence, not a worker processing them or proof of earlier approvals.')}</p>
            <p>{t('המספרים 1–8 והחצים מציגים את סדר התחנות. מספר הרשומות בכל תחנה מוצג בנפרד; החצים אינם הוכחה שמניה עברה את הבדיקות.', 'Steps 1–8 and arrows show station order. Record counts are separate; arrows do not prove a stock passed earlier gates.')}</p>
            <p>{t('המחקר מתעדכן כל דקה ומצב הסורק כל 30 שניות. המדגם אינו כל ה־Universe.', 'Research refreshes each minute and scanner status every 30 seconds. This sample is not the full universe.')}</p>
            <dl><div><dt>{t('תמונת מחקר', 'Research snapshot')}</dt><dd><bdi>{time(research?.generated_at,he)}</bdi></dd></div><div><dt>{t('מניות במדגם', 'Sampled stocks')}</dt><dd>{known ? new Set(allItems.map(i => i.ticker)).size : '—'}</dd></div></dl>
            {p.error && <details><summary>{t('פרטי שגיאת העדכון', 'Refresh error details')}</summary><p><bdi>{p.error}</bdi></p></details>}
            {research?.records_clipped || research?.clipped?.length ? <p>{t('המדגם מוגבל; היעדר מניה אינו הוכחה שאין פעילות.', 'The sample is capped. An absent stock does not prove inactivity.')}</p> : null}
          </div>}
        </div>
      </div>
    </div>}
  </section>
}

export function MobileReactors({he, items, changed, known, openStation}: {
  he:boolean; items:ActivityItem[]; changed:Set<string>; known:boolean
  openStation:(s:Station)=>void; openStock:(id:string)=>void
}) {
  const t=(a:string,b:string)=>he?a:b
  return <div className={`mini-reactors ${known?'':'is-loading'}`} aria-label={t('מפת הכורים', 'Reactor map')}>
    {STATIONS.map((s,n) => {
      const group = items.filter(i=>i.station===s)
      // Unique symbols are a preview; counts and the sheet retain every record.
      const symbols = [...new Set(group.map(i=>i.ticker).filter(Boolean))]
      const shown = symbols.slice(0,3)
      return <article data-reactor={s} key={s} className={`mini-reactor reactor-${s} ${group.some(i=>changed.has(i.id))?'has-update':''}`} style={{gridRow:Math.floor(n/2)+1,gridColumn:n%4===0||n%4===3?1:2}} data-flow={n===STATIONS.length-1?undefined:n%2===1?'down':n%4===0?'forward':'back'} data-arrow={n%2===1?'↓':(n%4===0)===he?'←':'→'}>
        <button type="button" className="mini-reactor-open" onClick={()=>openStation(s)} aria-label={`${t('שלב','Step')} ${n+1}: ${names(LABELS[s],he)} · ${known?`${group.length} ${t('רשומות','records')}`:t('טוען','Loading')}`}>
          <span className="mini-reactor-number" aria-hidden="true">{n+1}</span><span className="mini-reactor-name">{names(LABELS[s],he)}</span><span className="mini-reactor-count"><bdi>{known?group.length:'—'}</bdi> {t('רשומות','records')}</span>
          <span className="mini-reactor-stocks" aria-label={t('מניות בתחנה','Stocks in station')}>
            {shown.map(symbol=><bdi key={symbol} title={symbol}>{symbol}</bdi>)}
            {symbols.length>shown.length && <bdi className="mini-reactor-more" aria-label={t(`עוד ${symbols.length-shown.length} מניות`,`${symbols.length-shown.length} more stocks`)}>+{symbols.length-shown.length}</bdi>}
            {!shown.length && <span>{known?t('אין רשומות במדגם','No sampled records'):t('ממתין לנתונים','Waiting for data')}</span>}
          </span>
        </button>
      </article>
    })}
  </div>
}
