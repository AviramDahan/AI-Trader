import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { LABELS, STATE_LABELS, STATE_SYMBOLS, STATIONS, type ActivityItem, type ActivityUpdate, type Station } from './systemActivityModel'
import { buildNetwork, buildConstellation, buildEvidenceSweep, networkControls, networkMotionAllowed, networkCentre as centre } from './systemNetworkGeometry'
import spiderTexture from './assets/evidence-spider-titanium-v1.png'
export { CLUSTERS, COMPACT_CLUSTERS, NETWORK_LIMIT, buildNetwork, buildConstellation, buildEvidenceSweep, networkControls, networkMotionAllowed } from './systemNetworkGeometry'
const REST = { x: 610, y: 340 }

// Clipped parts of one alpha sprite: every limb shares the same material/light.
// Coordinates use a 1280-unit sprite space, not map positions.
const SPIDER_LEGS = [
  {hip:[630,530],polygon:'70,240 290,240 440,320 600,455 665,565 600,575 435,435 70,375'},
  {hip:[685,500],polygon:'390,65 455,65 590,185 675,345 725,505 665,530 600,370 505,205'},
  {hip:[765,500],polygon:'730,500 800,350 845,245 970,150 1090,155 1220,210 970,240 880,350 810,540'},
  {hip:[825,550],polygon:'805,545 880,430 960,375 1100,350 1255,485 1230,520 1110,440 970,435 870,590'},
]

/** Photoreal decorative crawler; its finite path represents observed updates only. */
export function EvidenceSpider({moving,idle=false,allowReducedMotion=false,path,point,compact,batch,scale}:{moving:boolean;idle?:boolean;allowReducedMotion?:boolean;path:string;point:{x:number;y:number};compact:boolean;batch:string;scale?:number}) {
  const id=useId().replace(/:/g,'')
  return <g className={`system-evidence-spider ${moving?'is-walking':idle?'is-idle':''}`} data-motion-override={allowReducedMotion?'true':undefined} aria-hidden="true" pointerEvents="none">
    <defs>
      {[-1,1].flatMap(side=>SPIDER_LEGS.map((leg,n)=><clipPath key={`${side}:${n}`} id={`spider-leg-${id}-${side}-${n}`}><polygon points={side===-1?leg.polygon:leg.polygon.split(' ').map(pair=>{const [x,y]=pair.split(',').map(Number);return `${x},${1280-y}`}).join(' ')}/></clipPath>))}
      <clipPath id={`spider-body-${id}`}><path d="M 150 480 Q 300 405 475 445 L 610 515 Q 720 470 820 525 L 955 560 L 965 700 L 825 750 Q 720 815 610 750 L 480 810 Q 285 845 150 710 Z"/></clipPath>
    </defs>
    <g key={moving?batch:'rest'} transform={moving?undefined:`translate(${point.x} ${point.y})`}>
      {moving && <animateMotion path={path} dur="3.2s" rotate="auto" fill="freeze" calcMode="paced"/>}
      <g className="system-spider-pose">
      <g transform={`scale(${scale ?? (compact?.044:.052)})`}>
        <g transform="translate(-640 -640)">
          <ellipse cx="615" cy="665" rx="315" ry="180" fill="#000" opacity=".38"/>
          {[-1,1].flatMap(side=>SPIDER_LEGS.map((leg,n)=><g key={`${side}:${n}`} className={`system-spider-leg gait-${(n+(side===1?1:0))%2}`} style={{transformOrigin:`${leg.hip[0]}px ${side===-1?leg.hip[1]:1280-leg.hip[1]}px`,'--idle-period':`${9+n*1.7+(side===1?2.3:0)}s`,'--idle-delay':`${-n*2.1-(side===1?4.7:0)}s`} as React.CSSProperties}>
            <image href={spiderTexture} width="1280" height="1280" clipPath={`url(#spider-leg-${id}-${side}-${n})`}/>
          </g>))}
          <image className="system-spider-body" href={spiderTexture} width="1280" height="1280" clipPath={`url(#spider-body-${id})`}/>
        </g>
      </g>
      </g>
    </g>
  </g>
}

export function SystemNetwork({ he, items, changed, updates = [], station, setStation, selected, select, available, marketOpen }: {
  he: boolean; items: ActivityItem[]; changed: Set<string>; station: Station | 'all'; setStation: (v: Station | 'all') => void
  updates?: ActivityUpdate[]
  selected: string | null; select: (v: string|null) => void; available: boolean; marketOpen: boolean | undefined
}) {
  const [compact, setCompact] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width:1000px)').matches)
  const [reduced, setReduced] = useState(()=>typeof window!=='undefined'&&window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [motion, setMotion] = useState(()=>!reduced)
  const [motionOverride, setMotionOverride] = useState(false)
  const motionAllowed = networkMotionAllowed(motion,reduced,motionOverride)
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden')
  const seenBatch = useRef('')
  const lastPoint = useRef(REST)
  const timer = useRef<number | undefined>()
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
  const [sweep, setSweep] = useState({ key: '', path: 'M 610 340 L 610 340', active: false, shown: [] as ActivityUpdate[], omitted: 0 })
  useEffect(() => {
    const query=window.matchMedia('(prefers-reduced-motion: reduce)'), update=()=> {
      setReduced(query.matches);setMotion(!query.matches);setMotionOverride(false)
    }
    query.addEventListener('change',update)
    return ()=>query.removeEventListener('change',update)
  },[])
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  useEffect(() => {
    const query = window.matchMedia('(max-width:1000px)'), update = () => setCompact(query.matches)
    query.addEventListener('change',update)
    return () => query.removeEventListener('change',update)
  }, [])
  useEffect(() => {
    const p = centre(compact)
    window.clearTimeout(timer.current); lastPoint.current = p
    setSweep(v=>({...v,active:false,path:`M ${p.x} ${p.y} L ${p.x} ${p.y}`}))
  }, [compact])
  const clusters = useMemo(() => buildNetwork(items,compact), [items,compact])
  const field = useMemo(() => buildConstellation(compact), [compact])
  const core = centre(compact)
  useEffect(() => {
    const key = updates.map(u => u.key).join('|')
    if (!key || key === seenBatch.current) return
    seenBatch.current = key // discarded/paused/hidden batches aren't replayed when viewing resumes
    const next = buildEvidenceSweep(items, updates, lastPoint.current,compact)
    if (!motionAllowed || !visible || !available || !next.shown.length) return
    window.clearTimeout(timer.current)
    lastPoint.current = { x: next.end.x, y: next.end.y }
    setSweep({ key, path: next.path, shown: next.shown, omitted: next.omitted, active: true })
    timer.current = window.setTimeout(() => setSweep(v => ({ ...v, active: false })), 3200)
  }, [updates, items, motionAllowed, visible, available, compact])
  useEffect(() => {
    if (!motionAllowed || !visible || !available) {
      window.clearTimeout(timer.current); setSweep(v => v.active ? { ...v, active: false } : v)
    }
  }, [motionAllowed, visible, available])
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const moving = sweep.active && motionAllowed && visible && available
  const idle = !moving && motionAllowed && visible && available
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
            <button type="button" className={`system-cluster-button ${updatedStations.has(c.station)?'system-new-evidence':''}`} style={{fontSize:controls.fontSize}} dir={he ? 'rtl' : 'ltr'} aria-pressed={station === c.station} aria-label={`${LABELS[c.station][he ? 0 : 1]}: ${c.total}`}
              onClick={() => setStation(station === c.station ? 'all' : c.station)}><span className="system-cluster-index" aria-hidden="true">{String(STATIONS.indexOf(c.station)+1).padStart(2,'0')}</span><span>{LABELS[c.station][he ? 0 : 1]}</span><bdi>{c.total}</bdi></button>
          </foreignObject>
          {!!c.omitted && <text className="system-omitted" x={c.x} y={c.y + 100} textAnchor="middle">+{c.omitted} {t('ברשימת התחנה', 'in station list')}</text>}
        </g>)}
        <EvidenceSpider moving={moving} idle={idle} allowReducedMotion={motionOverride} path={sweep.path} point={lastPoint.current} compact={compact} batch={sweep.key}/>
      </svg>
    </div>
  return <div ref={panel} className="system-network-panel">
    <div className="system-network-heading"><div><span className="system-eyebrow">THE INTELLIGENCE WEB</span><h3>{t('רשת המניות', 'Stock network')}</h3></div>
      <div className="system-network-controls">
      <button type="button" className="system-motion-toggle" aria-pressed={motionAllowed} onClick={() => {setMotion(!motionAllowed);setMotionOverride(reduced&&!motionAllowed)}}>{motionAllowed ? t('השהה תנועה', 'Pause motion') : t('הפעל תנועה', 'Enable motion')}</button>
      {reduced&&!motionAllowed&&<span className="system-motion-preference">{t('הפחתת תנועה פעילה במכשיר. אפשר להפעיל כאן במפורש.', 'Reduced motion is enabled on this device. You can explicitly enable animation here.')}</span>}</div>
    </div>
    <div className="system-network-readout"><span><i className={available?'connected':''}/>{available?t('עדכון מחזורי מחובר','PERIODIC FEED CONNECTED'):t('ממתין לנתונים תקינים','AWAITING VALID DATA')}</span><bdi>{String(items.length).padStart(2,'0')} {t('רשומות במדגם','SAMPLED RECORDS')}</bdi><span>{marketOpen === true ? t('מסחר פתוח','MARKET OPEN') : marketOpen === false ? t('מחוץ למסחר','OUTSIDE SESSION') : t('מצב שוק לא ידוע','SESSION UNKNOWN')}</span></div>
    {flat}
    <div className="system-state-key" aria-label={t('מקרא מצב המניות','Stock state legend')}>{(['blocked','waiting','uncertain','open'] as const).map(s=><span className={`system-state-badge state-${s}`} key={s}><bdi aria-hidden="true">{STATE_SYMBOLS[s]}</bdi>{STATE_LABELS[s][he?0:1]}</span>)}</div>
    <div className="system-network-legend"><span><i className="system-legend-event"/>{t('סימון מניה: שינוי מתועד שנקלט — לא מצב Worker בזמן אמת', 'Stock marker: a received retained-data change — not real-time worker activity')}</span></div>
    <p className="system-spider-caption">{t('תנועת המנוחה דקורטיבית בלבד. מעבר בין תחנות מתרחש רק בעקבות עדכון מתועד — לא מעקב חי אחר Worker.', 'Idle movement is decorative only. Travel between stations happens only on received evidence updates — not live worker tracking.')}</p>
    <p className={`system-network-update ${moving&&available?'system-update-received':''}`} role="status">{sweep.shown.length ? <><strong>{t(moving ? 'נקלט עדכון' : 'העדכון האחרון שהוצג', moving ? 'Update received' : 'Last displayed update')}</strong>: <bdi>{sweep.shown.at(-1)!.item.ticker}</bdi> · {LABELS[sweep.shown.at(-1)!.item.station][he ? 0 : 1]} · <time dateTime={sweep.shown.at(-1)!.item.at!} title={sweep.shown.at(-1)!.item.at!}><bdi>{new Date(sweep.shown.at(-1)!.item.at!).toLocaleTimeString(he?'he-IL':'en-GB')}</bdi></time>{sweep.omitted>0 && <> · {t(`ועוד ${sweep.omitted} עדכונים ברשימות`, `${sweep.omitted} more updates in the lists`)}</>}</> : t('ממתין לשינוי מתועד חדש — אין מעבר בין תחנות על טעינה או רענון ללא שינוי.', 'Waiting for new retained evidence — no travel on initial load or unchanged refresh.')}</p>
    <details className="system-network-note"><summary>{t('איך לקרוא את הרשת','How to read the network')}</summary><p className="system-footnote">{t('לחצו על סימול לפתיחת המסלול, או על שם תחנה לסינון. קורים הם שיוך לתחנה, לא הוכחה למעבר בין שלבים. נקודות הרקע דקורטיביות. עד 4 רשומות בכור בטלפון, 8 במחשב; כל יתר המדגם ברשימות למטה.', 'Select a ticker for its journey, or a station name to filter. Wires mean station membership, not proof of passed stages. Background points are decorative. Up to 4 records per cluster on phones, 8 on desktop; remaining sampled records are listed below.')}</p></details>
  </div>
}
