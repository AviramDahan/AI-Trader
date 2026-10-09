import * as THREE from 'three'
import { buildConstellation, geometryHash } from './systemNetworkGeometry'
import { spatialPoint, spiderStep, type Point3 } from './systemWeb3DModel'

export const vec = (p: Point3) => new THREE.Vector3(p.x,p.y,p.z)
export function disposeObject(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>()
  root.traverse(object=> {
    const renderable=object as THREE.Mesh
    if(renderable.geometry) geometries.add(renderable.geometry)
    if(renderable.material) (Array.isArray(renderable.material)?renderable.material:[renderable.material]).forEach(m=>materials.add(m))
  })
  geometries.forEach(g=>g.dispose()); materials.forEach(m=>m.dispose())
  root.clear()
}
export function lineGeometry(points: THREE.Vector3[]) { return new THREE.BufferGeometry().setFromPoints(points) }

/** Static, bounded silk. Vertices are decoration, not stocks or an execution trace. */
export function createSilk(compact: boolean) {
  const root=new THREE.Group(), groups=new Map<string,THREE.Group>()
  for(const c of buildConstellation(compact)) {
    const group=new THREE.Group(); group.name=c.station; groups.set(c.station,group); root.add(group)
    const extent=compact?76:127
    const points=c.points.map(p=> {
      const dx=(p.x-c.x)/extent,dy=(p.y-c.y)/(extent*.7)
      const depth=32*(1-dx*dx-dy*dy)+Math.sin(dx*5+dy*3)*6
      return vec(spatialPoint(p,c.station,compact,depth))
    })
    const position=new Float32Array(points.flatMap(p=>p.toArray())), sizes=new Float32Array(c.points.map(p=>p.radius*3))
    const particles=new THREE.BufferGeometry()
    particles.setAttribute('position',new THREE.BufferAttribute(position,3));particles.setAttribute('pointSize',new THREE.BufferAttribute(sizes,1))
    const glow=new THREE.ShaderMaterial({transparent:true,depthWrite:false,uniforms:{tint:{value:new THREE.Color(c.color)},opacity:{value:.8}},
      vertexShader:'attribute float pointSize; void main(){ vec4 p=modelViewMatrix*vec4(position,1.0); gl_Position=projectionMatrix*p; gl_PointSize=clamp(pointSize*1800.0/max(1.0,-p.z),3.0,14.0); }',
      fragmentShader:'uniform vec3 tint; uniform float opacity; void main(){ float d=length(gl_PointCoord-vec2(0.5)); float core=1.0-smoothstep(0.06,0.23,d); float halo=1.0-smoothstep(0.1,0.5,d); gl_FragColor=vec4(tint+vec3(core*0.4),(core*0.9+halo*0.35)*opacity); }',
      blending:THREE.AdditiveBlending,
    })
    group.add(new THREE.Points(particles,glow))
    const index=new Map(c.points.map((p,n)=>[p,n]))
    const edges=c.edges.flatMap(e=>[points[index.get(e.a)!],points[index.get(e.b)!]])
    const threads=new THREE.LineBasicMaterial({color:c.color,transparent:true,opacity:.16,depthWrite:false})
    threads.userData.baseOpacity=.16
    group.add(new THREE.LineSegments(lineGeometry(edges),threads))
    const end=vec(spatialPoint(c,c.station,compact))
    for(let n=0;n<3;n++) {
      const start=new THREE.Vector3((n-1)*5,0,24)
      const curve=new THREE.CubicBezierCurve3(start,new THREE.Vector3(end.x*.3,end.y*.16+(n-1)*20,100),
        new THREE.Vector3(end.x*.7,end.y*.9,end.z+(n-1)*12),end.clone().add(new THREE.Vector3((n-1)*4,0,0)))
      const material=new THREE.LineBasicMaterial({color:c.color,transparent:true,opacity:.11,depthWrite:false});material.userData.baseOpacity=.11
      group.add(new THREE.Line(lineGeometry(curve.getPoints(28)),material))
    }
  }
  // Peripheral dust has no labels, interactions, event timers or fake activity.
  const dust=Array.from({length:compact?70:160},(_,n)=> {
    const seed=geometryHash(`silk:${n}`),a=n*2.39996,r=220+seed%470
    return new THREE.Vector3(Math.cos(a)*r,Math.sin(a)*r*.62,-150-(seed%220))
  })
  root.add(new THREE.Points(lineGeometry(dust),new THREE.PointsMaterial({color:'#44776f',size:1.3,transparent:true,opacity:.34,depthWrite:false})))
  return {root,groups}
}

function segment(a: THREE.Vector3,b: THREE.Vector3,r1: number,r2: number,material: THREE.Material) {
  const delta=b.clone().sub(a),mesh=new THREE.Mesh(new THREE.CylinderGeometry(r2,r1,delta.length(),8),material)
  mesh.position.copy(a).add(b).multiplyScalar(.5)
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),delta.normalize())
  return mesh
}
/** Procedural 3D articulated spider, self-contained; no model downloads. */
export function createSpider(compact: boolean) {
  const root=new THREE.Group(),body=new THREE.Group(),legs:THREE.Group[]=[]
  root.name='evidence-spider';body.name='spider-shell';root.add(body)
  const shell=new THREE.MeshStandardMaterial({color:'#183338',metalness:.45,roughness:.38})
  const armour=new THREE.MeshStandardMaterial({color:'#49676a',metalness:.65,roughness:.3})
  const joint=new THREE.MeshStandardMaterial({color:'#a5c9bc',metalness:.55,roughness:.32})
  const trim=new THREE.MeshStandardMaterial({color:'#6ec6b3',emissive:'#163b32',emissiveIntensity:.3,metalness:.5,roughness:.35})
  const eye=new THREE.MeshStandardMaterial({color:'#b5ffe7',emissive:'#52c4a4',emissiveIntensity:1.1,roughness:.25})
  // Shared geometry: poses move rigid links, never allocate GPU buffers per frame.
  const sphere=new THREE.SphereGeometry(1,24,16),eyeGeometry=new THREE.SphereGeometry(1,12,8)
  const jointGeometry=new THREE.SphereGeometry(1,10,8)
  const upperGeometry=new THREE.CylinderGeometry(1.15,1.7,1,10),lowerGeometry=new THREE.CylinderGeometry(.35,1.1,1,10)
  const oval=(x:number,y:number,z:number,sx:number,sy:number,sz:number,material:THREE.Material)=> {
    const mesh=new THREE.Mesh(sphere,material);mesh.position.set(x,y,z);mesh.scale.set(sx,sy,sz);body.add(mesh);return mesh
  }
  // Broad abdomen, distinct thorax and forward head: readable silhouette, not a needle.
  oval(0,-13,9,14.5,18,11,shell);oval(0,9,11,10.5,11,8,armour);oval(0,22,11,7,6,5,shell)
  oval(0,-1,10,7,4,6,armour)
  // Thin raised panel seams; no texture/model downloads or bloom pass.
  for(const side of [-1,1]) {
    const seam=new THREE.CatmullRomCurve3([new THREE.Vector3(side*4,0,17),new THREE.Vector3(side*10,-12,18),new THREE.Vector3(side*6,-27,14)])
    body.add(new THREE.Mesh(new THREE.TubeGeometry(seam,12,.35,5,false),trim))
  }
  const spine=new THREE.CatmullRomCurve3([new THREE.Vector3(0,-28,15),new THREE.Vector3(0,-13,20.3),new THREE.Vector3(0,0,17)])
  body.add(new THREE.Mesh(new THREE.TubeGeometry(spine,12,.25,5,false),joint))
  for(const [x,y,z,size] of [[-2,25,15.5,1.35],[2,25,15.5,1.35],[-4.8,23,14.6,.9],[4.8,23,14.6,.9],[-3.4,20.5,15.6,.75],[3.4,20.5,15.6,.75],[-5.8,20.5,13,.6],[5.8,20.5,13,.6]]) {
    const mesh=new THREE.Mesh(eyeGeometry,eye);mesh.name='spider-eye';mesh.position.set(x,y,z);mesh.scale.setScalar(size);body.add(mesh)
  }
  const up=new THREE.Vector3(0,1,0),delta=new THREE.Vector3()
  const align=(mesh:THREE.Mesh,a:THREE.Vector3,b:THREE.Vector3)=> {
    delta.copy(b).sub(a);mesh.scale.y=delta.length()
    mesh.position.copy(a).add(b).multiplyScalar(.5)
    mesh.quaternion.setFromUnitVectors(up,delta.normalize())
  }
  const rigs:{hip:THREE.Vector3;restKnee:THREE.Vector3;restFoot:THREE.Vector3;upperLength:number;lowerLength:number;upper:THREE.Mesh;lower:THREE.Mesh;knee:THREE.Mesh;foot:THREE.Mesh}[]=[]
  for(let n=0;n<8;n++) {
    const side=n<4?-1:1,row=n%4,y=(1.5-row)*8
    const a=new THREE.Vector3(side*9,y,10),b=new THREE.Vector3(side*[27,36,36,27][row],[29,13,-14,-31][row],25)
    const c=new THREE.Vector3(side*[54,62,59,49][row],[52,30,-32,-52][row],-2)
    const leg=new THREE.Group();leg.name=`spider-leg-${n}`
    const upper=new THREE.Mesh(upperGeometry,armour),lower=new THREE.Mesh(lowerGeometry,shell)
    const hip=new THREE.Mesh(jointGeometry,joint);hip.name=`spider-hip-${n}`;hip.position.copy(a);hip.scale.setScalar(1.8)
    const knee=new THREE.Mesh(jointGeometry,joint);knee.name=`spider-knee-${n}`;knee.scale.setScalar(1.9)
    const foot=new THREE.Mesh(jointGeometry,trim);foot.name=`spider-foot-${n}`;foot.scale.set(.65,1.15,.65)
    leg.add(upper,lower,hip,knee,foot)
    root.add(leg);legs.push(leg)
    const upperLength=a.distanceTo(b),lowerLength=b.distanceTo(c)
    leg.userData.lengths={upper:upperLength,lower:lowerLength}
    rigs.push({hip:a,restKnee:b,restFoot:c,upperLength,lowerLength,upper,lower,knee,foot})
  }
  for(const side of [-1,1]) {
    body.add(segment(new THREE.Vector3(side*3.5,25,9),new THREE.Vector3(side*6,30,7),.8,.55,armour))
    body.add(segment(new THREE.Vector3(side*6,30,7),new THREE.Vector3(side*3,32,6),.55,.2,joint))
  }
  const footTarget=new THREE.Vector3(),axis=new THREE.Vector3(),pole=new THREE.Vector3(),kneePoint=new THREE.Vector3()
  const pose=(elapsedMs=0,moving=false)=> {
    rigs.forEach((r,n)=> {
      const step=spiderStep(elapsedMs,n,moving)
      footTarget.copy(r.restFoot);footTarget.y+=step.stride;footTarget.z+=step.lift
      axis.copy(footTarget).sub(r.hip)
      const distance=Math.max(.0001,Math.min(axis.length(),r.upperLength+r.lowerLength-.0001));axis.normalize()
      // Two-link inverse kinematics: lengths and hips stay fixed while the foot lifts.
      const along=(r.upperLength*r.upperLength-r.lowerLength*r.lowerLength+distance*distance)/(2*distance)
      const height=Math.sqrt(Math.max(0,r.upperLength*r.upperLength-along*along))
      pole.copy(r.restKnee).sub(r.hip);pole.addScaledVector(axis,-pole.dot(axis)).normalize()
      kneePoint.copy(r.hip).addScaledVector(axis,along).addScaledVector(pole,height)
      footTarget.copy(r.hip).addScaledVector(axis,distance)
      r.knee.position.copy(kneePoint);r.foot.position.copy(footTarget)
      align(r.upper,r.hip,kneePoint);align(r.lower,kneePoint,footTarget)
    })
    const elapsed=Number.isFinite(elapsedMs)?Math.max(0,elapsedMs):0
    body.position.z=moving?Math.sin(elapsed*Math.PI/320)*.65:0
    body.rotation.x=moving?Math.sin(elapsed*Math.PI/640)*.012:0
  }
  pose()
  root.scale.setScalar(compact?1.05:.9);root.position.set(0,0,60)
  return {root,legs,pose}
}
