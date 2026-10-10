import { useEffect, useMemo, useRef, useState } from 'react'
import { LABELS, STATE_LABELS, STATE_SYMBOLS, STATIONS, stockCount, type ActivityItem, type ActivityUpdate, type Station } from './systemActivityModel'
import { buildNetwork, buildConstellation, buildEvidenceSweep, networkControls, networkCentre as centre } from './systemNetworkGeometry'
export { CLUSTERS, COMPACT_CLUSTERS, NETWORK_LIMIT, buildNetwork, buildConstellation, buildEvidenceSweep, networkControls, networkMotionAllowed } from './systemNetworkGeometry'

export function SystemNetwork({ he, items, changed, updates = [], station, setStation, selected, select, available, marketOpen }: {
  he: boolean; items: ActivityItem[]; changed: Set<string>; station: Station | 'all'; setStation: (v: Station | 'all') => void
  updates?: ActivityUpdate[]
  selected: string | null; select: (v: string|null) => void; available: boolean; marketOpen: boolean | undefined
}) {
  const [compact, setCompact] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width:1000px)').matches)
  const panel = useRef<HTMLDivElement>(null)
  const map = useRef<HTMLDivElement>(null)
  const [mapWidth, setMapWidth] = useState(0)
  useEffect(() => {
    const element = map.current
    if (!element) return
    const update = () => setMapWidth(element.getBoundingClientRect().width)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(()=> {
    // Navigation only: keep the selected label above the mobile card in either renderer.
    if(compact&&selected)panel.current?.scrollIntoView({behavior:'auto',block:'start'})
  },[compact,selected])
  useEffect(() => {
    const query = window.matchMedia('(max-width:1000px)'), update = () => setCompact(query.matches)
    query.addEventListener('change',update)
    return () => query.removeEventListener('change',update)
  }, [])
  const clusters = useMemo(() => buildNetwork(items,compact), [items,compact])
  const field = useMemo(() => buildConstellation(compact), [compact])
  const core = centre(compact)
  const sweep = useMemo(() => buildEvidenceSweep(items,available ? updates : [],core,compact), [items,updates,available,compact])
  const viewBox = compact ? '0 0 380 776' : '0 0 1200 800'
  const controls = networkControls(compact,mapWidth)
  const updatedStations=new Set(available?items.filter(i=>changed.has(i.id)).map(i=>i.station):[])
  const t = (a: string, b: string) => he ? a : b
  const activate = (e: React.KeyboardEvent<SVGGElement>, action: () => void) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); action() }
  }
  const flat = <div ref={map} className={`system-web system-organic-web ${compact?'compact':''}`} style={{'--map-control-unit':controls.unitsPerPixel} as React.CSSProperties}>
      <svg viewBox={viewBox} role="group" aria-label={t('מפת תחנות דו־ממדית קבועה — רשת מניות', 'Fixed 2D station map — stock network')}>
        <defs>
          <radialGradient id="web-halo"><stop stopColor="#0e493f" stopOpacity=".55"/><stop offset="1" stopColor="#071013" stopOpacity="0"/></radialGradient>
          <filter id="web-node-glow" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="2.8"/></filter>
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
          <g className="system-reactor" aria-hidden="true"><circle cx={c.x} cy={c.y} r={compact?32:45}/><circle cx={c.x} cy={c.y} r={compact?27:39}/><circle cx={c.x} cy={c.y} r={compact?22:33}/></g>
          {c.nodes.map(n => <g key={n.item.id}>
            <path className="system-stock-wire" d={`M ${c.x} ${c.y} Q ${n.x} ${c.y + 18} ${n.x} ${n.y}`} />
            <g role="button" tabIndex={0} className={`system-graph-stock state-${n.item.state} ${selected === n.item.id ? 'selected' : ''} ${available && changed.has(n.item.id) ? 'system-arrival' : ''}`}
              aria-label={`${t('מסלול מניה', 'Stock journey')}: ${n.item.ticker} · ${STATE_LABELS[n.item.state][he ? 0 : 1]}`} aria-pressed={selected === n.item.id}
              onClick={() => select(n.item.id)} onKeyDown={e => activate(e, () => select(n.item.id))}>
              <title>{`${n.item.ticker} · ${n.item.company} · ${STATE_LABELS[n.item.state][he ? 0 : 1]}`}</title>
              <circle className="system-stock-hit" cx={n.x} cy={n.y} r="23"/><circle className="system-stock-glow" cx={n.x} cy={n.y} r="6" filter="url(#web-node-glow)"/><circle className="system-stock-orbit" cx={n.x} cy={n.y} r="8"/><circle className="system-stock-dot" cx={n.x} cy={n.y} r="3.8"/>
              <foreignObject x={n.x - 40} y={n.y + 9} width="80" height={controls.labelHeight}>
                <div className="system-map-stock-label" dir="ltr" style={{fontSize:controls.labelFontSize}}>{STATE_SYMBOLS[n.item.state]} {n.item.ticker}</div>
              </foreignObject>
            </g>
          </g>)}
          <foreignObject x={c.x - controls.buttonWidth/2} y={c.y - controls.buttonOffset} width={controls.buttonWidth} height={controls.buttonHeight}>
            <button type="button" className={`system-cluster-button ${updatedStations.has(c.station)?'system-new-evidence':''}`} style={{fontSize:controls.fontSize}} dir={he ? 'rtl' : 'ltr'} aria-pressed={station === c.station} aria-label={`${LABELS[c.station][he ? 0 : 1]}: ${stockCount(items.filter(i=>i.station===c.station))} ${t('מניות','stocks')}`}
              onClick={() => setStation(station === c.station ? 'all' : c.station)}><span className="system-cluster-index" aria-hidden="true">{String(STATIONS.indexOf(c.station)+1).padStart(2,'0')}</span><span>{LABELS[c.station][he ? 0 : 1]}</span><bdi>{stockCount(items.filter(i=>i.station===c.station))}</bdi></button>
          </foreignObject>
          {!!c.omitted && <text className="system-omitted" x={c.x} y={c.y + 100} textAnchor="middle">+{c.omitted} {t('ברשימת התחנה', 'in station list')}</text>}
        </g>)}
      </svg>
    </div>
  return <div ref={panel} className="system-network-panel">
    <div className="system-network-heading"><div><span className="system-eyebrow">THE INTELLIGENCE WEB</span><h3>{t('רשת המניות', 'Stock network')}</h3></div>
    </div>
    <div className="system-network-readout"><span><i className={available?'connected':''}/>{available?t('עדכון מחזורי מחובר','PERIODIC FEED CONNECTED'):t('ממתין לנתונים תקינים','AWAITING VALID DATA')}</span><bdi>{String(stockCount(items)).padStart(2,'0')} {t('מניות במדגם','SAMPLED STOCKS')}</bdi><span>{marketOpen === true ? t('מסחר פתוח','MARKET OPEN') : marketOpen === false ? t('מחוץ למסחר','OUTSIDE SESSION') : t('מצב שוק לא ידוע','SESSION UNKNOWN')}</span></div>
    {flat}
    <div className="system-state-key" aria-label={t('מקרא מצב המניות','Stock state legend')}>{(['blocked','waiting','uncertain','open'] as const).map(s=><span className={`system-state-badge state-${s}`} key={s}><bdi aria-hidden="true">{STATE_SYMBOLS[s]}</bdi>{STATE_LABELS[s][he?0:1]}</span>)}</div>
    <div className="system-network-legend"><span><i className="system-legend-event"/>{t('סימון מניה: שינוי מתועד שנקלט — לא מצב Worker בזמן אמת', 'Stock marker: a received retained-data change — not real-time worker activity')}</span></div>
    <p className={`system-network-update ${sweep.shown.length>0&&available?'system-update-received':''}`} role="status">{sweep.shown.length ? <><strong>{t('העדכון האחרון שנקלט', 'Latest received update')}</strong>: <bdi>{sweep.shown.at(-1)!.item.ticker}</bdi> · {LABELS[sweep.shown.at(-1)!.item.station][he ? 0 : 1]} · <time dateTime={sweep.shown.at(-1)!.item.at!} title={sweep.shown.at(-1)!.item.at!}><bdi>{new Date(sweep.shown.at(-1)!.item.at!).toLocaleTimeString(he?'he-IL':'en-GB')}</bdi></time>{sweep.omitted>0 && <> · {t(`ועוד ${sweep.omitted} עדכונים ברשימות`, `${sweep.omitted} more updates in the lists`)}</>}</> : t('ממתין לשינוי מתועד חדש.', 'Waiting for new retained evidence.')}</p>
    <details className="system-network-note"><summary>{t('איך לקרוא את הרשת','How to read the network')}</summary><p className="system-footnote">{t('לחצו על סימול לפתיחת המסלול, או על שם תחנה לסינון. קורים הם שיוך לתחנה, לא הוכחה למעבר בין שלבים. נקודות הרקע דקורטיביות. עד 4 פריטי מניות בכור בטלפון, 8 במחשב; כל יתר המדגם ברשימות למטה.', 'Select a ticker for its journey, or a station name to filter. Wires mean station membership, not proof of passed stages. Background points are decorative. Up to 4 stock entries per cluster on phones, 8 on desktop; remaining sampled entries are listed below.')}</p></details>
  </div>
}
