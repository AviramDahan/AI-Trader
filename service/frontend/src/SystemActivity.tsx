import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { API_ORIGIN } from './appShared'
import { activeTargetIndexes } from './signalPresentation'
import { SystemNetwork } from './SystemNetwork'
import { buildActivity, detectActivityUpdates, finite, LABELS, REASONS, recordTime, STATE_LABELS, STATIONS, timestamp, type ActivityItem, type ActivityUpdate, type Row, type Station } from './systemActivityModel'
import './systemActivity.css'

const label = (names: [string, string], he: boolean) => names[he ? 0 : 1]
const number = (v: unknown, suffix = '') => finite(v) == null ? '—' : `${finite(v)!.toFixed(2)}${suffix}`
const stamp = (v: unknown, he: boolean) => timestamp(v) ? new Date(String(v)).toLocaleString(he ? 'he-IL' : 'en-GB') : he ? 'לא מתועד' : 'Not recorded'
const reason = (code: string | null | undefined, he: boolean) => code ? REASONS[code] ? label(REASONS[code], he) : code : he ? 'לא מתועד' : 'Not recorded'
const readFollowed = (): string[] => {
  try { const data = JSON.parse(localStorage.getItem('ai_trader_visual_follow') || '[]'); return Array.isArray(data) ? data.filter(v => typeof v === 'string').slice(0, 100) : [] } catch { return [] }
}

export function SystemActivity({ he, dashboard, dashboardError = '' }: { he: boolean, dashboard: Row | null, dashboardError?: string }) {
  const [research, setResearch] = useState<Row | null>(null)
  const [error, setError] = useState('')
  const [hours, setHours] = useState(24)
  const [ticker, setTicker] = useState('')
  const [station, setStation] = useState<Station | 'all'>('all')
  const [selected, setSelected] = useState<string | null>(null)
  const [followed, setFollowed] = useState<string[]>(readFollowed)
  const [onlyFollowed, setOnlyFollowed] = useState(false)
  const [changed, setChanged] = useState<Set<string>>(new Set())
  const [updates, setUpdates] = useState<ActivityUpdate[]>([])
  const previous = useRef<ActivityItem[] | null>(null)
  const baselineAt = useRef(0)
  const items = useMemo(() => buildActivity(research, dashboard), [research, dashboard])
  useEffect(() => {
    const controller = new AbortController()
    let active = true, inFlight = false
    setResearch(null); setError(''); previous.current = null; baselineAt.current = 0; setUpdates([]); setChanged(new Set())
    const refresh = async () => {
      if (inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      try {
        const response = await fetch(`${API_ORIGIN}/api/scanner/research?hours=${hours}`, { cache: 'no-store', signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]) })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const data = await response.json()
        if (active) { setResearch(data); setError('') }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : 'Unavailable') }
      finally { inFlight = false }
    }
    void refresh()
    const interval = window.setInterval(() => void refresh(), 60000)
    const visible = () => { if (document.visibilityState === 'visible') void refresh() }
    document.addEventListener('visibilitychange', visible)
    return () => { active = false; controller.abort(); window.clearInterval(interval); document.removeEventListener('visibilitychange', visible) }
  }, [hours])
  useEffect(() => {
    const now = Date.now(), generated = timestamp(research?.generated_at)
    // First load, failed/stale snapshots and reconnection establish a baseline, not a replay.
    if (!research || !dashboard || error || dashboardError || !generated || generated > now || now-generated > 150000) {
      previous.current = null; baselineAt.current = 0; setUpdates([]); setChanged(new Set()); return
    }
    const observed = detectActivityUpdates(previous.current, items, baselineAt.current, now)
    previous.current = items; baselineAt.current = now
    setUpdates(observed)
    setChanged(new Set(observed.map(v => v.item.id)))
    const timer = window.setTimeout(() => setChanged(new Set()), 4000)
    return () => window.clearTimeout(timer)
  }, [items, research, dashboard, error, dashboardError])
  const follow = (symbol: string) => setFollowed(current => {
    const next = current.includes(symbol) ? current.filter(v => v !== symbol) : [...current, symbol].slice(-100)
    try { localStorage.setItem('ai_trader_visual_follow', JSON.stringify(next)) } catch { /* Viewing remains available without storage. */ }
    return next
  })
  return <SystemActivityView he={he} research={research} dashboard={dashboard} error={error || dashboardError}
    items={items} changed={changed} updates={updates} hours={hours} setHours={setHours} ticker={ticker} setTicker={setTicker}
    station={station} setStation={setStation} selected={selected} setSelected={setSelected}
    followed={followed} follow={follow} onlyFollowed={onlyFollowed} setOnlyFollowed={setOnlyFollowed} />
}

type ViewProps = {
  he: boolean; research: Row | null; dashboard: Row | null; error?: string; items?: ActivityItem[]; changed?: Set<string>
  updates?: ActivityUpdate[]
  hours?: number; setHours?: (v: number) => void; ticker?: string; setTicker?: (v: string) => void
  station?: Station | 'all'; setStation?: (v: Station | 'all') => void
  selected?: string | null; setSelected?: (v: string | null) => void; followed?: string[]; follow?: (v: string) => void
  onlyFollowed?: boolean; setOnlyFollowed?: (v: boolean) => void
}

export function SystemActivityView({ he, research, dashboard, error = '', items = buildActivity(research, dashboard), changed = new Set(),
  updates = [],
  hours = 24, setHours = () => {}, ticker = '', setTicker = () => {}, station = 'all', setStation = () => {},
  selected = null, setSelected = () => {}, followed = [], follow = () => {}, onlyFollowed = false, setOnlyFollowed = () => {} }: ViewProps) {
  const t = (a: string, b: string) => he ? a : b
  const [view, setView] = useState<'stations' | 'map'>('stations')
  const [detailsOpen, setDetailsOpen] = useState(false)
  const journey = useRef<HTMLDetailsElement>(null)
  const workspace = useRef<HTMLDivElement>(null), wasOpen = useRef(false)
  useEffect(() => { setDetailsOpen(false) }, [selected])
  useEffect(() => {
    if (detailsOpen && journey.current) {
      journey.current.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
      journey.current.focus({ preventScroll: true })
    } else if(wasOpen.current && workspace.current) {
      const anchor=workspace.current.querySelector<HTMLButtonElement>('.system-stock-select[aria-pressed=true], .system-3d-stock[aria-pressed=true]')
      ;(anchor || workspace.current).scrollIntoView({behavior:'auto',block:'nearest'})
      anchor?.focus({preventScroll:true})
    }
    wasOpen.current=detailsOpen
  }, [detailsOpen])
  const filtered = items.filter(i => (!ticker || `${i.ticker} ${i.company}`.toLowerCase().includes(ticker.trim().toLowerCase())) && (!onlyFollowed || followed.includes(i.ticker)))
  const chosen = items.find(i => i.id === selected)
  const open = dashboard?.market?.is_open
  const generated = research?.generated_at
  const old = timestamp(generated) > 0 && Date.now() - timestamp(generated) > 150000
  const invalidTime = !!research && (!timestamp(generated) || timestamp(generated)>Date.now())
  const available = !!research && !!dashboard && !invalidTime && !error && !old
  const connection = error ? t('החיבור נכשל — מוצג מידע אחרון', 'Connection failed — last retained data') : !research || !dashboard ? t('ממתין לנתונים', 'Waiting for data') : invalidTime ? t('זמן התמונה לא תקין — מוצג מידע שמור','Invalid snapshot time — retained data') : old ? t('המידע לא עודכן — לא פעילות חיה', 'Data not updated — not live activity') : t('מחובר · עדכון מחזורי', 'Connected · periodic updates')
  const fullJourney = chosen && <details className="system-full-journey" ref={journey} tabIndex={-1} open={detailsOpen} onToggle={e=>setDetailsOpen(e.currentTarget.open)}>
    <summary>{t('מסלול הראיות המלא', 'Full evidence journey')} · <bdi>{chosen.ticker}</bdi></summary>
    <StockJourney item={chosen} he={he} records={research?.records || []} onClose={() => setDetailsOpen(false)} /></details>
  return <section className="system-activity" dir={he ? 'rtl' : 'ltr'} aria-label={t('המערכת בפעולה', 'System in motion')}>
    <header className="system-title"><div><span className="system-eyebrow">AI TRADER / ACTIVITY</span><h2>{t('מה קורה במערכת?', 'What is happening?')}</h2><p>{t('איפה כל מניה נמצאת — ומה עוצר או מקדם אותה.', 'Where each stock stands — and what blocks or advances it.')}</p></div>
      <div className={`system-connection ${!available ? 'warning' : ''}`}><span />{connection}<small>{t('תמונת המחקר', 'Research snapshot')}: <bdi>{stamp(generated, he)}</bdi></small></div>
    </header>
    {error && <p className="scanner-warning" role="alert">{t('העדכון נכשל. אין להסיק פעילות חדשה מהמידע השמור.', 'Refresh failed. Retained data is not new activity.')} <bdi>{error}</bdi></p>}
    <details className="system-quick-filters"><summary>{t('חיפוש וסינון', 'Search and filters')}<small>{ticker || (station !== 'all' ? label(LABELS[station],he) : t('כל התחנות', 'All stations'))} · <bdi>{hours}h</bdi></small></summary>
      <div className="system-toolbar">
        <label>{t('חיפוש מניה', 'Find a stock')}<input placeholder={t('סימול או חברה', 'Ticker or company')} value={ticker} onChange={e => setTicker(e.target.value)} /></label>
        <label>{t('תחנה', 'Station')}<select value={station} onChange={e => setStation(e.target.value as Station | 'all')}><option value="all">{t('כל התחנות', 'All stations')}</option>{STATIONS.map(s => <option key={s} value={s}>{label(LABELS[s], he)}</option>)}</select></label>
        <label>{t('חלון מחקר', 'Research window')}<select value={hours} onChange={e => setHours(Number(e.target.value))}>{[24,48,168].map(v => <option key={v} value={v}>{v}h</option>)}</select></label>
        <label className="system-follow-filter"><input type="checkbox" checked={onlyFollowed} onChange={e => setOnlyFollowed(e.target.checked)} />{t('במעקב בתצוגה בלבד', 'Visually followed only')} ({followed.length})</label>
      </div>
    </details>
    <div className="system-view-switch" role="group" aria-label={t('בחירת תצוגה','Choose view')}>
      <button type="button" aria-pressed={view==='stations'} onClick={()=>setView('stations')}>{t('תחנות ומניות','Stations & stocks')}</button>
      <button type="button" aria-pressed={view==='map'} onClick={()=>setView('map')}>{t('מפת תלת־ממד','3D map')}</button>
    </div>
    <div className="system-overview">
      <div ref={workspace} className={view==='stations'?'system-station-workspace':`system-map-workspace ${chosen?'has-selection':''} ${detailsOpen?'detail-open':''}`}>
      {view==='stations' ? <StationFlow he={he} items={filtered} station={station} selected={selected} select={setSelected}
        followed={followed} follow={follow} changed={available ? changed : new Set()} stale={!available}
        onDetails={()=>setDetailsOpen(true)} fullJourney={fullJourney} /> : <>
      <SystemNetwork he={he} items={filtered} changed={changed} updates={updates} station={station} setStation={setStation}
        selected={selected} select={setSelected} available={available} marketOpen={open} />
      {chosen && <StockFocus item={chosen} he={he} stale={!available}
        onClose={()=>setSelected(null)} onDetails={()=>setDetailsOpen(true)} />}
      </>}
      </div>
      <aside className="system-context"><details><summary>{t('מה רואים כאן?', 'What is shown?')}</summary>
        <p>{t('מניה מופיעה בתחנה לפי התיעוד האחרון שלה. זה אינו אומר שהיא עברה את כל התחנות הקודמות או שה־Worker מטפל בה כרגע. סימון עדכון מציין רק שינוי מתועד חדש שנקלט בתצוגה.', 'A stock is placed by its latest retained evidence, not proof that earlier stages passed or a worker is processing it now. An update marker indicates only new retained evidence received by the view.')}</p>
        <p>{t('מחקר מתרענן כל דקה; מצב הסורק כל 30 שניות. זה אינו זרם עסקאות בזמן אמת.', 'Research refreshes every minute; scanner status every 30 seconds. This is not a real-time trade feed.')}</p>
        <p>{t('מוצגת הסריקה האחרונה שנשמרה לכל מניה במדגם, לצד הסיגנלים והפוזיציות. זו אינה רשימת כל ה־Universe. סימון כוכב נשמר רק בדפדפן ואינו משנה watchlist או מסחר.', 'Latest retained scan per sampled stock, alongside signals and positions. Not the entire universe. Stars are browser-only and do not change the watchlist or trading.')}</p>
        </details><dl><div><dt>{t('מניות במדגם התחנות', 'Stocks in station sample')}</dt><dd>{new Set(filtered.map(i => i.ticker)).size}</dd></div>
          <div><dt>{t('פוזיציות דמה פתוחות', 'Open paper positions')}</dt><dd>{dashboard ? items.filter(i => i.state === 'open').length : '—'}</dd></div>
          <div><dt>{t('מחזור סריקה אחרון', 'Last scan')}</dt><dd><bdi>{stamp(dashboard?.activity?.last_scan_at ? new Date(dashboard.activity.last_scan_at*1000).toISOString() : null, he)}</bdi></dd></div></dl>
        {open === false && <p className="system-session-note">{t('מחוץ למסחר: האיסוף יכול להמשיך. כניסה ממתינה אינה פוזיציה פעילה.', 'Outside session: collection can continue. A waiting entry is not an active position.')}</p>}
      </aside>
    </div>
    <details className="system-support-details"><summary>{t('מצב רכיבים מתועד', 'Retained component status')}</summary><div className="system-services" aria-label={t('מצב רכיבים מתועד', 'Retained component status')}>
      {(['scan','news_feed','news_ai','monitor','telegram','backup'] as const).map(component => {
        const service = dashboard?.services?.find((s: Row) => s.component === component)
        const names: Record<string,[string,string]> = { scan: ['סורק','Scanner'], news_feed: ['איסוף חדשות','News collection'], news_ai: ['AI חדשות','News AI'], monitor: ['ניטור פוזיציות','Position monitor'], telegram: ['מסירה','Delivery'], backup: ['גיבוי','Backup'] }
        return <div key={component}><strong>{label(names[component],he)}</strong><bdi>{service?.status || t('לא מתועד','Not recorded')}</bdi><small>{t('הצלחה אחרונה','Last success')}: {stamp(service?.last_success_at,he)}</small></div>
      })}
    </div></details>
    {!!research?.records_clipped || !!research?.clipped?.length ? <details className="system-sample-warning scanner-warning"><summary>{t('מדגם מוגבל — לא כל ההיסטוריה מוצגת', 'Capped sample — not all history is shown')}</summary><p>{t('המדגם מוגבל: חלק מפרטי ההיסטוריה לא נכללו. אין להסיק שאין פעילות במניה שלא מופיעה.', 'Sample is capped: some history is omitted. An absent ticker does not prove inactivity.')}</p></details> : null}
    {!research && !error && <p role="status">{t('טוען את תיעוד התחנות…', 'Loading station evidence…')}</p>}
    {view==='map' && <details className="system-support-details"><summary>{t('רשומות התחנות', 'Station records')} <bdi>{filtered.length}</bdi></summary>
      <StationFlow he={he} items={filtered} station={station} selected={selected} select={setSelected} followed={followed} follow={follow}
        changed={new Set()} stale={!available} onDetails={()=>setDetailsOpen(true)} /></details>}
    {view==='map' && fullJourney}
    {selected && !chosen && <p role="status">{t('הרשומה כבר אינה במדגם הנוכחי. אין בכך הוכחה שהפוזיציה נסגרה.', 'Record is no longer in the current sample. This does not prove the position closed.')}</p>}
  </section>
}

const STATION_HELP: Record<Station,[string,string]> = {
  technical:['מחיר, מגמה ותקינות נתונים','Price, trend and data checks'],
  targets:['כניסה, סטופ ויחס סיכון־סיכוי','Entry, stop and risk/reward'],
  evidence:['חדשות וראיות תומכות','News and supporting evidence'],
  ai:['החלטת המודל ובקרות','Model decision and gates'],
  signal:['זכאות הסיגנל — לפני ביצוע','Signal eligibility — before execution'],
  order:['המתנה לכניסה או בירור','Waiting for entry or resolution'],
  position:['כניסה בוצעה; ניטור יעד וסטופ','Entry filled; target and stop monitoring'],
  exit:['תוצאה שנשמרה אחרי יציאה','Retained outcome after exit'],
}

export function StationFlow({he,items,station,selected,select,followed,follow,changed,stale,onDetails,fullJourney}: {
  he:boolean; items:ActivityItem[]; station:Station|'all'; selected:string|null; select:(id:string|null)=>void;
  followed:string[]; follow:(ticker:string)=>void; changed:Set<string>; stale:boolean; onDetails:()=>void; fullJourney?:ReactNode;
}) {
  const t=(a:string,b:string)=>he?a:b
  const [expanded,setExpanded]=useState<Partial<Record<Station,boolean>>>({})
  const [showAll,setShowAll]=useState<Partial<Record<Station,boolean>>>({})
  const root=useRef<HTMLDivElement>(null), previousStation=useRef<Station|null>(null)
  useEffect(()=>{
    const current=items.find(i=>i.id===selected)
    if(current) root.current?.querySelector<HTMLButtonElement>('.system-stock-select[aria-pressed=true]')?.focus({preventScroll:true})
    else if(previousStation.current) root.current?.querySelector<HTMLButtonElement>(`.station-${previousStation.current} .system-flow-heading`)?.focus({preventScroll:true})
    previousStation.current=current?.station || null
  },[selected])
  return <div ref={root} className="system-station-flow" aria-label={t('תחנות ומניות','Stations & stocks')}>
    <div className="system-flow-intro"><span>{t('לחצו על מניה לפרטים','Select a stock for details')}</span><details><summary>{t('מיקום מתועד, לא מעבר מאומת','Retained location, not verified progression')}</summary><p>{t('מיקום לפי התיעוד האחרון. תחנות קודמות אינן בהכרח אישור מעבר.','Location by latest evidence. Earlier stages do not necessarily imply approval.')}</p></details></div>
    {STATIONS.filter(s=>station==='all'||station===s).map(s=>{
      const group=items.filter(i=>i.station===s), chosen=group.find(i=>i.id===selected)
      const isOpen=!!expanded[s] || !!chosen
      // Keep every retained record reachable, including a selection beyond the list cap.
      const visible=showAll[s]?group:group.filter((i,n)=>n<8 || i.id===selected)
      return <section key={s} className={`system-flow-station station-${s} ${isOpen?'is-expanded':''}`} aria-label={label(LABELS[s],he)}>
        <button type="button" className="system-flow-heading" aria-expanded={isOpen} aria-controls={`station-records-${s}`}
          onClick={()=>{setExpanded(v=>({...v,[s]:!isOpen}));if(chosen)select(null)}}>
          <span className="system-flow-step" aria-hidden="true">{String(STATIONS.indexOf(s)+1).padStart(2,'0')}</span>
          <span className="system-flow-name"><strong>{label(LABELS[s],he)}</strong><small>{label(STATION_HELP[s],he)}</small></span>
          <span className="system-flow-count"><bdi>{group.length}</bdi><small>{t('רשומות','records')}</small></span>
          <span className="system-flow-chevron" aria-hidden="true">{isOpen?'−':'+'}</span>
        </button>
        {!isOpen && <div className="system-flow-preview">
          {group.slice(0,3).map(i=><button type="button" key={i.id} className={`system-flow-chip state-${i.state} ${changed.has(i.id)?'system-arrival':''}`}
            onClick={()=>select(i.id)} aria-label={`${t('פרטי מניה','Stock details')}: ${i.ticker} · ${label(STATE_LABELS[i.state],he)}`}>
            <bdi>{i.ticker}</bdi><span>{i.reason==='allocation_blocked'?t('הקצאת דמה חסומה','Paper allocation blocked'):i.state==='recorded'?t('תיעוד בלבד','Recorded only'):label(STATE_LABELS[i.state],he)}</span></button>)}
          {group.length>3 && <button className="system-flow-more" type="button" onClick={()=>setExpanded(v=>({...v,[s]:true}))}>{t(`עוד ${group.length-3}`,`${group.length-3} more`)}</button>}
          {!group.length && <span className="system-flow-empty">{t('אין רשומות במדגם','No records in sample')}</span>}
        </div>}
        <div id={`station-records-${s}`} hidden={!isOpen} className="system-flow-records">
          {visible.map(i=><div key={i.id} className="system-flow-record">
            <article className={`system-stock state-${i.state} ${changed.has(i.id)?'system-arrival':''}`}>
              <button type="button" className="system-stock-select" aria-pressed={selected===i.id} onClick={()=>select(selected===i.id?null:i.id)}>
                <strong><bdi>{i.ticker}</bdi></strong>{selected===i.id ? <small>{t('פרטים פתוחים — לחצו לסגירה','Details open — select to close')}</small> : <>
                <span><bdi>{i.company || t('שם חברה לא נשמר','Company name not retained')}</bdi></span>
                <small>{label(STATE_LABELS[i.state],he)} · {i.kind==='position'?(i.trade?.legacy_position_id?'Legacy':'Native'):i.kind==='signal'?t('סיגנל','Signal'):t('סריקה','Scan')}</small>
                {i.reason && <small className="system-stock-reason">{reason(i.reason,he)}</small>}
                <time dateTime={i.at||undefined}>{stamp(i.at,he)}</time></>}
              </button>
              <button className="system-follow" type="button" aria-pressed={followed.includes(i.ticker)} aria-label={`${t('מעקב בתצוגה','Visual follow')}: ${i.ticker}`} onClick={()=>follow(i.ticker)}>{followed.includes(i.ticker)?'★':'☆'}</button>
            </article>
            {selected===i.id && <div className="system-flow-focus"><StockFocus item={i} he={he} stale={stale} onClose={()=>select(null)} onDetails={onDetails}/>{fullJourney}</div>}
          </div>)}
          {!group.length && <p className="system-empty">{t('אין רשומות במדגם ובסינון הזה','No records in this filtered sample')}</p>}
          {group.length>8 && <button className="system-more" type="button" onClick={()=>setShowAll(v=>({...v,[s]:!v[s]}))}>{showAll[s]?t('פחות','Less'):t(`הצג את כל ${group.length} הרשומות`,`Show all ${group.length} records`)}</button>}
        </div>
      </section>
    })}
  </div>
}

export function activityLevels(i: ActivityItem) {
  const r = i.record, s = i.signal, trade = i.trade
  const plan = trade?.settings?.target_plan || s?.technical_json?.target_plan
  const checks: Row[] = r?.target_checks || []
  const accepted = [...checks].reverse().find(c => c.accepted_levels)?.accepted_levels
  const entry = trade?.entry_price ?? s?.planned_entry ?? accepted?.entry ?? checks.at(-1)?.quote?.price
  const stop = trade?.current_stop ?? s?.current_stop ?? s?.original_stop ?? accepted?.stop ?? plan?.stop
  const targetIndexes = activeTargetIndexes(trade || s || {})
  const onlyTarget = targetIndexes.length === 1 ? targetIndexes[0] : null
  const activeTarget = plan?.active_target ?? s?.active_target ?? trade?.active_target ?? accepted?.active_target ?? (onlyTarget ? (trade || s || {})[`tp${onlyTarget}`] : null)
  const rr = plan?.active_target != null ? plan?.rr?.[0] : onlyTarget ? plan?.rr?.[onlyTarget-1] ?? s?.[`rr${onlyTarget}`] : accepted?.rr?.[0] ?? checks.at(-1)?.geometry?.rr_rounded
  return {plan,entry,stop,activeTarget,rr}
}

export function StockFocus({item:i,he,stale,onClose,onDetails}:{item:ActivityItem;he:boolean;stale:boolean;onClose:()=>void;onDetails:()=>void}) {
  const t=(a:string,b:string)=>he?a:b
  const {entry,stop,activeTarget,rr}=activityLevels(i)
  return <aside className="system-focus-card" aria-label={t('תקציר המניה במיקוד','Focused stock summary')} onKeyDown={e=>{if(e.key==='Escape')onClose()}}>
    <header><div><span className="system-eyebrow">{t('מניה במיקוד','STOCK IN FOCUS')}</span><h3><bdi>{i.ticker}</bdi></h3><p><bdi>{i.company || t('שם חברה לא נשמר','Company name not retained')}</bdi></p></div>
      <button type="button" aria-label={t('בטל מיקוד','Clear focus')} onClick={onClose}>×</button></header>
    <span className={`system-state-badge state-${i.state}`}>{label(STATE_LABELS[i.state],he)}</span>
    <p className="system-focus-station">{label(LABELS[i.station],he)}</p>
    <p className="system-focus-reason">{i.reason?reason(i.reason,he):t('אין סיבה נוספת מתועדת. שלבים חסרים אינם אישור מעבר.','No further reason retained. Missing stages do not imply approval.')}</p>
    <time dateTime={i.at || undefined}>{t('זמן הראיה','Evidence time')}: <bdi>{stamp(i.at,he)}</bdi></time>
    {stale && <p className="scanner-warning">{t('מידע שמור — העדכון אינו זמין או אינו טרי.','Retained data — refresh unavailable or stale.')}</p>}
    <dl className="system-focus-levels">{[[t(i.trade?'כניסה בפועל':'כניסה / ייחוס',i.trade?'Filled entry':'Entry / reference'),entry,''],[t('סטופ','Stop'),stop,''],[t('יעד פעיל','Active target'),activeTarget,''],[t('RR ברוטו','Gross RR'),rr,'R']].map(([name,v,suffix])=><div key={String(name)}><dt>{String(name)}</dt><dd><bdi>{number(v,String(suffix))}</bdi></dd></div>)}</dl>
    <button className="system-focus-details" type="button" onClick={onDetails}>{t('פתח ראיות מלאות','Open full evidence')} <span aria-hidden="true">↗</span></button>
  </aside>
}

function StockJourney({ item: i, he, records, onClose }: { item: ActivityItem, he: boolean, records: Row[], onClose: () => void }) {
  const t = (a: string, b: string) => he ? a : b
  const r = i.record, s = i.signal, trade = i.trade, o = i.outcome
  const checks: Row[] = r?.target_checks || []
  const {plan,entry,stop,activeTarget,rr}=activityLevels(i)
  const sameTicker = records.filter(v => v.ticker === i.ticker && (!r || v.scan_id !== r.scan_id)).sort((a,b) => timestamp(recordTime(b))-timestamp(recordTime(a))).slice(0, 5)
  return <section className="system-journey" aria-label={t('מסלול המניה', 'Stock journey')}>
    <header><div><span className="system-eyebrow">{t('המסלול המתועד', 'RETAINED JOURNEY')}</span><h3><bdi>{i.ticker}</bdi> · <bdi>{i.company || '—'}</bdi></h3><p>{label(LABELS[i.station], he)} · {label(STATE_LABELS[i.state], he)}</p></div><button type="button" onClick={onClose}>{t('סגירה', 'Close')}</button></header>
    <p className="system-footnote">{t('שלבים שלא תועדו אינם מסומנים כעברו. הסריקות האחרות למטה אינן אותה שרשרת ביצוע.', 'Unrecorded stages are not marked passed. Other scans below are not the same execution chain.')}</p>
    <dl className="system-levels">{[[t(trade ? 'כניסה בפועל' : 'מחיר כניסה / ייחוס', trade ? 'Filled entry' : 'Entry / reference'), entry, ''], [t('סטופ', 'Stop'), stop, ''], [t('יעד פעיל', 'Active target'), activeTarget, ''], ['RR '+t('מתוכנן ברוטו', 'planned gross'), rr, 'R']].map(([name,v,suffix]) => <div key={String(name)}><dt>{String(name)}</dt><dd><bdi>{number(v, String(suffix))}</bdi></dd></div>)}</dl>
    {activeTarget == null && (trade || s) && <p>{t('תוכנית קודמת: היעדים נשמרים לפי חוזה האסטרטגיה, ללא המצאת יעד יחיד.', 'Earlier plan: targets follow its saved strategy contract; no invented single target.')} {activeTargetIndexes(trade || s || {}).map(n => <bdi key={n}> TP{n}: {number((trade || s || {})[`tp${n}`])} </bdi>)}</p>}
    <p>{t('תוקף', 'Valid until')}: <bdi>{stamp(s?.valid_until || (r?.signals || [])[0]?.valid_until, he)}</bdi> · {t('מדיניות', 'Policy')}: <bdi>{plan?.policy_version || s?.policy_version || o?.policy_version || t('גרסה לא נשמרה', 'Version not retained')}</bdi></p>
    <ol className="system-journey-timeline">
      <li><strong>{label(LABELS.technical, he)}</strong><p>{r?.technical_recorded ? t('מועמד מתועד; אין כאן אישור שכל הבקרות עברו.', 'Candidate retained; not proof all gates passed.') : t('חסרה ראיית סריקה מקושרת במדגם', 'Linked scan evidence missing in sample')}</p>{r && <time>{stamp(r.at, he)}</time>}</li>
      <li><strong>{label(LABELS.targets, he)}</strong>{checks.length ? checks.map((c, index) => <p key={index}><bdi>{c.phase} · {c.outcome}</bdi> · {stamp(c.decided_at || c.observed_at, he)}{c.rejection_reason && <> · <bdi>{reason(`pre_${c.rejection_reason.replace(/^pre_/, '')}`, he)}</bdi></>}{c.quote?.eligible_for_entry === false && <> · {t('מחיר למחקר בלבד — אינו מאשר כניסה', 'Research-only quote — does not authorize entry')}</>}</p>) : <p>{t('אין בדיקת יעדים מקושרת', 'No linked target check')}</p>}</li>
      <li><strong>{label(LABELS.evidence, he)}</strong>{r?.sec_decision ? <p>SEC · <bdi>{r.sec_decision.mode}</bdi> · {t('שינוי דירוג', 'Rank adjustment')}: <bdi>{number(r.sec_decision.sec_adjustment)}</bdi> · {stamp(r.sec_decision.decided_at, he)}<br/>{t('רשומת SEC אינה לבדה הוכחה שעבר סף הראיות.', 'A SEC record alone does not prove the evidence gate passed.')}</p> : <p>{t('פירוט מעבר סף הראיות אינו זמין במסלול הזה', 'Evidence-gate detail is not available in this view')}</p>}</li>
      <li><strong>{label(LABELS.ai, he)}</strong>{r?.ai_decision ? <p><bdi>{r.ai_decision.action}</bdi> · {t('ציון מודל לא מכויל', 'Uncalibrated model score')}: <bdi>{number(r.ai_decision.confidence)}</bdi></p> : <p>{t('אין החלטת AI מקושרת במדגם', 'No linked AI decision in sample')}</p>}{(r?.reviews || []).map((v: Row,n: number) => <p key={n}><bdi>{v.result}</bdi> · {stamp(v.at, he)} · {t('ניסיונות מתועדים', 'Recorded attempts')}: {v.attempts}</p>)}</li>
      <li><strong>{label(LABELS.signal, he)}</strong><p>{s ? t('סיגנל נשמר; פעולה ומצב ביצוע מוצגים בנפרד. מצב ההקצאה אינו מדד איכות הסיגנל.', 'Signal retained; action and execution status are separate. Allocation status is not signal quality.') : t('אין סיגנל מקושר במדגם', 'No linked signal in sample')}{s && <> <bdi>#{s.id} · {s.action || '—'} · {s.status}</bdi></>}</p></li>
      <li><strong>{label(LABELS.order, he)}</strong>{r?.orders?.length ? r.orders.map((v: Row) => <p key={v.id}><bdi>#{v.id} · {v.purpose} · {v.status}</bdi></p>) : <p>{t('פרטי הפקודה אינם זמינים במדגם; אין להסיק שבוצעה כניסה.', 'Order detail unavailable in sample; do not infer a fill.')}</p>}</li>
      <li><strong>{label(LABELS.position, he)}</strong><p>{trade ? <><bdi>#{trade.id} · {trade.status} · {trade.legacy_position_id ? 'Legacy' : 'Native'}</bdi> · {stamp(trade.opened_at, he)}<br/>{t('יתרה מהפוזיציה', 'Position remaining')}: <bdi>{number(o?.remaining_pct, '%')}</bdi></> : t('לא נמצאה פוזיציה מקושרת; סיגנל או פקודה אינם עסקה שבוצעה.', 'No linked position found; a signal or order is not a filled trade.')}</p></li>
      <li><strong>{label(LABELS.exit, he)}</strong>{o ? <><p>{t('ממומש נטו', 'Realized net')}: <bdi>{number(o.realized_net_pct,'%')} / {number(o.realized_net_r,'R')}</bdi><br/>{t('חלק פתוח ברוטו', 'Open portion gross')}: <bdi>{number(o.open_gross_pct,'%')} / {number(o.open_gross_r,'R')}</bdi></p>{(o.exits || []).map((v: Row,n: number) => <p key={n}><bdi>{v.type}</bdi> · {number(v.position_pct,'%')} {t('מהפוזיציה', 'of position')} · {stamp(v.at, he)}</p>)}{o.mark_stale && <p className="scanner-warning">{t('הערכת החלק הפתוח מבוססת על נר ישן; אינה מחיר חי.', 'Open valuation uses an old bar, not a live quote.')}</p>}{o.cohort === 'Legacy' && <p>{t('Legacy: חסרה היסטוריה מלאה לאימות התוצאה.', 'Legacy: complete history unavailable for verified results.')}</p>}</> : <p>{t('אין תוצאה מאומתת במדגם — לא אפס רווח.', 'No verified outcome in sample — not zero return.')}</p>}</li>
    </ol>
    {i.reason && <p className="system-session-note">{t('סיבה שנשמרה', 'Retained reason')}: <bdi>{reason(i.reason, he)}</bdi> <code dir="ltr">{i.reason}</code></p>}
    {!!sameTicker.length && <details><summary>{t('סריקות אחרות של אותה מניה — שרשראות נפרדות', 'Other scans of this stock — separate chains')}</summary>{sameTicker.map(v => <p key={v.scan_id}><bdi>{stamp(recordTime(v),he)}</bdi> · <bdi>{reason(v.rejection,he)}</bdi></p>)}</details>}
    <p className="system-footnote">{t('תוצאות הסיגנל משוקללות לפי חלקי הפוזיציה, אינן תשואת תיק. Shadow אינו תיק עצמאי ואינו נכלל בתחנות הביצוע הראשיות.', 'Signal outcomes are weighted by position portions, not portfolio returns. Shadow is not independent capital and is excluded from main execution stations.')}</p>
  </section>
}
