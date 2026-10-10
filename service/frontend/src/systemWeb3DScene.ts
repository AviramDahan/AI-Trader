import * as THREE from 'three'
import { buildConstellation, geometryHash } from './systemNetworkGeometry'
import { spatialPoint, type Point3 } from './systemWeb3DModel'

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
