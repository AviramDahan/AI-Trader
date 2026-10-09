import { Component, lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { LABELS, STATE_LABELS, STATE_SYMBOLS, STATIONS, type ActivityItem, type ActivityUpdate, type Station } from './systemActivityModel'
import { CLUSTERS, COMPACT_CLUSTERS, buildNetwork, buildConstellation, buildEvidenceSweep, networkCentre as centre } from './systemNetworkGeometry'
export { CLUSTERS, COMPACT_CLUSTERS, NETWORK_LIMIT, buildNetwork, buildConstellation, buildEvidenceSweep } from './systemNetworkGeometry'
const Web3D = lazy(() => import('./SystemWeb3D'))
// A GPU/chunk failure must not remove the retained data or stock controls.
export class Network3DErrorBoundary extends Component<{children:ReactNode;fallback:ReactNode;he:boolean},{failed:boolean}> {
  state={failed:false}
  static getDerivedStateFromError(){return {failed:true}}
  render(){return this.state.failed?<><p className="system-3d-fallback" role="status">{this.props.he?'תצוגת התלת־ממד לא נטענה; המפה הדו־ממדית נשארת זמינה.':'3D did not load; the 2D map remains available.'}</p>{this.props.fallback}</>:this.props.children}
}
const REST = { x: 610, y: 340 }

export function SystemNetwork({ he, items, changed, updates = [], station, setStation, selected, select, available, marketOpen }: {
  he: boolean; items: ActivityItem[]; changed: Set<string>; station: Station | 'all'; setStation: (v: Station | 'all') => void
  updates?: ActivityUpdate[]
  selected: string | null; select: (v: string|null) => void; available: boolean; marketOpen: boolean | undefined
}) {
  const [motion, setMotion] = useState(true)
  const [compact, setCompact] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width:640px)').matches)
  const [zoom, setZoom] = useState(false)
  const [threeD, setThreeD] = useState(true)
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden')
  const seenBatch = useRef('')
  const lastPoint = useRef(REST)
  const timer = useRef<number | undefined>()
  const [sweep, setSweep] = useState({ key: '', path: 'M 610 340 L 610 340', active: false, shown: [] as ActivityUpdate[], omitted: 0 })
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  useEffect(() => {
    const query = window.matchMedia('(max-width:640px)'), update = () => setCompact(query.matches)
    query.addEventListener('change',update)
    return () => query.removeEventListener('change',update)
  }, [])
  useEffect(() => {
    const p = centre(compact)
    window.clearTimeout(timer.current); lastPoint.current = p
    setSweep(v=>({...v,active:false,path:`M ${p.x} ${p.y} L ${p.x} ${p.y}`})); setZoom(false)
  }, [compact])
  const clusters = useMemo(() => buildNetwork(items,compact), [items,compact])
  const field = useMemo(() => buildConstellation(compact), [compact])
  const core = centre(compact)
  useEffect(() => {
    const key = updates.map(u => u.key).join('|')
    if (!key || key === seenBatch.current) return
    seenBatch.current = key // discarded/paused/hidden batches aren't replayed when viewing resumes
    const next = buildEvidenceSweep(items, updates, lastPoint.current,compact)
    if (!motion || !visible || !available || !next.shown.length) return
    window.clearTimeout(timer.current)
    lastPoint.current = { x: next.end.x, y: next.end.y }
    setSweep({ key, path: next.path, shown: next.shown, omitted: next.omitted, active: true })
    timer.current = window.setTimeout(() => setSweep(v => ({ ...v, active: false })), 3200)
  }, [updates, items, motion, visible, available, compact])
  useEffect(() => {
    if (!motion || !visible || !available) {
      window.clearTimeout(timer.current); setSweep(v => v.active ? { ...v, active: false } : v)
    }
  }, [motion, visible, available])
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const moving = sweep.active && motion && visible && available
  const focus = clusters.flatMap(c=>c.nodes).find(n=>n.item.id===selected) || (station !== 'all' ? (compact ? COMPACT_CLUSTERS : CLUSTERS)[station] : core)
  const viewBox = zoom || selected ? `${focus.x-(compact?115:250)} ${focus.y-(compact?(selected?50:125):165)} ${compact?230:500} ${compact?250:330}` : compact ? '0 0 380 672' : '0 0 1200 720'
  const updatedStations=new Set(available?items.filter(i=>changed.has(i.id)).map(i=>i.station):[])
  const t = (a: string, b: string) => he ? a : b
  const activate = (e: React.KeyboardEvent<SVGGElement>, action: () => void) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); action() }
  }
  const flat = <div className={`system-web system-organic-web ${compact?'compact':''} ${moving ? 'evidence-motion-enabled' : ''}`}>
      <svg viewBox={viewBox} role="group" aria-label={t('מפת תחנות אינטראקטיבית — רשת מניות', 'Interactive station map — stock network')}>
        <defs>
          <radialGradient id="web-halo"><stop stopColor="#0e493f" stopOpacity=".55"/><stop offset="1" stopColor="#071013" stopOpacity="0"/></radialGradient>
          <radialGradient id="spider-body"><stop stopColor="#475c61"/><stop offset=".48" stopColor="#15272d"/><stop offset="1" stopColor="#040b10"/></radialGradient>
          <linearGradient id="spider-metal" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#b6fff0"/><stop offset=".4" stopColor="#479d93"/><stop offset="1" stopColor="#193745"/></linearGradient>
          <filter id="web-node-glow" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="2.8"/></filter>
          <filter id="spider-shadow" x="-100%" y="-100%" width="300%" height="300%"><feDropShadow dx="0" dy="5" stdDeviation="5" floodColor="#000" floodOpacity=".9"/></filter>
        </defs>
        <g aria-hidden="true" className="system-web-decoration">
          <ellipse cx={core.x} cy={core.y} rx={compact?160:490} ry={compact?260:320} fill="url(#web-halo)" />
          {field.map(c => <g key={c.station} style={{ color: c.color }} opacity={station !== 'all' && station !== c.station ? .2 : 1}>
            {c.edges.map((e,n)=><path key={`e${n}`} d={`M ${e.a.x} ${e.a.y} L ${e.b.x} ${e.b.y}`}/>)}
            {c.points.map((p,n)=><circle key={`p${n}`} cx={p.x} cy={p.y} r={p.radius} fill={c.color} opacity={p.opacity}/>)}
            {[0,1,2].map(n=><path key={`s${n}`} className="system-silk" d={`M ${core.x+(n-1)*6} ${core.y} C ${core.x+(c.x-core.x)*.32} ${c.y+(n-1)*24} ${c.x+(n-1)*14} ${core.y+(c.y-core.y)*.75} ${c.x+(n-1)*10} ${c.y}`}/>)}
          </g>)}
        </g>
        <g className="system-network-core" aria-hidden="true"><circle cx={core.x} cy={core.y} r={compact?38:65}/><circle className="system-core-ring" cx={core.x} cy={core.y} r={compact?48:81}/><text x={core.x} y={core.y+(compact?63:99)} textAnchor="middle">AI TRADER</text><text x={core.x} y={core.y+(compact?76:114)} textAnchor="middle" className="system-core-sub">EVIDENCE / NOT EXECUTION</text></g>
        {clusters.map(c => <g key={c.station} className={station !== 'all' && station !== c.station ? 'system-cluster-muted' : ''} style={{ color: c.color }}>
          {c.nodes.map(n => <g key={n.item.id}>
            <path className="system-stock-wire" d={`M ${c.x} ${c.y} Q ${n.x} ${c.y + 18} ${n.x} ${n.y}`} />
            <g role="button" tabIndex={0} className={`system-graph-stock state-${n.item.state} ${selected === n.item.id ? 'selected' : ''} ${available && changed.has(n.item.id) ? 'system-arrival' : ''}`}
              aria-label={`${t('מסלול מניה', 'Stock journey')}: ${n.item.ticker} · ${STATE_LABELS[n.item.state][he ? 0 : 1]}`} aria-pressed={selected === n.item.id}
              onClick={() => select(n.item.id)} onKeyDown={e => activate(e, () => select(n.item.id))}>
              <title>{`${n.item.ticker} · ${n.item.company} · ${STATE_LABELS[n.item.state][he ? 0 : 1]}`}</title>
              <circle className="system-stock-hit" cx={n.x} cy={n.y} r="23"/><circle className="system-stock-glow" cx={n.x} cy={n.y} r="6" filter="url(#web-node-glow)"/><circle className="system-stock-orbit" cx={n.x} cy={n.y} r="8"/><circle className="system-stock-dot" cx={n.x} cy={n.y} r="3.8"/>
              <text x={n.x} y={n.y + 19} textAnchor="middle" direction="ltr">{STATE_SYMBOLS[n.item.state]} {n.item.ticker.slice(0, 10)}</text>
            </g>
          </g>)}
          <foreignObject x={c.x - (compact?84:100)} y={c.y - (compact?54:78)} width={compact?168:200} height="44">
            <button type="button" className={`system-cluster-button ${updatedStations.has(c.station)?'system-new-evidence':''}`} dir={he ? 'rtl' : 'ltr'} aria-pressed={station === c.station} aria-label={`${LABELS[c.station][he ? 0 : 1]}: ${c.total}`}
              onClick={() => {setStation(station === c.station ? 'all' : c.station);setZoom(false)}}><span className="system-cluster-index" aria-hidden="true">{String(STATIONS.indexOf(c.station)+1).padStart(2,'0')}</span><span>{LABELS[c.station][he ? 0 : 1]}</span><bdi>{c.total}</bdi></button>
          </foreignObject>
          {!!c.omitted && <text className="system-omitted" x={c.x} y={c.y + 100} textAnchor="middle">+{c.omitted} {t('ברשימת התחנה', 'in station list')}</text>}
        </g>)}
        {/* A finite cursor sweep to newly observed evidence, not a trade or worker trace. */}
        <g key={sweep.key} aria-hidden="true" className="system-crawler" style={{ offsetPath: `path('${sweep.path}')`, offsetDistance: moving ? undefined : '100%' }}>
          <g transform={`scale(${compact ? .43 : .8})`} filter="url(#spider-shadow)">
            <circle className="system-crawler-aura" r="47"/>
            {Array.from({ length: 8 }, (_, n) => { const side=n<4?-1:1,row=n%4,y=(row-1.5)*7,kneeY=[-29,-13,14,31][row],tipY=[-51,-30,32,52][row],kneeX=[26,39,38,27][row],tipX=[49,60,57,45][row]
              return <g key={n} className={`system-crawler-leg leg-${n}`}><path className="spider-leg-shadow" d={`M ${side*8} ${y} L ${side*kneeX} ${kneeY} L ${side*tipX} ${tipY}`}/><path className="spider-leg-metal" d={`M ${side*8} ${y} L ${side*kneeX} ${kneeY} L ${side*tipX} ${tipY}`}/><circle cx={side*kneeX} cy={kneeY} r="1.8" fill="#8fcec3"/></g>
            })}
            <ellipse cy="12" rx="12" ry="20" className="system-crawler-body"/><path className="spider-shell" d="M 0 -5 Q -10 8 -6 23 M 0 -5 Q 10 8 6 23"/>
            <ellipse cy="-12" rx="10" ry="12" className="system-crawler-head"/>
            <path className="spider-shell" d="M -5 -22 L -7 -29 M 5 -22 L 7 -29"/>
            <circle cx="-4" cy="-17" r="2.1" fill="#f4b6df"/><circle cx="4" cy="-17" r="2.1" fill="#f4b6df"/>
          </g>
        </g>
      </svg>
    </div>
  return <div className="system-network-panel">
    <div className="system-network-heading"><div><span className="system-eyebrow">THE INTELLIGENCE WEB</span><h3>{t('רשת המניות', 'Stock network')}</h3></div>
      <div className="system-network-controls">
      <button type="button" aria-pressed={threeD} onClick={()=>{setThreeD(v=>!v);setZoom(false)}}>{threeD?t('תצוגת 2D','2D view'):t('תצוגת 3D','3D view')}</button>
      <button type="button" aria-pressed={zoom || !!selected} onClick={()=>{if(selected){select(null);setZoom(false)}else setZoom(v=>!v)}}>{zoom || selected?t('מפה מלאה','Full map'):t('התקרבות','Zoom in')}</button>
      <button type="button" className="system-motion-toggle" aria-pressed={motion} onClick={() => setMotion(v => !v)}>{motion ? t('השהה תנועת עדכונים', 'Pause update motion') : t('הפעל תנועת עדכונים', 'Enable update motion')}</button></div>
    </div>
    <div className="system-network-readout"><span><i className={available?'connected':''}/>{available?t('עדכון מחזורי מחובר','PERIODIC FEED CONNECTED'):t('ממתין לנתונים תקינים','AWAITING VALID DATA')}</span><bdi>{String(items.length).padStart(2,'0')} {t('רשומות במדגם','SAMPLED RECORDS')}</bdi><span>{marketOpen === true ? t('מסחר פתוח','MARKET OPEN') : marketOpen === false ? t('מחוץ למסחר','OUTSIDE SESSION') : t('מצב שוק לא ידוע','SESSION UNKNOWN')}</span></div>
    {threeD ? <Network3DErrorBoundary he={he} fallback={flat}><Suspense fallback={flat}><Web3D he={he} items={items} compact={compact} station={station} setStation={setStation}
      selected={selected} select={select} changed={changed} available={available} visible={visible} zoom={zoom}
      moving={moving} sweepKey={sweep.key} updates={sweep.shown} fallback={flat} resetZoom={()=>{setZoom(false);select(null)}}/></Suspense></Network3DErrorBoundary> : flat}
    <div className="system-state-key" aria-label={t('מקרא מצב המניות','Stock state legend')}>{(['blocked','waiting','uncertain','open'] as const).map(s=><span className={`system-state-badge state-${s}`} key={s}><bdi aria-hidden="true">{STATE_SYMBOLS[s]}</bdi>{STATE_LABELS[s][he?0:1]}</span>)}</div>
    <div className="system-network-legend"><span><i className="system-legend-crawler"/>{t('העכביש: מצביע לעדכון מתועד שנקלט — לא מצב Worker בזמן אמת', 'Crawler: points to received evidence updates — not real-time worker activity')}</span><span><i className="system-legend-event"/>{t('הבהוב מניה: שינוי אמיתי במידע שנשמר', 'Stock glow: an actual retained-data change')}</span></div>
    <p className={`system-network-update ${moving&&available?'system-update-received':''}`} role="status">{sweep.shown.length ? <><strong>{t(moving ? 'נקלט עדכון' : 'העדכון האחרון שהוצג', moving ? 'Update received' : 'Last displayed update')}</strong>: <bdi>{sweep.shown.at(-1)!.item.ticker}</bdi> · {LABELS[sweep.shown.at(-1)!.item.station][he ? 0 : 1]} · <time dateTime={sweep.shown.at(-1)!.item.at!} title={sweep.shown.at(-1)!.item.at!}><bdi>{new Date(sweep.shown.at(-1)!.item.at!).toLocaleTimeString(he?'he-IL':'en-GB')}</bdi></time>{sweep.omitted>0 && <> · {t(`ועוד ${sweep.omitted} עדכונים ברשימות`, `${sweep.omitted} more updates in the lists`)}</>}</> : t('ממתין לשינוי מתועד חדש — אין תנועה על טעינה או רענון ללא שינוי.', 'Waiting for new retained evidence — no motion on initial load or unchanged refresh.')}</p>
    <p className="system-reduced-note">{t('התנועה מושבתת בהתאם להעדפת תנועה מופחתת במכשיר.', 'Motion is disabled by your device’s reduced-motion preference.')}</p>
    <details className="system-network-note"><summary>{t('איך לקרוא את הרשת','How to read the network')}</summary><p className="system-footnote">{t('לחצו על סימול לפתיחת המסלול, או על שם תחנה לסינון. קורים הם שיוך לתחנה, לא הוכחה למעבר בין שלבים. נקודות הרקע דקורטיביות. עד 8 רשומות בכל אשכול; כל יתר המדגם ברשימות למטה.', 'Select a ticker for its journey, or a station name to filter. Wires mean station membership, not proof of passed stages. Background points are decorative. Up to 8 records per cluster; remaining sampled records are listed below.')}</p></details>
  </div>
}
