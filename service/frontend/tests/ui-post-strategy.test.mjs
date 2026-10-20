// Synthetic, read-only regression fixtures. Never calls the API or Telegram.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Link, MemoryRouter } from 'react-router-dom'
import { candidate, fixtureDashboard } from './system-activity-fixtures.mjs'
const bundle = await build({entryPoints:['src/SystemActivity.tsx','src/StockEvidence.tsx','src/systemActivityModel.ts','src/scannerNavigation.ts','src/MiniWorkspaceNav.tsx'],
  outdir:'unused',bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',
  external:['react','react/jsx-runtime','react-router-dom'],plugins:[{name:'isolated',setup(b){
    b.onResolve({filter:/^\.\/appShared$/},()=>({path:'shared',namespace:'stub'}))
    b.onResolve({filter:/^\.\/appChrome$/},()=>({path:'chrome',namespace:'stub'}))
    b.onResolve({filter:/\.css$/},()=>({path:'css',namespace:'stub'}))
    b.onLoad({filter:/.*/,namespace:'stub'},a=>({contents:a.path==='shared'?"export const API_ORIGIN='http://isolated.invalid'":a.path==='chrome'?'export const TopbarControls=()=>null':''}))
  }}]})
const load=name=>{const m={exports:{}};new Function('require','module','exports',bundle.outputFiles.find(f=>f.path.endsWith(name+'.js')).text)(createRequire(import.meta.url),m,m.exports);return m.exports}
const { StockEvidence }=load('StockEvidence'),{SystemActivityView,activityLevels}=load('SystemActivity'),{candidateItem}=load('systemActivityModel')
const {scannerRecordPath,revealScannerRecord}=load('scannerNavigation')
assert.equal(scannerRecordPath('trade',50,true,'?miniapp=1'),'/market?tab=results&miniapp=1#trade-50')
assert.equal(scannerRecordPath('signal',2,false,''),'/market?tab=signals#signal-2')
assert.equal(scannerRecordPath('signal','../secret',false,''),null)
assert.equal(scannerRecordPath('trade',0,false,''),null)
const linked=renderToStaticMarkup(createElement(MemoryRouter,{basename:'/AI-Trader',initialEntries:['/AI-Trader/market']},
  createElement(Link,{to:scannerRecordPath('trade',50,true,'?miniapp=1')},'Trade')))
assert.ok(linked.includes('href="/AI-Trader/market?tab=results&amp;miniapp=1#trade-50"'))
let seen=[]
const parent={tagName:'DETAILS',open:false,parentElement:null}
const node={tagName:'DETAILS',open:false,parentElement:parent,setAttribute:(...v)=>seen.push(v),scrollIntoView:()=>seen.push('scroll'),focus:()=>seen.push('focus')}
assert.equal(revealScannerRecord('#trade-50',{getElementById:()=>node}),true)
assert.ok(node.open&&parent.open)
assert.deepEqual(seen,[['tabindex','-1'],'scroll','focus'])
assert.equal(revealScannerRecord('#trade-51',{getElementById:()=>null}),false)
assert.equal(revealScannerRecord('#../../secret',{getElementById:()=>{throw new Error('must not access DOM')}}),false)
const at='2026-10-09T15:00:00Z'
const check={phase:'pre_ai',outcome:'REJECT',decided_at:at,quote:{price:74.94},minimum_rr:2,
  rejection_reason:'invalid_rounded_levels',rejection_detail:['target_buffer_reaches_entry'],
  geometry:{stop_rounded:73.05,target_rounded:74.8,rr_rounded:-.07}}
const skipped=candidateItem(candidate('SKIP',{rejection:'pre_invalid_rounded_levels',rejection_stage:'targets',target_checks:[check],reviews:[{result:'early_skip',attempts:0,at}]}))
const render=(item,he=true)=>renderToStaticMarkup(createElement(StockEvidence,{item,he,records:[],levels:activityLevels(item),onClose:()=>{}}))
const html=render(skipped)
assert.ok(!html.includes('נשמרו ניסיונות סקירה'),'early_skip with zero attempts must not claim an AI attempt')
assert.ok(html.includes('לא נוצרה תוכנית כניסה מאושרת'))
assert.ok(!html.includes('סטופ נוכחי / שנבדק'))
assert.ok(!html.includes('היחס שנשמר בתוכנית'))
assert.equal(activityLevels(skipped).rr,undefined,'rejected geometry is not an approved plan RR')
assert.ok(html.includes('73.05')&&html.includes('74.80'),'rejected check evidence remains available')
for(const he of [true,false]) {
  const ai=candidateItem(candidate('CALL',{reviews:[{result:'error',attempts:1,at}]}))
  assert.ok(render(ai,he).includes(he?'נשמרו ניסיונות סקירה':'Review attempts retained'))
  const hold=candidateItem(candidate('HOLD',{ai_decision:{action:'HOLD',confidence:.9},reviews:[{result:'validated',attempts:1,at}]}))
  assert.ok(render(hold,he).includes(he?'המתנה':'Hold'))
  const missing=renderToStaticMarkup(createElement(MemoryRouter,{},createElement(SystemActivityView,{he,research:null,dashboard:fixtureDashboard})))
  assert.match(missing,/data-count-known="false"/,'missing research must not display zero as a verified station count')
  assert.ok(missing.includes(he?'לא זמין':'Unavailable'))
}
const {stationKnowledge}=load('systemActivityModel')
const emptyResearch={records:[],generated_at:new Date().toISOString()}
assert.equal(stationKnowledge(null,fixtureDashboard).technical,false)
assert.equal(stationKnowledge(null,fixtureDashboard).position,true)
assert.equal(stationKnowledge(emptyResearch,null).technical,true)
assert.equal(stationKnowledge({...emptyResearch,generated_at:'invalid'},fixtureDashboard).technical,false)
assert.equal(stationKnowledge({...emptyResearch,generated_at:'2099-01-01T00:00:00Z'},fixtureDashboard).technical,false)
const verifiedEmpty=renderToStaticMarkup(createElement(MemoryRouter,{},createElement(SystemActivityView,{
  he:true,research:emptyResearch,dashboard:{trades:[],signals:[]}})))
assert.ok(verifiedEmpty.includes('data-count-known="true"'))
assert.ok(verifiedEmpty.includes('אין מניות במדגם'))
console.log('Post-strategy UI: zero-attempt AI, rejected/approved plan separation and unknown station counts passed')
