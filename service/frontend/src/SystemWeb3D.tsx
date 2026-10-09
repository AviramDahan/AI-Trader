import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { LABELS, STATE_LABELS, STATE_SYMBOLS, type ActivityItem, type ActivityUpdate, type Station } from './systemActivityModel'
import { buildSpatialNetwork, evidenceDestinations, evidencePosition, focusDestination, placeLabel, spiderHeading, WEB3D_BUDGET, type Point3 } from './systemWeb3DModel'
import { createSilk, createSpider, disposeObject, lineGeometry, vec } from './systemWeb3DScene'

type Props = {
  he:boolean; items:ActivityItem[]; compact:boolean; station:Station|'all'; setStation:(s:Station|'all')=>void
  selected:string|null; select:(id:string)=>void; changed:Set<string>; available:boolean; visible:boolean; zoom:boolean
  moving:boolean; sweepKey:string; updates:ActivityUpdate[]; fallback:ReactNode; resetZoom:()=>void
}
type Runtime = { update:(p:Props)=>void; home:()=>void; rotate:(direction:number)=>void }
export default function SystemWeb3D(props:Props) {
  const {he,items,compact,station,setStation,selected,select,changed,available,fallback}=props
  const host=useRef<HTMLDivElement>(null),labels=useRef(new Map<string,HTMLElement>()),runtime=useRef<Runtime>()
  const latest=useRef(props);latest.current=props
  const [failed,setFailed]=useState(false),[ready,setReady]=useState(false)
  const clusters=useMemo(()=>buildSpatialNetwork(items,compact),[items,compact])
  const t=(a:string,b:string)=>he?a:b
  useEffect(()=> {
    if(failed)return
    const element=host.current
    if(!element) return
    let renderer:THREE.WebGLRenderer
    try { renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'low-power'}) }
    catch { setFailed(true);return }
    let disposed=false,raf=0,width=1,height=1,frames=0,lastFrame=-Infinity,inView=true
    let animation:{points:Point3[];start:number}|null=null,seenKey=latest.current.sweepKey
    let previousZoom=false,previousStation:Station|'all'='all',previousSelected:string|null=null
    let flight:{eye:THREE.Vector3;target:THREE.Vector3;endEye:THREE.Vector3;endTarget:THREE.Vector3;start:number}|null=null
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(42,1,1,5000)
    renderer.setClearColor(0x000000,0);renderer.outputColorSpace=THREE.SRGBColorSpace
    renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.2
    renderer.domElement.setAttribute('aria-label',he?'מרחב תלת־ממד: גררו לסיבוב, שתי אצבעות להתקרבות':'3D space: drag to orbit, pinch to zoom')
    renderer.domElement.setAttribute('aria-hidden','true') // semantic stock/station buttons are separate HTML
    element.prepend(renderer.domElement)
    scene.add(new THREE.HemisphereLight('#bce5da','#0b1620',2.2))
    const keyLight=new THREE.DirectionalLight('#ddfff1',3.8);keyLight.position.set(-240,300,550);scene.add(keyLight)
    const rimLight=new THREE.DirectionalLight('#6b91cf',2.7);rimLight.position.set(360,-120,-100);scene.add(rimLight)
    const silk=createSilk(compact),spider=createSpider(compact);scene.add(silk.root,spider.root)
    const core=new THREE.Group()
    for(const radius of [86,96,103]) {
      const ring=new THREE.Mesh(new THREE.TorusGeometry(radius,.3,4,96),new THREE.MeshBasicMaterial({color:'#548c7e',transparent:true,opacity:.26}))
      ring.position.z=-12;core.add(ring)
    }
    scene.add(core)
    let stocks=new THREE.Group();scene.add(stocks)
    let projected=new Map<string,Point3>(),activeNodes=0
    const controls=new OrbitControls(camera,renderer.domElement)
    controls.autoRotate=false;controls.enableDamping=false;controls.enablePan=false
    controls.rotateSpeed=.45;controls.zoomSpeed=.65
    controls.minPolarAngle=.75;controls.maxPolarAngle=2.25;controls.minAzimuthAngle=-.9;controls.maxAzimuthAngle=.9
    controls.minDistance=compact?420:320;controls.maxDistance=compact?2500:2300
    const reduced=window.matchMedia('(prefers-reduced-motion:reduce)')
    // Only the explicitly labelled synthetic preview may force motion for QA.
    const forcedMotion=!!document.querySelector('link[href="/synthetic-motion.css"]')
    const canMove=()=>!reduced.matches||forcedMotion
    const canDraw=()=>!disposed&&document.visibilityState!=='hidden'&&inView
    const home=()=> {
      flight=null;element.dataset.cameraMotion='resting'
      const aspect=width/height
      const distance=compact?Math.max(1600,800/Math.max(.35,aspect)):Math.max(1050,620/Math.max(.55,aspect))
      controls.target.set(0,0,0);camera.position.set(compact?40:145,compact?50:155,distance)
      controls.update();requestRender()
    }
    const finishCamera=()=> {
      if(flight){camera.position.copy(flight.endEye);controls.target.copy(flight.endTarget);flight=null;controls.update()}
      element.dataset.cameraMotion='resting'
    }
    const focus=(point:Point3,animate=true)=> {
      // Frame the selected node above the nonmodal mobile summary, not behind it.
      const endTarget=vec(point).add(new THREE.Vector3(0,compact?-220:0,0)),endEye=endTarget.clone().add(new THREE.Vector3(30,40,compact?850:650))
      if(animate&&canMove()&&canDraw()) {
        flight={eye:camera.position.clone(),target:controls.target.clone(),endEye,endTarget,start:performance.now()}
      } else {flight=null;camera.position.copy(endEye);controls.target.copy(endTarget);controls.update()}
      requestRender()
    }
    const projectLabels=()=> {
      camera.updateMatrixWorld()
      const projectedPoint=new THREE.Vector3()
      const occupied:{x:number;y:number;w:number;h:number}[]=[]
      const ordered=[...projected].sort(([a],[b])=>Number(b.startsWith('station:'))-Number(a.startsWith('station:'))||Number(b===latest.current.selected)-Number(a===latest.current.selected))
      for(const [id,point] of ordered) {
        const label=labels.current.get(id);if(!label)continue
        projectedPoint.copy(vec(point)).project(camera)
        const x=(projectedPoint.x*.5+.5)*width,y=(-projectedPoint.y*.5+.5)*height
        const outside=projectedPoint.z<-1||projectedPoint.z>1||x<8||x>width-8||y<8||y>height-8
        label.style.visibility=outside?'hidden':'visible'
        const position=outside||id==='core'?{x,y}:placeLabel(x,y,label.offsetWidth,label.offsetHeight,width,height,occupied)
        label.style.transform=`translate(${position.x}px,${position.y}px) translate(-50%,-50%)`
        label.style.zIndex=String(Math.round((1-projectedPoint.z)*1000)+10)
      }
    }
    const draw=(now:number)=> {
      raf=0
      if(!canDraw()) return
      if(now-lastFrame<WEB3D_BUDGET.frameInterval && (animation||flight)) {requestRender();return}
      lastFrame=now
      if(flight) {
        const progress=Math.min(1,(now-flight.start)/WEB3D_BUDGET.focusMs),ease=1-Math.pow(1-progress,3)
        camera.position.lerpVectors(flight.eye,flight.endEye,ease);controls.target.lerpVectors(flight.target,flight.endTarget,ease)
        if(progress>=1)flight=null
        controls.update()
      }
      element.dataset.cameraMotion=flight?'active':'resting'
      if(animation) {
        const progress=Math.min(1,(now-animation.start)/WEB3D_BUDGET.sweepMs)
        const point=evidencePosition(animation.points,progress);spider.root.position.copy(vec(point))
        const tangent=evidencePosition(animation.points,Math.min(1,progress+.02))
        if(progress<1) spider.root.rotation.z=spiderHeading(point,tangent,spider.root.rotation.z)
        spider.pose(now-animation.start,progress<1)
        if(progress>=1) animation=null
      }
      element.dataset.motion=animation?'active':'resting'
      projectLabels()
      try {renderer.render(scene,camera)} catch {finish();setFailed(true);return}
      frames++
      element.dataset.renderFrames=String(frames);element.dataset.drawCalls=String(renderer.info.render.calls)
      if(animation||flight) requestRender()
    }
    function requestRender() { if(!raf&&canDraw())raf=window.requestAnimationFrame(draw) }
    const finish=()=> {
      if(animation) spider.root.position.copy(vec(animation.points.at(-1)!))
      animation=null;spider.pose();element.dataset.motion='resting'
    }
    const update=(p:Props)=> {
      // Rebuild bounded stock geometry only, not the decorative field or renderer.
      scene.remove(stocks);disposeObject(stocks);stocks=new THREE.Group();scene.add(stocks)
      const groups=buildSpatialNetwork(p.items,compact);projected=new Map([['core',{x:0,y:-128,z:35}]])
      activeNodes=0
      const sphereGeometry=new THREE.SphereGeometry(4,12,8),ringGeometry=new THREE.TorusGeometry(9,.45,4,24)
      for(const cluster of groups) {
        projected.set(`station:${cluster.station}`,cluster.label)
        for(const node of cluster.nodes) {
          activeNodes++;projected.set(node.item.id,{...node.point,y:node.point.y-45})
          const color=node.item.state==='blocked'?'#fb7185':node.item.state==='uncertain'?'#fbbf24':cluster.color
          const material=new THREE.MeshBasicMaterial({color})
          const dot=new THREE.Mesh(sphereGeometry,material);dot.position.copy(vec(node.point));stocks.add(dot)
          const fresh=p.available&&p.changed.has(node.item.id)
          const ring=new THREE.Mesh(ringGeometry,new THREE.MeshBasicMaterial({color,transparent:true,opacity:p.selected===node.item.id||fresh ? .95 : .5}))
          if(fresh)ring.scale.setScalar(1.4)
          ring.position.copy(vec(node.point));stocks.add(ring)
          const curve=new THREE.QuadraticBezierCurve3(vec(cluster.point),vec({...node.point,y:node.point.y+24,z:node.point.z+8}),vec(node.point))
          stocks.add(new THREE.Line(lineGeometry(curve.getPoints(8)),new THREE.LineBasicMaterial({color:cluster.color,transparent:true,opacity:.3})))
        }
      }
      // Empty geometry must also be released when no stocks exist.
      if(!activeNodes) {sphereGeometry.dispose();ringGeometry.dispose()}
      for(const [name,group] of silk.groups) {
        const dim=p.station!=='all'&&p.station!==name
        const fresh=p.available&&p.items.some(i=>i.station===name&&p.changed.has(i.id))
        group.traverse(object=> {
          const material=(object as THREE.Mesh).material as THREE.Material|undefined
          if(!material)return
          if(material instanceof THREE.ShaderMaterial) material.uniforms.opacity.value=dim?.15:fresh?1:.8
          else material.opacity=Math.min(1,(material.userData.baseOpacity||.22)*(dim?.22:fresh?1.8:1))
        })
      }
      if(p.sweepKey && p.sweepKey!==seenKey) {
        seenKey=p.sweepKey
        const destinations=evidenceDestinations(p.items,p.updates,compact)
        if(p.moving && p.available && p.visible && inView && destinations.length) {
          const points=[{...spider.root.position},...destinations]
          if(canMove()) animation={points,start:performance.now()}
          else {animation=null;spider.root.position.copy(vec(points.at(-1)!))}
        }
      }
      if(!p.moving||!p.available||!p.visible) finish()
      if(p.selected!==previousSelected) {
        previousSelected=p.selected
        const point=focusDestination(p.items,p.selected,compact)
        if(point)focus(point);else home()
      }
      if((p.zoom!==previousZoom||p.station!==previousStation)&&!p.selected) {
        previousZoom=p.zoom;previousStation=p.station
        if(p.zoom) {
          const target=p.station==='all'?new THREE.Vector3():vec(groups.find(c=>c.station===p.station)!.point)
          controls.target.copy(target);camera.position.copy(target).add(new THREE.Vector3(65,80,compact?630:590));controls.update()
        } else home()
      }
      previousZoom=p.zoom;previousStation=p.station
      element.dataset.stockCount=String(activeNodes);requestRender()
    }
    const resize=()=> {
      const bounds=element.getBoundingClientRect();width=Math.max(1,bounds.width);height=Math.max(1,bounds.height)
      const ratio=Math.min(window.devicePixelRatio||1,WEB3D_BUDGET.pixelRatio,Math.sqrt(WEB3D_BUDGET.maxPixels/(width*height)))
      renderer.setPixelRatio(ratio);renderer.setSize(width,height,false)
      camera.aspect=width/height;camera.updateProjectionMatrix();element.dataset.pixelRatio=ratio.toFixed(2)
      const point=focusDestination(latest.current.items,latest.current.selected,compact)
      // Opening the desktop summary resizes the canvas; do not skip its focus transition.
      if(point&&flight)requestRender();else if(point)focus(point,false);else if(!previousZoom)home();else requestRender()
    }
    const lose=(event:Event)=>{event.preventDefault();finish();finishCamera();setFailed(true)}
    const visibility=()=>{if(document.visibilityState==='hidden'){finish();finishCamera();window.cancelAnimationFrame(raf);raf=0}else requestRender()}
    const reduce=()=>{if(!canMove()){finish();finishCamera()}requestRender()}
    const manual=()=>{flight=null;element.dataset.cameraMotion='resting'}
    controls.addEventListener('start',manual)
    controls.addEventListener('change',requestRender)
    renderer.domElement.addEventListener('webglcontextlost',lose)
    document.addEventListener('visibilitychange',visibility);reduced.addEventListener('change',reduce)
    const observer=new ResizeObserver(resize);observer.observe(element)
    const intersection=new IntersectionObserver(entries=> {
      inView=entries[0]?.isIntersecting??false
      if(!inView){finish();finishCamera();window.cancelAnimationFrame(raf);raf=0}else requestRender()
    });intersection.observe(element)
    runtime.current={update,home,rotate:direction=>{manual();controls.rotateLeft(direction*.18);controls.update();requestRender()}}
    resize();update(latest.current);element.dataset.renderer='webgl2';setReady(true)
    return ()=> {
      disposed=true;window.cancelAnimationFrame(raf);runtime.current=undefined
      observer.disconnect();intersection.disconnect();controls.removeEventListener('change',requestRender);controls.removeEventListener('start',manual);controls.dispose()
      document.removeEventListener('visibilitychange',visibility);reduced.removeEventListener('change',reduce)
      renderer.domElement.removeEventListener('webglcontextlost',lose)
      disposeObject(scene);renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove()
    }
  },[compact,failed])
  useEffect(()=>{runtime.current?.update(props)},[props.items,props.selected,props.station,props.zoom,props.moving,props.sweepKey,props.available,props.visible,props.changed])
  if(failed)return <><p className="system-3d-fallback" role="status">{t('תלת־ממד אינו זמין במכשיר זה. המפה הדו־ממדית והנתונים נשארים זמינים.','3D is unavailable on this device. The 2D map and data remain available.')}</p>{fallback}</>
  return <div className={`system-web3d ${compact?'compact':''} ${selected?'is-focused':''}`} role="group" aria-label={t('מפת תחנות אינטראקטיבית — רשת מניות בתלת־ממד','Interactive station map — 3D stock network')}>
    <div className="system-web3d-stage" ref={host}>
      <div className="system-3d-label-layer">
        <div className="system-3d-core-label" ref={e=>{if(e)labels.current.set('core',e);else labels.current.delete('core')}} aria-hidden="true"><strong>AI TRADER</strong><span>EVIDENCE NETWORK</span></div>
        {clusters.map(c=><div key={c.station}>
          <button dir={he?'rtl':'ltr'} className={`system-3d-station ${available&&items.some(i=>i.station===c.station&&changed.has(i.id))?'system-new-evidence':''}`} ref={e=>{const key=`station:${c.station}`;if(e)labels.current.set(key,e);else labels.current.delete(key)}}
            style={{color:c.color}} aria-label={`${LABELS[c.station][he?0:1]}: ${c.total}`} aria-pressed={station===c.station}
            onClick={()=>setStation(station===c.station?'all':c.station)}><small>{String(clusters.indexOf(c)+1).padStart(2,'0')}</small><span>{LABELS[c.station][he?0:1]}</span><bdi>{c.total}</bdi>{c.omitted>0&&<em>+{c.omitted}</em>}</button>
          {c.nodes.map(n=><button key={n.item.id} ref={e=>{if(e)labels.current.set(n.item.id,e);else labels.current.delete(n.item.id)}}
            className={`system-3d-stock state-${n.item.state} ${available&&changed.has(n.item.id)?'system-arrival':''}`} style={{color:c.color}}
            aria-label={`${t('מסלול מניה','Stock journey')}: ${n.item.ticker} · ${STATE_LABELS[n.item.state][he?0:1]}`} aria-pressed={selected===n.item.id}
            title={`${n.item.company} · ${STATE_LABELS[n.item.state][he?0:1]}`} onClick={()=>select(n.item.id)}><span aria-hidden="true">{STATE_SYMBOLS[n.item.state]}</span><bdi>{n.item.ticker.slice(0,10)}</bdi></button>)}
        </div>)}
      </div>
    </div>
    {!ready&&<p className="system-3d-loading" role="status">{t('מכין את המרחב…','Preparing the space…')}</p>}
    <div className="system-3d-hud"><span><bdi>3D</bdi> · {t('מרחב ראיות','EVIDENCE SPACE')}</span><p>{t('גרירה לסיבוב · שתי אצבעות להתקרבות','Drag to orbit · pinch to zoom')}</p>
      <div><button type="button" aria-label={t('סיבוב המפה שמאלה','Rotate map left')} onClick={()=>runtime.current?.rotate(-1)}>↶</button><button type="button" aria-label={t('סיבוב המפה ימינה','Rotate map right')} onClick={()=>runtime.current?.rotate(1)}>↷</button><button type="button" onClick={()=>{props.resetZoom();runtime.current?.home()}}>{t('איפוס מבט','Reset view')}</button></div>
    </div>
  </div>
}
