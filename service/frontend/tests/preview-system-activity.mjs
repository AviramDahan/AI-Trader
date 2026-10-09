/** Local-only visual QA. Synthetic fixtures, GET-only; never connects to Production. */
import { createServer } from 'node:http'
import { build } from 'esbuild'
import { fixtureResearch, fixtureDashboard } from './system-activity-fixtures.mjs'

const result = await build({ stdin: { contents: `
  import React from 'react'; import {createRoot} from 'react-dom/client';
  import {SystemActivity} from './src/SystemActivity'; import './src/index.css';
  if(new URLSearchParams(location.search).get('event-test')==='synthetic') {
    const interval=window.setInterval.bind(window);window.setInterval=(fn,ms,...args)=>interval(fn,ms===60000?2000:ms,...args);
  }
  const dashboard=${JSON.stringify(fixtureDashboard)};
  createRoot(document.getElementById('root')).render(<SystemActivity he={true} dashboard={dashboard}/>);
`, resolveDir: process.cwd(), loader: 'tsx' }, outdir: 'preview-unused', bundle: true, write: false,
  plugins: [{ name: 'local-api-only', setup(b) {
    b.onResolve({filter: /\/appShared$/}, () => ({path:'stub',namespace:'stub'}))
    b.onLoad({filter:/.*/,namespace:'stub'}, () => ({contents:"export const API_ORIGIN=new URLSearchParams(location.search).get('event-test')==='synthetic'?'/fixture-event':'';"}))
  } }] })
const js = result.outputFiles.find(f => f.path.endsWith('.js')).text
const css = result.outputFiles.find(f => f.path.endsWith('.css')).text
let fixturePoll = 0, fixtureEventAt = null
const server = createServer((request,response) => {
  if(request.method !== 'GET') {response.writeHead(405);response.end();return}
  const path = new URL(request.url,'http://127.0.0.1:4318').pathname
  response.setHeader('Cache-Control','no-store')
  if(path === '/api/scanner/research' || path === '/fixture-event/api/scanner/research') {
    const data = {...fixtureResearch,generated_at:new Date().toISOString()}
    if(path.startsWith('/fixture-event/')) {
      if(++fixturePoll===2) fixtureEventAt=new Date().toISOString()
      if(fixtureEventAt) data.records=fixtureResearch.records.map(r=>r.ticker==='ALFA'?{...r,at:fixtureEventAt,rejection:'pre_no_forward_zone',rejection_stage:'targets'}:r)
    }
    response.setHeader('Content-Type','application/json'); response.end(JSON.stringify(data)); return
  }
  if(path === '/preview.js') {response.setHeader('Content-Type','application/javascript');response.end(js);return}
  if(path === '/preview.css') {response.setHeader('Content-Type','text/css');response.end(css);return}
  // Opt-in fixture-only animation test, without changing OS/browser preferences.
  // The production CSS still strictly respects prefers-reduced-motion.
  if(path === '/synthetic-motion.css') {response.setHeader('Content-Type','text/css');response.end('.evidence-motion-enabled .system-crawler{animation:system-evidence-sweep 3.2s linear 1 forwards}.evidence-motion-enabled .system-crawler-leg{animation:system-visual-step 650ms ease-in-out 6 alternate}.system-reduced-note{display:none}');return}
  if(path !== '/') {response.writeHead(404);response.end();return}
  response.setHeader('Content-Type','text/html; charset=utf-8')
  const motionTest = new URL(request.url,'http://127.0.0.1:4318').searchParams.get('motion-test') === 'synthetic'
  const eventTest = new URL(request.url,'http://127.0.0.1:4318').searchParams.get('event-test') === 'synthetic'
  if(eventTest) {fixturePoll=0;fixtureEventAt=null}
  response.end(`<!doctype html><html lang="he" dir="rtl" data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI-Trader — תצוגת בדיקה סינתטית</title><link rel="stylesheet" href="/preview.css">${motionTest ? '<link rel="stylesheet" href="/synthetic-motion.css">' : ''}</head><body><div style="background:#372b10;color:#fde68a;padding:12px;text-align:center;font:14px sans-serif">תצוגת בדיקה מקומית · נתונים סינתטיים בלבד · לא Production${motionTest ? ' · בדיקת אנימציה יזומה על fixtures בלבד' : ''}${eventTest ? ' · עדכון fixture יחיד ב־ALFA, רענון בדיקה כל 2 שניות' : ''}</div><main id="root" style="max-width:1400px;margin:auto;padding:24px"></main><script src="/preview.js"></script></body></html>`)
})
server.listen(4318,'127.0.0.1',()=>console.log('Synthetic read-only UI preview: http://127.0.0.1:4318'))
