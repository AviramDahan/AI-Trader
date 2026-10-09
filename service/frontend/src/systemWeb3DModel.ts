import { STATIONS, type ActivityItem, type ActivityUpdate, type Station } from './systemActivityModel'
import { buildNetwork, geometryHash, networkCentre } from './systemNetworkGeometry'

export type Point3 = { x: number; y: number; z: number }
// Depth is presentation geometry, never a ranking score or passed-gate claim.
const DEPTH: Record<Station, number> = {technical:-95,targets:90,evidence:-55,ai:130,signal:35,order:-105,position:75,exit:-130}
export function spatialPoint(p: {x:number;y:number}, station: Station, compact = false, offset = 0): Point3 {
  const core = networkCentre(compact)
  return { x:(p.x-core.x)*(compact?1.8:1), y:(core.y-p.y)*(compact?1.65:1), z:DEPTH[station]*(compact?.65:1)+offset }
}
export function buildSpatialNetwork(items: ActivityItem[], compact = false) {
  return buildNetwork(items,compact).map(c=>({...c,point:spatialPoint(c,c.station,compact),
    label:spatialPoint({x:c.x,y:c.y-(compact?44:70)},c.station,compact,12),
    nodes:c.nodes.map(n=>({...n,point:spatialPoint(n,c.station,compact,18+geometryHash(n.item.id)%14)})),
  }))
}
export function evidenceDestinations(items: ActivityItem[], updates: ActivityUpdate[], compact = false): Point3[] {
  const clusters = buildSpatialNetwork(items,compact)
  const known = new Map(items.map(i=>[i.id,i]))
  return updates.filter(u=>known.get(u.item.id)?.station===u.item.station).slice(0,4).map(u=> {
    const cluster=clusters.find(c=>c.station===u.item.station)!
    return cluster.nodes.find(n=>n.item.id===u.item.id)?.point || cluster.point
  })
}
export function focusDestination(items:ActivityItem[],id:string|null,compact=false):Point3|null {
  const item=items.find(i=>i.id===id)
  if(!item)return null
  const cluster=buildSpatialNetwork(items,compact).find(c=>c.station===item.station)!
  return cluster.nodes.find(n=>n.item.id===id)?.point || cluster.point
}
/** Presentation-only label offsets. Never moves the underlying evidence nodes. */
export function placeLabel(x:number,y:number,w:number,h:number,width:number,height:number,occupied:{x:number;y:number;w:number;h:number}[]) {
  const overlaps=(p:{x:number;y:number})=>occupied.some(r=>Math.abs(p.x-r.x)<(w+r.w)/2+4&&Math.abs(p.y-r.y)<(h+r.h)/2+4)
  const offsets=[[0,0],[0,h+6],[0,-h-6],[w+6,0],[-w-6,0],[w+6,h+6],[-w-6,h+6],[0,2*(h+6)],[0,-2*(h+6)]]
  const candidates=offsets.map(([dx,dy])=>({x:Math.max(w/2+4,Math.min(width-w/2-4,x+dx)),y:Math.max(h/2+4,Math.min(height-h/2-4,y+dy))}))
  const result=candidates.find(p=>!overlaps(p))||candidates[0]
  occupied.push({...result,w,h});return result
}
/** Small visual arc between observed destinations; does not infer intermediate gates. */
export function evidencePosition(points: Point3[], progress: number): Point3 {
  if(!points.length) return {x:0,y:0,z:60}
  if(points.length===1) return {...points[0]}
  const t=Math.max(0,Math.min(1,Number.isFinite(progress)?progress:0))*(points.length-1)
  const n=Math.min(points.length-2,Math.floor(t)), f=t-n, a=points[n], b=points[n+1]
  return {x:a.x+(b.x-a.x)*f,y:a.y+(b.y-a.y)*f,z:a.z+(b.z-a.z)*f+Math.sin(f*Math.PI)*24}
}
export const WEB3D_BUDGET = { pixelRatio:1.5, maxPixels:1_600_000, frameInterval:1000/30, sweepMs:3200, focusMs:450, stations:STATIONS.length }

/** Decorative gait only. Four alternating feet swing; the others stay in stance.
 * Uses sweep-relative time, never a timer or a claim of worker/trade activity. */
export function spiderStep(elapsedMs:number,leg:number,moving:boolean) {
  if(!moving)return {stride:0,lift:0}
  const elapsed=Number.isFinite(elapsedMs)?Math.max(0,elapsedMs):0
  const phase=(elapsed/640+((leg%4)%2+(leg<4?0:1))*.5)%1
  if(phase<.62)return {stride:4-8*phase/.62,lift:0}
  const swing=(phase-.62)/.38,ease=swing*swing*(3-2*swing)
  return {stride:-4+8*ease,lift:Math.sin(swing*Math.PI)*5}
}

/** Keep orientation when stationary; interpolate the shortest turn on a real sweep. */
export function spiderHeading(from:Point3,to:Point3,current:number) {
  const dx=to.x-from.x,dy=to.y-from.y
  if(Math.hypot(dx,dy)<.0001)return current
  const desired=Math.atan2(-dx,dy),delta=Math.atan2(Math.sin(desired-current),Math.cos(desired-current))
  return current+delta*.28
}
