import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { readFileSync } from 'node:fs'
import { fixtureResearch, fixtureDashboard } from './system-activity-fixtures.mjs'
const bundle = await build({entryPoints:['src/SystemActivity.tsx','src/systemActivityModel.ts','src/MiniAppActivity.tsx','src/telegramMiniApp.ts'],outdir:'unused',bundle:true,write:false,
  platform:'node',format:'cjs',jsx:'automatic',external:['react','react/jsx-runtime','react-router-dom'],loader:{'.png':'file'},
  plugins:[{name:'isolated',setup(b){
    b.onResolve({filter:/^\.\/appChrome$/},()=>({path:'chrome',namespace:'stub'}))
    b.onResolve({filter:/^\.\/appShared$/},()=>({path:'shared',namespace:'stub'}))
    b.onResolve({filter:/\.css$/},()=>({path:'css',namespace:'stub'}))
    b.onLoad({filter:/.*/,namespace:'stub'},a=>({contents:a.path==='chrome'?'export const TopbarControls=()=>null':"export const API_ORIGIN='http://isolated.invalid'"}))
  }}]})
const load=name=>{const m={exports:{}};new Function('require','module','exports',bundle.outputFiles.find(f=>f.path.endsWith(name+'.js')).text)(createRequire(import.meta.url),m,m.exports);return m.exports}
const {SystemActivityView}=load('SystemActivity'),{MobileReactors}=load('MiniAppActivity'),{buildActivity,STATIONS}=load('systemActivityModel')
const {installMiniAppBackButton}=load('telegramMiniApp')
let assertions=0
const ok=v=>{assert.ok(v);assertions++},equal=(a,b)=>{assert.deepEqual(a,b);assertions++}
const render=props=>renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/market?miniapp=1']},createElement(SystemActivityView,{he:true,miniApp:true,...props})))
const empty=render({research:null,dashboard:null})
ok(empty.includes('מפת הכורים'));equal((empty.match(/data-reactor=/g)||[]).length,8)
ok(empty.includes('טוען נתונים'));ok(!empty.includes('scanner-hero'));ok(!empty.includes('system-title'));ok(!empty.includes('scanner-tabs'))
equal((empty.match(/mini-reactor-count"><bdi>—/g)||[]).length,8)
const r={...fixtureResearch,generated_at:new Date().toISOString()}
const full=render({research:r,dashboard:fixtureDashboard})
ok(full.includes('מחובר'));ok(full.includes('השוק'));ok(full.indexOf('mini-reactors')<full.indexOf('mini-bottom-nav'))
const items=buildActivity(r,fixtureDashboard),original=JSON.stringify(items)
for(const he of [true,false]) {
  const map=renderToStaticMarkup(createElement(MobileReactors,{he,items,changed:new Set(),updates:[],known:true,available:true,openStation:()=>{},openStock:()=>{}}))
  for(const s of STATIONS)ok(map.includes(`data-reactor="${s}"`))
  ok(map.includes('FOXT'));ok(!map.includes('spider'));ok(!map.includes('animateMotion'))
}
equal(JSON.stringify(items),original)
const failed=render({research:r,dashboard:fixtureDashboard,error:'signal timed out'})
ok(failed.includes('העדכון מתעכב'));ok(!failed.includes('signal timed out'));ok(!failed.includes('is-connected'))
const stale=render({research:fixtureResearch,dashboard:fixtureDashboard});ok(stale.includes('מידע שמור'))
const noRecords=render({research:{generated_at:new Date().toISOString(),records:[]},dashboard:{signals:[],trades:[],market:{is_open:false}}})
equal((noRecords.match(/mini-reactor-count"><bdi>0/g)||[]).length,8)
ok(noRecords.includes('אין רשומות במדגם'))
const calls=[],events=new Map(),button={show:()=>calls.push('show'),hide:()=>calls.push('hide'),onClick:cb=>button.click=cb,offClick:cb=>{if(button.click===cb)button.click=null}}
const win={location:{search:'?miniapp=1'},Telegram:{WebApp:{BackButton:button}},addEventListener:(name,cb)=>events.set(name,cb),removeEventListener:(name,cb)=>{if(events.get(name)===cb)events.delete(name)}}
const cleanup=installMiniAppBackButton(()=>calls.push('back'),win);equal(calls,['show']);button.click();equal(calls,['show','back']);cleanup();equal(calls,['show','back','hide']);equal(button.click,null);equal(events.size,0)
win.Telegram=undefined;const late=installMiniAppBackButton(()=>calls.push('late'),win);win.Telegram={WebApp:{BackButton:button}};events.get('ai-trader:miniapp-ready')();button.click();late();equal(calls.slice(-3),['show','late','hide'])
win.location.search='';const plain=installMiniAppBackButton(()=>{},win);equal(button.click,null);plain()
const css=readFileSync('src/miniAppActivity.css','utf8'),source=readFileSync('src/MiniAppActivity.tsx','utf8')
ok(css.includes('min-height:44px'));ok(css.includes('min-height:48px'));ok(css.includes('grid-template-rows:repeat(4'));ok(css.includes('@media(max-height:680px)'))
ok(source.includes('aria-modal="true"'));ok(source.includes("setAttribute('inert'"));ok(source.includes("e.key !== 'Tab'"));ok(!source.includes('EvidenceSpider'))
for(const forbidden of ['fetch(',"method: 'POST'",'sendMessage','initData','scrollIntoView'])ok(!source.includes(forbidden))
// Numbers are station sequence, not counts; DOM/tab order stays chronological.
for(const he of [true,false]) {
  const map=renderToStaticMarkup(createElement(MobileReactors,{he,items,changed:new Set(),known:true,openStation:()=>{},openStock:()=>{}}))
  const rows=[...map.matchAll(/<article([^>]+)>/g)].map(m=>m[1])
  equal(rows.length,8)
  for(let n=0;n<8;n++) {
    ok(rows[n].includes(`data-reactor="${STATIONS[n]}"`))
    ok(rows[n].includes(`grid-row:${Math.floor(n/2)+1}`))
    ok(rows[n].includes(`grid-column:${n%4===0||n%4===3?1:2}`))
  }
  equal((map.match(/data-flow=/g)||[]).length,7)
  equal((map.match(/data-flow="down"/g)||[]).length,3)
  ok(map.includes(`data-arrow="${he?'←':'→'}"`))
  ok(map.includes(`data-arrow="${he?'→':'←'}"`))
  for(let n=1;n<=8;n++)ok(map.includes(`class="mini-reactor-number" aria-hidden="true">${n}</span>`))
  ok(map.includes(he?'שלב 1:':'Step 1:'))
  ok(map.includes(he?'רשומות':'records'))
}
ok(!empty.includes('תנועת המחשה'));ok(!full.includes('עכביש'))
ok(css.includes('[data-flow=down]'));ok(css.includes('pointer-events:none'))
// Always-visible, bounded, unique ticker preview; no extra tiny touch targets.
const dense=Array.from({length:7},(_,n)=>({...items[0],id:`dense-${n}`,ticker:['ALFA','ALFA','BRK.B','CHAR','DELTA','ECHO','FOXT'][n],station:STATIONS[0]}))
const denseOriginal=JSON.stringify(dense)
for(const he of [true,false]) {
  const map=renderToStaticMarkup(createElement(MobileReactors,{he,items:dense,changed:new Set(),known:true,openStation:()=>{},openStock:()=>{}}))
  const preview=map.match(/class="mini-reactor-stocks"[^>]*>(.*?)<\/span>\s*<\/button>/s)[1]
  ok(preview.includes('ALFA'));ok(preview.includes('BRK.B'));ok(preview.includes('CHAR'))
  equal((preview.match(/title="ALFA"/g)||[]).length,1)
  ok(preview.includes('>+3</bdi>'));ok(!preview.includes('DELTA'))
  ok(map.includes('<bdi>7</bdi>'));equal((map.match(/<button /g)||[]).length,8)
  equal((map.match(/class="mini-reactor-stocks"/g)||[]).length,8)
  ok(!preview.includes('<button'));ok(preview.includes('<bdi'))
}
equal(JSON.stringify(dense),denseOriginal)
ok(!css.includes('.mini-reactor-preview'));ok(!css.match(/mini-reactor-stocks[^}]*display:none/))
ok(css.includes('text-overflow:ellipsis'));ok(css.includes('grid-column:1/-1'))
console.log(`Mobile workspace: ${assertions} assertions passed (synthetic evidence; no network or Telegram delivery)`)
