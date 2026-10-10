import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import * as THREE from 'three'
import { fixtureResearch,fixtureDashboard } from './system-activity-fixtures.mjs'

const result=await build({entryPoints:['src/systemWeb3DModel.ts','src/systemWeb3DScene.ts','src/systemActivityModel.ts'],
  bundle:true,write:false,outdir:'unused',platform:'node',format:'cjs',external:['three']})
const load=name=> {
  const m={exports:{}}
  const originalRequire=createRequire(import.meta.url)
  new Function('require','module','exports',result.outputFiles.find(f=>f.path.endsWith(name+'.js')).text)(path=>path==='three'?THREE:originalRequire(path),m,m.exports)
  return m.exports
}
const {buildActivity}=load('systemActivityModel')
const {buildSpatialNetwork,evidenceDestinations,evidencePosition,focusDestination,placeLabel,WEB3D_BUDGET}=load('systemWeb3DModel')
const {createSilk,disposeObject}=load('systemWeb3DScene')
const items=buildActivity(fixtureResearch,fixtureDashboard),unchanged=JSON.stringify(items)
let assertions=0
const equal=(a,b)=>{assert.deepEqual(a,b);assertions++}
const check=v=>{assert.ok(v);assertions++}
for(const compact of [false,true]) {
  const graph=buildSpatialNetwork(items,compact)
  equal(graph.flatMap(c=>c.nodes.map(n=>n.item.id)).sort(),items.map(i=>i.id).sort())
  equal(graph,buildSpatialNetwork([...items].reverse(),compact))
  check(new Set(graph.map(c=>c.point.z)).size>1)
  check(graph.flatMap(c=>c.nodes).every(n=>Object.values(n.point).every(Number.isFinite)))
  const crowded=buildSpatialNetwork(Array.from({length:100},(_,n)=>({...items[0],id:`synthetic:${n}`})),compact)
  equal(crowded[0].nodes.length,compact?4:8);equal(crowded[0].omitted,compact?96:92)
  equal(buildSpatialNetwork([],compact).flatMap(c=>c.nodes),[])
  equal(focusDestination(items,null,compact),null)
  equal(focusDestination(items,'missing',compact),null)
  equal(focusDestination(items,graph[0].nodes[0].item.id,compact),graph[0].nodes[0].point)
  const denseItems=Array.from({length:100},(_,n)=>({...items[0],id:`synthetic:${n}`}))
  const omitted=denseItems.find(i=>!crowded[0].nodes.some(n=>n.item.id===i.id))
  equal(focusDestination(denseItems,omitted.id,compact),crowded[0].point)
  const updates=items.map(i=>({key:i.id,item:i}))
  equal(evidenceDestinations(items,updates,compact).length,4)
  equal(evidenceDestinations([],updates,compact),[])
  equal(evidenceDestinations(items,[{key:'bad',item:{...items[0],station:'ai'}}],compact),[])
  equal(evidenceDestinations(items,[updates[0]],compact),[graph[0].nodes[0].point])
  const silk=createSilk(compact)
  equal(silk.groups.size,8)
  let particleCount=0,vertexCount=0,disposedGeometries=0
  const geometries=new Set(),materials=new Set()
  silk.root.traverse(o=> {
    if(o.isPoints)particleCount+=o.geometry.attributes.position.count
    if(o.geometry){geometries.add(o.geometry);vertexCount+=o.geometry.attributes.position.count}
    if(o.material)materials.add(o.material)
  })
  equal(particleCount,compact?390:800)
  check([...silk.groups.values()].every(g=>g.children.filter(c=>c.type==='Line').length===3))
  check(vertexCount<15000)
  geometries.forEach(g=>g.addEventListener('dispose',()=>disposedGeometries++))
  let disposedMaterials=0
  materials.forEach(m=>m.addEventListener('dispose',()=>disposedMaterials++))
  disposeObject(silk.root)
  equal(disposedGeometries,geometries.size);equal(disposedMaterials,materials.size);equal(silk.root.children.length,0)
}
equal(JSON.stringify(items),unchanged) // visual model never mutates source data
const points=[{x:0,y:0,z:60},{x:30,y:40,z:100}]
equal(evidencePosition(points,0),points[0]);equal(evidencePosition(points,1),points[1])
equal(evidencePosition(points,2),points[1]);equal(evidencePosition(points,-1),points[0])
equal(evidencePosition(points,NaN),points[0]);equal(evidencePosition([],0),{x:0,y:0,z:60})
equal(evidencePosition([points[1]],.5),points[1]);check(evidencePosition(points,.5).z>80)
equal(WEB3D_BUDGET.sweepMs,3200);check(WEB3D_BUDGET.pixelRatio<=1.5);equal(WEB3D_BUDGET.frameInterval,1000/30)
equal(WEB3D_BUDGET.focusMs,450)
const occupied=[]
equal(placeLabel(100,100,55,44,380,520,occupied),{x:100,y:100})
equal(placeLabel(133,100,55,44,380,520,occupied),{x:133,y:150})
const edge=placeLabel(2,2,55,44,380,520,occupied)
check(edge.x>=31.5&&edge.y>=26)
const source=readFileSync('src/SystemWeb3D.tsx','utf8'),sceneSource=readFileSync('src/systemWeb3DScene.ts','utf8')
check(!source.includes('fetch(')&&!sceneSource.includes('fetch('))
check(!source.includes('setInterval(')&&!source.includes('Math.random('))
check(source.includes('controls.autoRotate=false') && source.includes('controls.enableDamping=false'))
check(source.includes('renderer.dispose()') && source.includes('renderer.forceContextLoss()') && source.includes('observer.disconnect()'))
check(source.includes('webglcontextlost') && source.includes('setFailed(true)'))
check(source.includes("visibilityState==='hidden'") && source.includes('IntersectionObserver'))
check(source.includes('reduced.matches') && source.includes('WEB3D_BUDGET.maxPixels'))
check(source.includes('if(flight) requestRender()')) // finite camera navigation only
check(source.includes('p.selected!==previousSelected') && source.includes('focusDestination(p.items,p.selected,compact)'))
check(source.includes('element.dataset.cameraMotion'))
check(source.includes('controls.removeEventListener(\'start\',manual)'))
check(source.includes('props.changed]')) // finite highlight cleared without a new provider snapshot
check(source.includes('if(point&&flight)requestRender()')) // sidebar resize preserves finite focus travel
check(source.includes('compact?-220:0')) // mobile card must not occlude the selected node
check(!source.includes('spider') && !sceneSource.includes('createSpider'))
check(!source.includes('animation.points') && !source.includes('sweepKey'))
equal(load('systemWeb3DScene').createSpider,undefined)
equal(load('systemWeb3DModel').spiderStep,undefined)
console.log(`3D geometry, evidence destinations, bounds and GPU-resource disposal: ${assertions} assertions passed`)
