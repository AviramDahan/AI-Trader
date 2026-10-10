/** Local-only visual QA. Synthetic fixtures, GET-only; never connects to Production. */
import { createServer } from 'node:http'
import { build } from 'esbuild'
import { fixtureResearch, fixtureDashboard } from './system-activity-fixtures.mjs'

const compilePreview = async (unavailable=false) => build({ stdin: { contents: `
  import React from 'react'; import {createRoot} from 'react-dom/client';
  import {SystemActivity,SystemActivityView} from './src/SystemActivity'; import './src/index.css';
  import {buildActivity,STATIONS} from './src/systemActivityModel';
  if(new URLSearchParams(location.search).get('motion-test')==='synthetic') {
    const media=window.matchMedia.bind(window);
    window.matchMedia=q=>q==='(prefers-reduced-motion: reduce)'?{matches:false,media:q,addEventListener(){},removeEventListener(){}}:media(q);
  }
  if(new URLSearchParams(location.search).get('event-test')==='synthetic') {
    const interval=window.setInterval.bind(window);window.setInterval=(fn,ms,...args)=>interval(fn,ms===60000?2000:ms,...args);
  }
  const dashboard=${JSON.stringify(fixtureDashboard)};
  const density=new URLSearchParams(location.search).get('density-test')==='synthetic';
  function DenseFixture() {
    const [selected,setSelected]=React.useState(null),[station,setStation]=React.useState('all');
    const research={...${JSON.stringify(fixtureResearch)},generated_at:new Date().toISOString()};
    const base=buildActivity(research,dashboard);
    const items=STATIONS.flatMap((s,i)=>Array.from({length:8},(_,n)=>({...base.find(v=>v.station===s),id:'dense:'+i+':'+n,ticker:'TEST'+n})));
    return <><p className="scanner-warning">DENSE FIXTURE · 64 רשומות סינתטיות · לא פעילות אמיתית</p><SystemActivityView he={true} research={research} dashboard={dashboard} items={items} selected={selected} setSelected={setSelected} station={station} setStation={setStation}/></>;
  }
  createRoot(document.getElementById('root')).render(density?<DenseFixture/>:<SystemActivity he={true} dashboard={dashboard}/>);
`, resolveDir: process.cwd(), loader: 'tsx' }, outdir: 'preview-unused', loader:{'.png':'file'}, bundle: true, write: false,
  plugins: [{ name: 'local-api-only', setup(b) {
    b.onResolve({filter: /\/appShared$/}, () => ({path:'stub',namespace:'stub'}))
    b.onLoad({filter:/.*/,namespace:'stub'}, () => ({contents:"export const API_ORIGIN=new URLSearchParams(location.search).get('event-test')==='synthetic'?'/fixture-event':'';"}))
  } },{name:'synthetic-unsupported-gpu',setup(b) {
    if(!unavailable)return
    b.onResolve({filter:/^three$/},args=>args.importer.endsWith('SystemWeb3D.tsx')?{path:'gpu-fixture',namespace:'gpu-fixture'}:null)
    b.onLoad({filter:/.*/,namespace:'gpu-fixture'},()=>({contents:"export * from 'three'; export class WebGLRenderer { constructor(){throw new Error('Synthetic unsupported GPU')} }",resolveDir:process.cwd()}))
  }}] })
const result=await compilePreview(),gpuFallback=await compilePreview(true)
const js = result.outputFiles.find(f => f.path.endsWith('.js')).text
const fallbackJs = gpuFallback.outputFiles.find(f => f.path.endsWith('.js')).text
const css = result.outputFiles.find(f => f.path.endsWith('.css')).text
let fixturePoll = 0, fixtureEventAt = null
const server = createServer((request,response) => {
  if(request.method !== 'GET') {response.writeHead(405);response.end();return}
  const path = new URL(request.url,'http://127.0.0.1:4318').pathname
  response.setHeader('Cache-Control','no-store')
  const image=result.outputFiles.find(f=>f.path.endsWith('.png') && path==='/'+f.path.split(/[\\/]/).at(-1))
  if(image) {response.setHeader('Content-Type','image/png');response.end(image.contents);return}
  if(path === '/api/scanner/research' || path === '/fixture-event/api/scanner/research') {
    const data = {...fixtureResearch,generated_at:new Date().toISOString()}
    if(path.startsWith('/fixture-event/')) {
      if(++fixturePoll===2) fixtureEventAt=new Date().toISOString()
      if(fixtureEventAt) data.records=fixtureResearch.records.map(r=>r.ticker==='ALFA'?{...r,at:fixtureEventAt,rejection:'pre_no_forward_zone',rejection_stage:'targets'}:r)
    }
    response.setHeader('Content-Type','application/json'); response.end(JSON.stringify(data)); return
  }
  if(path === '/preview.js') {response.setHeader('Content-Type','application/javascript');response.end(js);return}
  if(path === '/preview-fallback.js') {response.setHeader('Content-Type','application/javascript');response.end(fallbackJs);return}
  if(path === '/preview.css') {response.setHeader('Content-Type','text/css');response.end(css);return}
  if(path !== '/') {response.writeHead(404);response.end();return}
  response.setHeader('Content-Type','text/html; charset=utf-8')
  const eventTest = new URL(request.url,'http://127.0.0.1:4318').searchParams.get('event-test') === 'synthetic'
  const motionTest = new URL(request.url,'http://127.0.0.1:4318').searchParams.get('motion-test') === 'synthetic'
  const gpuTest = new URL(request.url,'http://127.0.0.1:4318').searchParams.get('renderer-test') === 'unavailable'
  const lossTest = new URL(request.url,'http://127.0.0.1:4318').searchParams.get('renderer-test') === 'context-loss'
  if(eventTest) {fixturePoll=0;fixtureEventAt=null}
  response.end(`<!doctype html><html lang="he" dir="rtl" data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI-Trader — תצוגת בדיקה סינתטית</title><link rel="stylesheet" href="/preview.css">${motionTest?'<style>.system-evidence-spider.is-walking .system-spider-leg{animation:system-spider-step .32s ease-in-out 10}.system-evidence-spider.is-walking .system-spider-leg.gait-1{animation-direction:reverse}</style>':''}</head><body><div style="background:#211c11;color:#cbbb91;padding:9px;text-align:center;font:11px sans-serif">PREVIEW · נתונים סינתטיים בלבד · לא Production${eventTest ? ' · עדכון ALFA יחיד' : ''}${motionTest?' · בדיקת תנועה סינתטית':''}${gpuTest?' · בדיקת GPU לא זמין':''}${lossTest?` · <button type="button" onclick="document.querySelector('.system-web3d canvas')?.getContext('webgl2')?.getExtension('WEBGL_lose_context')?.loseContext()">בדיקת אובדן GPU — fixture בלבד</button>`:''}</div><main id="root" style="max-width:1400px;margin:auto;padding:clamp(8px,2vw,28px)"></main><script src="${gpuTest?'/preview-fallback.js':'/preview.js'}"></script></body></html>`)
})
server.listen(4318,'127.0.0.1',()=>console.log('Synthetic read-only UI preview: http://127.0.0.1:4318'))
