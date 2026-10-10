import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { TopbarControls } from './appChrome'
import { EvidenceSpider } from './SystemNetwork'
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
const ICONS: Record<Station, string> = { technical: '⌁', targets: '◎', evidence: '▤', ai: '✧', signal: '↗', order: '◷', position: '◉', exit: '✓' }

/** A display-only shell over the same retained evidence as the full website. */
export function MiniAppActivity(p: Props) {
  const { he, items, allItems, research, dashboard, available, changed } = p
  const t = (a: string, b: string) => he ? a : b
  const location = useLocation(), navigate = useNavigate()
  const [view, setView] = useState<'map' | 'stocks' | 'more'>('map')
  const [motionEnabled,setMotionEnabled] = useState(() => typeof window === 'undefined' || !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [motionOverride,setMotionOverride] = useState(false)
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
        <MobileReactors he={he} items={items} changed={changed} updates={p.updates} known={known} available={available} motionEnabled={motionEnabled} motionOverride={motionOverride} active={view === 'map' && !sheet} openStation={s => open({ kind: 'station', station: s })} openStock={id => open({ kind: 'stock', id })} />
        <div className="mini-map-footnote"><span>{t('לחצו על כור או מניה לפרטים', 'Tap a reactor or stock for details')}</span><span>{dashboard?.market?.is_open === false ? t('השוק סגור', 'Market closed') : dashboard?.market?.is_open === true ? t('השוק פתוח', 'Market open') : t('מצב שוק לא זמין', 'Market status unavailable')}</span></div>
      </div>
      {view === 'stocks' && <div className="mini-page"><h1>{t('מניות במדגם', 'Sampled stocks')}</h1><label className="mini-search">{t('חיפוש', 'Search')}<input type="search" placeholder={t('סימול או חברה', 'Ticker or company')} value={p.ticker} onChange={e => p.setTicker(e.target.value)} /></label>{list(items)}</div>}
      {view === 'more' && <div className="mini-page"><h1>{t('עוד במערכת', 'More')}</h1><div className="mini-more-links">
        {([['signals','סיגנלים ופוזיציות','Signals and positions'],['research','מחקר סיגנלים','Signal research'],['results','תוצאות','Results'],['news','חדשות','News'],['status','מצב הסורק','Scanner status']] as const).map(([tab, a, b]) => <button key={tab} type="button" onClick={() => navigate(preserveMiniApp(`/market?tab=${tab}`, location.search, location.hash))}>{t(a,b)}<span aria-hidden="true">‹</span></button>)}
        <button type="button" onClick={() => open({ kind: 'info' })}>{t('איך לקרוא את התצוגה?', 'How to read this view')}<span aria-hidden="true">ⓘ</span></button>
      </div><TopbarControls /><label className="mini-motion-option"><input type="checkbox" checked={motionEnabled} onChange={e=>{setMotionEnabled(e.target.checked);setMotionOverride(e.target.checked)}} />{t('תנועת המחשה', 'Illustrative motion')}</label><p className="mini-small-note">{t('צפייה בלבד. אין שינוי בסורק או במסחר.', 'Read-only. No scanner or trading changes.')}</p></div>}
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
            <p>{t('העכביש הוא המחשה: תנועה בין כורים מופיעה רק כשנקלט שינוי מתועד. תנועה קלה במקום היא אנימציה בלבד.', 'The spider illustrates observed updates between reactors. Gentle motion in place is decorative only.')}</p>
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

export function MobileReactors({he, items, changed, updates, known, available, motionEnabled=true, motionOverride=false, active=true, openStation, openStock}: {
  he:boolean; items:ActivityItem[]; changed:Set<string>; updates:ActivityUpdate[]; known:boolean; available:boolean
  openStation:(s:Station)=>void; openStock:(id:string)=>void; motionEnabled?:boolean; motionOverride?:boolean; active?:boolean
}) {
  const map = useRef<HTMLDivElement>(null), seen = useRef('')
  const sweepTimer = useRef<number | undefined>()
  const [visible,setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden')
  const [motion, setMotion] = useState(() => typeof window === 'undefined' || !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const motionAllowed=motionEnabled && (motion || motionOverride)
  const [size, setSize] = useState({w:380,h:510})
  const [sweep, setSweep] = useState({active:false,key:'',path:''})
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const change = () => setMotion(!query.matches)
    query.addEventListener('change',change)
    const resize = new ResizeObserver(() => { const r = map.current?.getBoundingClientRect(); if(r?.width && r.height) setSize({w:r.width,h:r.height}) })
    if(map.current) resize.observe(map.current)
    return () => { query.removeEventListener('change',change); resize.disconnect() }
  },[])
  useEffect(() => {
    const key = updates.map(u=>u.key).join('|')
    if(!key || key === seen.current) return
    seen.current = key // Hidden, unavailable and paused batches are discarded, never replayed.
    if(!available || !motionAllowed || !active || document.visibilityState === 'hidden') return
    const rect = map.current?.getBoundingClientRect()
    if(!rect) return
    const points = [...new Set(updates.filter(u => items.some(i=>i.id===u.item.id)).map(u=>u.item.station))].slice(0,4).map(s => {
      const r = map.current?.querySelector(`[data-reactor="${s}"]`)?.getBoundingClientRect()
      return r ? `${r.x-rect.x+r.width/2} ${r.y-rect.y+r.height/2}` : ''
    }).filter(Boolean)
    if(!points.length) return
    window.clearTimeout(sweepTimer.current)
    setSweep({active:true,key,path:`M ${rect.width/2} ${rect.height/2} L ${points.join(' L ')} L ${rect.width/2} ${rect.height/2}`})
    sweepTimer.current = window.setTimeout(()=>setSweep(v=>({...v,active:false})),3200)
  },[updates,items,available,motionAllowed,active])
  useEffect(()=>()=>window.clearTimeout(sweepTimer.current),[])
  useEffect(() => {
    const stop = () => { const shown=document.visibilityState !== 'hidden'; setVisible(shown); if(!shown) { window.clearTimeout(sweepTimer.current); setSweep(v=>({...v,active:false})) } }
    if(!available || !motionAllowed || !active) { window.clearTimeout(sweepTimer.current); setSweep(v=>({...v,active:false})) }
    document.addEventListener('visibilitychange',stop)
    return ()=>document.removeEventListener('visibilitychange',stop)
  },[available,motionAllowed,active])
  const t=(a:string,b:string)=>he?a:b
  return <div ref={map} className={`mini-reactors ${known?'':'is-loading'}`} aria-label={t('מפת הכורים', 'Reactor map')}>
    <svg className="mini-spider-overlay" viewBox={`0 0 ${size.w} ${size.h}`} aria-hidden="true"><path d={`M ${size.w/2} 18 L ${size.w/2} ${size.h-18}`} className="mini-spine" />
      <EvidenceSpider moving={sweep.active && available && motionAllowed && visible && active} idle={motionAllowed && visible && active} allowReducedMotion={motionOverride} path={sweep.path} point={{x:size.w/2,y:size.h/2}} compact batch={sweep.key} scale={.034} />
    </svg>
    {STATIONS.map((s,n) => {
      const group = items.filter(i=>i.station===s)
      return <article data-reactor={s} key={s} className={`mini-reactor reactor-${s} ${group.some(i=>changed.has(i.id))?'has-update':''}`}>
        <button type="button" className="mini-reactor-open" onClick={()=>openStation(s)} aria-label={`${names(LABELS[s],he)} · ${known?group.length:t('טוען','Loading')}`}>
          <span className="mini-reactor-icon" aria-hidden="true">{ICONS[s]}</span><span className="mini-reactor-name">{names(LABELS[s],he)}</span><span className="mini-reactor-count"><bdi>{known?group.length:'—'}</bdi></span><span className="mini-reactor-number" aria-hidden="true">{String(n+1).padStart(2,'0')}</span>
        </button>
        <div className="mini-reactor-preview">{group.slice(0,1).map(item=><button type="button" key={item.id} onClick={()=>openStock(item.id)} aria-label={`${t('פרטי מניה','Stock details')}: ${item.ticker}`}><bdi>{item.ticker}</bdi><span>{item.state==='recorded'?t('תיעוד בלבד','Recorded only'):names(STATE_LABELS[item.state],he)}</span></button>)}
          {!group.length && <span>{known?t('אין רשומות במדגם','No sampled records'):t('ממתין לנתונים','Waiting for data')}</span>}
        </div>
      </article>
    })}
  </div>
}
