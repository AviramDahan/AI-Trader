import { useEffect, useMemo, useRef, useState } from 'react'
import { LABELS, STATE_LABELS, STATIONS, type ActivityItem, type ActivityUpdate, type Station } from './systemActivityModel'

export const CLUSTERS: Record<Station, { x: number; y: number; color: string }> = {
  technical: { x: 205, y: 150, color: '#67cfff' }, targets: { x: 545, y: 115, color: '#f7c96b' },
  evidence: { x: 950, y: 155, color: '#c3a2ff' }, ai: { x: 1040, y: 370, color: '#ff8ca9' },
  signal: { x: 845, y: 575, color: '#72e2ba' }, order: { x: 480, y: 550, color: '#f8b87a' },
  position: { x: 185, y: 485, color: '#50dccd' }, exit: { x: 185, y: 315, color: '#a4b5d2' },
}
export const NETWORK_LIMIT = 8
const hash = (s: string) => Array.from(s).reduce((a, c) => ((a * 31 + c.charCodeAt(0)) >>> 0), 7)
export function buildNetwork(items: ActivityItem[]) {
  return STATIONS.map(station => {
    const cluster = CLUSTERS[station]
    // Stable IDs, never random layout or fabricated stock nodes. Each cluster is bounded.
    const group = items.filter(i => i.station === station).sort((a, b) => a.id.localeCompare(b.id))
    const nodes = group.slice(0, NETWORK_LIMIT).map((item, index) => ({ item,
      x: cluster.x + ((index % 4) - 1.5) * 54 + (hash(item.id) % 13 - 6),
      y: cluster.y + 38 + Math.floor(index / 4) * 45 + (hash(item.id + 'y') % 13 - 6),
    }))
    return { station, ...cluster, total: group.length, omitted: Math.max(0, group.length - nodes.length), nodes }
  })
}
const REST = { x: 610, y: 340 }
// Cursor destinations are observed updates, never a tour of assumed pipeline stages.
export function buildEvidenceSweep(items: ActivityItem[], updates: ActivityUpdate[], from = REST) {
  const known = new Map(items.map(i => [i.id, i]))
  const visibleUpdates = updates.filter(u => known.get(u.item.id)?.station === u.item.station)
  const shown = visibleUpdates.slice(0, 4)
  const nodes = new Map(buildNetwork(items).flatMap(c => c.nodes.map(n => [n.item.id, n] as const)))
  const points = [from, ...shown.map(u => nodes.get(u.item.id) || CLUSTERS[u.item.station])]
  return { path: points.map((p, n) => `${n ? 'L' : 'M'} ${p.x} ${p.y}`).join(' '),
    end: points.at(-1)!, shown, omitted: visibleUpdates.length - shown.length }
}

export function SystemNetwork({ he, items, changed, updates = [], station, setStation, selected, select, available, marketOpen }: {
  he: boolean; items: ActivityItem[]; changed: Set<string>; station: Station | 'all'; setStation: (v: Station | 'all') => void
  updates?: ActivityUpdate[]
  selected: string | null; select: (v: string) => void; available: boolean; marketOpen: boolean | undefined
}) {
  const [motion, setMotion] = useState(true)
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
  const clusters = useMemo(() => buildNetwork(items), [items])
  useEffect(() => {
    const key = updates.map(u => u.key).join('|')
    if (!key || key === seenBatch.current) return
    seenBatch.current = key // discarded/paused/hidden batches aren't replayed when viewing resumes
    const next = buildEvidenceSweep(items, updates, lastPoint.current)
    if (!motion || !visible || !available || !next.shown.length) return
    window.clearTimeout(timer.current)
    lastPoint.current = { x: next.end.x, y: next.end.y }
    setSweep({ key, path: next.path, shown: next.shown, omitted: next.omitted, active: true })
    timer.current = window.setTimeout(() => setSweep(v => ({ ...v, active: false })), 3200)
  }, [updates, items, motion, visible, available])
  useEffect(() => {
    if (!motion || !visible || !available) {
      window.clearTimeout(timer.current); setSweep(v => v.active ? { ...v, active: false } : v)
    }
  }, [motion, visible, available])
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const moving = sweep.active && motion && visible && available
  const t = (a: string, b: string) => he ? a : b
  const activate = (e: React.KeyboardEvent<SVGGElement>, action: () => void) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); action() }
  }
  return <div className="system-network-panel">
    <div className="system-network-heading"><div><span className="system-eyebrow">NEURAL WEB / RETAINED EVIDENCE</span><h3>{t('רשת המניות', 'Stock network')}</h3></div>
      <button type="button" className="system-motion-toggle" aria-pressed={motion} onClick={() => setMotion(v => !v)}>{motion ? t('השהה תנועת עדכונים', 'Pause update motion') : t('הפעל תנועת עדכונים', 'Enable update motion')}</button>
    </div>
    <div className={`system-web system-organic-web ${moving ? 'evidence-motion-enabled' : ''}`}>
      <svg viewBox="0 0 1200 720" role="group" aria-label={t('מפת תחנות אינטראקטיבית — רשת מניות', 'Interactive station map — stock network')}>
        <defs><radialGradient id="web-halo"><stop stopColor="#2dd4bf" stopOpacity=".13"/><stop offset="1" stopColor="#2dd4bf" stopOpacity="0"/></radialGradient></defs>
        <g aria-hidden="true" className="system-web-decoration">
          <circle cx="610" cy="340" r="300" fill="url(#web-halo)" />
          {clusters.map(c => <g key={c.station} style={{ color: c.color }}>
            {Array.from({ length: 24 }, (_, n) => { const angle = n * 2.39996, radius = 24 + Math.sqrt(n) * 20
              const x = c.x + Math.cos(angle) * radius, y = c.y + Math.sin(angle) * radius * .7
              const previous = angle - 2.39996
              return <g key={n}><path d={`M ${c.x} ${c.y} Q ${c.x + Math.sin(angle) * 45} ${y} ${x} ${y} L ${c.x + Math.cos(previous) * radius} ${c.y + Math.sin(previous) * radius * .7}`} /><circle cx={x} cy={y} r="1.1" /></g>
            })}
            <path className="system-cluster-wire" d={`M 610 340 Q ${c.x} 340 ${c.x} ${c.y}`} />
          </g>)}
        </g>
        <g className="system-network-core" aria-hidden="true"><circle cx="610" cy="340" r="42"/><text x="610" y="333" textAnchor="middle">AI TRADER</text><text x="610" y="351" textAnchor="middle" className="system-core-sub">PAPER / READ ONLY</text></g>
        {clusters.map(c => <g key={c.station} className={station !== 'all' && station !== c.station ? 'system-cluster-muted' : ''} style={{ color: c.color }}>
          {c.nodes.map(n => <g key={n.item.id}>
            <path className="system-stock-wire" d={`M ${c.x} ${c.y} Q ${n.x} ${c.y + 18} ${n.x} ${n.y}`} />
            <g role="button" tabIndex={0} className={`system-graph-stock state-${n.item.state} ${selected === n.item.id ? 'selected' : ''} ${available && changed.has(n.item.id) ? 'system-arrival' : ''}`}
              aria-label={`${t('מסלול מניה', 'Stock journey')}: ${n.item.ticker} · ${STATE_LABELS[n.item.state][he ? 0 : 1]}`} aria-pressed={selected === n.item.id}
              onClick={() => select(n.item.id)} onKeyDown={e => activate(e, () => select(n.item.id))}>
              <title>{`${n.item.ticker} · ${n.item.company} · ${STATE_LABELS[n.item.state][he ? 0 : 1]}`}</title>
              <circle className="system-stock-hit" cx={n.x} cy={n.y} r="22"/><circle className="system-stock-dot" cx={n.x} cy={n.y} r="4"/>
              <text x={n.x} y={n.y + 17} textAnchor="middle" direction="ltr">{n.item.ticker.slice(0, 10)}</text>
            </g>
          </g>)}
          <foreignObject x={c.x - 88} y={c.y - 25} width="176" height="36">
            <button type="button" className="system-cluster-button" dir={he ? 'rtl' : 'ltr'} aria-pressed={station === c.station} aria-label={`${LABELS[c.station][he ? 0 : 1]}: ${c.total}`}
              onClick={() => setStation(station === c.station ? 'all' : c.station)}><span>{LABELS[c.station][he ? 0 : 1]}</span><bdi>{c.total}</bdi></button>
          </foreignObject>
          {!!c.omitted && <text className="system-omitted" x={c.x} y={c.y + 140} textAnchor="middle">+{c.omitted} {t('ברשימת התחנה', 'in station list')}</text>}
        </g>)}
        {/* A finite cursor sweep to newly observed evidence, not a trade or worker trace. */}
        <g key={sweep.key} aria-hidden="true" className="system-crawler" style={{ offsetPath: `path('${sweep.path}')`, offsetDistance: moving ? undefined : '100%' }}>
          <circle className="system-crawler-aura" r="28"/>
          {Array.from({ length: 8 }, (_, n) => { const side = n < 4 ? -1 : 1, row = n % 4, y = (row - 1.5) * 5
            return <path key={n} className={`system-crawler-leg leg-${n}`} d={`M ${side*5} ${y} Q ${side*15} ${y-6} ${side*(23-row)} ${y+9} L ${side*(29-row)} ${y+14}`} />
          })}
          <ellipse rx="7" ry="10" className="system-crawler-body"/><circle cy="-11" r="4" className="system-crawler-head"/>
        </g>
        <text className="system-network-session" x="610" y="687" textAnchor="middle">{marketOpen === true ? t('מסחר פתוח', 'Market open') : marketOpen === false ? t('מחוץ למסחר', 'Outside session') : t('מצב שוק לא ידוע', 'Session unknown')} · {items.length} {t('רשומות במדגם', 'sample records')}</text>
      </svg>
    </div>
    <div className="system-network-legend"><span><i className="system-legend-crawler"/>{t('העכביש: מצביע לעדכון מתועד שנקלט — לא מצב Worker בזמן אמת', 'Crawler: points to received evidence updates — not real-time worker activity')}</span><span><i className="system-legend-event"/>{t('הבהוב מניה: שינוי אמיתי במידע שנשמר', 'Stock glow: an actual retained-data change')}</span></div>
    <p className="system-network-update" role="status">{sweep.shown.length ? <>{t(moving ? 'נקלט עדכון' : 'העדכון האחרון שהוצג', moving ? 'Update received' : 'Last displayed update')}: <bdi>{sweep.shown.at(-1)!.item.ticker}</bdi> · {LABELS[sweep.shown.at(-1)!.item.station][he ? 0 : 1]} · <bdi>{sweep.shown.at(-1)!.item.at}</bdi>{sweep.omitted>0 && <> · {t(`ועוד ${sweep.omitted} עדכונים ברשימות`, `${sweep.omitted} more updates in the lists`)}</>}</> : t('ממתין לשינוי מתועד חדש — אין תנועה על טעינה או רענון ללא שינוי.', 'Waiting for new retained evidence — no motion on initial load or unchanged refresh.')}</p>
    <p className="system-reduced-note">{t('התנועה מושבתת בהתאם להעדפת תנועה מופחתת במכשיר.', 'Motion is disabled by your device’s reduced-motion preference.')}</p>
    <p className="system-footnote system-network-note">{t('לחצו על סימול לפתיחת המסלול, או על שם תחנה לסינון. קורים הם שיוך לתחנה, לא הוכחה למעבר בין שלבים. נקודות הרקע דקורטיביות. עד 8 רשומות בכל אשכול; כל יתר המדגם ברשימות למטה.', 'Select a ticker for its journey, or a station name to filter. Wires mean station membership, not proof of passed stages. Background points are decorative. Up to 8 records per cluster; remaining sampled records are listed below.')}</p>
  </div>
}
