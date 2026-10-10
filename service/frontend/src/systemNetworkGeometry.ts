import { STATIONS, type ActivityItem, type ActivityUpdate, type Station } from './systemActivityModel'

export const CLUSTERS: Record<Station, { x: number; y: number; color: string }> = {
  technical: { x: 205, y: 150, color: '#67cfff' }, targets: { x: 545, y: 115, color: '#f7c96b' },
  evidence: { x: 950, y: 155, color: '#c3a2ff' }, ai: { x: 1040, y: 395, color: '#ff8ca9' },
  signal: { x: 845, y: 635, color: '#72e2ba' }, order: { x: 480, y: 550, color: '#f8b87a' },
  position: { x: 185, y: 630, color: '#50dccd' }, exit: { x: 185, y: 390, color: '#a4b5d2' },
}
export const NETWORK_LIMIT = 8
export const COMPACT_CLUSTERS: typeof CLUSTERS = Object.fromEntries(STATIONS.map((s,n) => [s, {
  ...CLUSTERS[s], x: n % 2 ? 286 : 94, y: 112 + Math.floor(n/2)*176,
}])) as typeof CLUSTERS
export const networkCentre = (compact: boolean) => compact ? { x: 190, y: 388 } : { x: 610, y: 340 }
export const networkMotionAllowed = (requested: boolean, reduced: boolean, explicitlyEnabled: boolean) => requested && (!reduced || explicitlyEnabled)
/** Screen-space controls: resizing a sidebar must not shrink text or touch targets. */
export function networkControls(compact: boolean, renderedWidth: number) {
  const width = Number.isFinite(renderedWidth) && renderedWidth > 0 ? renderedWidth : compact ? 380 : 1200
  const unitsPerPixel = (compact ? 380 : 1200) / width
  return { unitsPerPixel, buttonWidth: (compact ? Math.min(164,width*.44) : 208)*unitsPerPixel,
    buttonHeight: 48*unitsPerPixel, buttonOffset: (compact ? 64 : 78)*unitsPerPixel,
    fontSize: 14*unitsPerPixel, labelFontSize: 13*unitsPerPixel, labelHeight: 20*unitsPerPixel }
}
export const geometryHash = (s: string) => Array.from(s).reduce((a, c) => ((a * 31 + c.charCodeAt(0)) >>> 0), 7)
export function buildNetwork(items: ActivityItem[], compact = false) {
  return STATIONS.map(station => {
    const cluster = (compact ? COMPACT_CLUSTERS : CLUSTERS)[station]
    const group = items.filter(i => i.station === station).sort((a, b) => a.id.localeCompare(b.id))
    const nodes = group.slice(0, compact?4:NETWORK_LIMIT).map((item, index) => ({ item,
      x: cluster.x + (compact?((index%2)-.5)*88:((index%3)-1)*88) + (geometryHash(item.id) % 7 - 3),
      y: cluster.y + 2 + (compact?Math.floor(index/2)*42:Math.floor(index/3)*36) + (geometryHash(item.id + 'y') % 7 - 3),
    }))
    return { station, ...cluster, total: group.length, omitted: Math.max(0, group.length - nodes.length), nodes }
  })
}
/** Decorative geometry only: no vertex or edge represents a stock or a passed gate. */
export function buildConstellation(compact = false) {
  return STATIONS.map(station => {
    const c = (compact ? COMPACT_CLUSTERS : CLUSTERS)[station], count = compact ? 40 : 80
    const points = Array.from({length: count}, (_,n) => {
      const angle = n*2.39996 + geometryHash(station)%10
      const contour = .84 + .12*Math.sin(angle*3 + geometryHash(station)%5)
      const radius = Math.sqrt((n+.5)/count)*(compact ? 76 : 127)*contour
      return {x:c.x+Math.cos(angle)*radius, y:c.y+Math.sin(angle)*radius*.7,
        radius:n%31===0 ? 2.3 : n%9===0 ? 1.5 : .55+(n%3)*.3, opacity:.2+(n%7)*.09}
    })
    const edges = points.flatMap((p,n) => points.map((q,j)=>({q,j,d:(q.x-p.x)**2+(q.y-p.y)**2}))
      .filter(v=>v.j!==n).sort((a,b)=>a.d-b.d).slice(0,3).filter(v=>v.j>n).map(v=>({a:p,b:v.q})))
    return {station,...c,points,edges}
  })
}
// Destinations are observed updates, never a tour of assumed pipeline stages.
export function buildEvidenceSweep(items: ActivityItem[], updates: ActivityUpdate[], from = networkCentre(false), compact = false) {
  const known = new Map(items.map(i => [i.id, i]))
  const visibleUpdates = updates.filter(u => known.get(u.item.id)?.station === u.item.station)
  const shown = visibleUpdates.slice(0, 4)
  const nodes = new Map(buildNetwork(items,compact).flatMap(c => c.nodes.map(n => [n.item.id, n] as const)))
  const points = [from, ...shown.map(u => nodes.get(u.item.id) || (compact ? COMPACT_CLUSTERS : CLUSTERS)[u.item.station])]
  return { path: points.map((p, n) => `${n ? 'L' : 'M'} ${p.x} ${p.y}`).join(' '),
    end: points.at(-1)!, shown, omitted: visibleUpdates.length - shown.length }
}
