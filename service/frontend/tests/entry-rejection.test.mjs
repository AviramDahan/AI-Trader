import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const bundle=await build({entryPoints:['src/StockEvidence.tsx','src/ScannerDashboard.tsx'],outdir:'unused',
  bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',loader:{'.png':'file'},define:{'import.meta.env.PROD':'false'},
  external:['react','react/jsx-runtime','react-router-dom'],plugins:[{name:'isolated',setup(b){
    b.onResolve({filter:/^\.\/appShared$/},()=>({path:'shared',namespace:'stub'}))
    b.onResolve({filter:/\.css$/},()=>({path:'css',namespace:'stub'}))
    b.onLoad({filter:/.*/,namespace:'stub'},()=>({contents:"export const API_ORIGIN='http://isolated.invalid'; export const useLanguage=()=>({language:'he'}); export const useTheme=()=>({theme:'dark'})"}))
  }}]})
const load=name=>{const m={exports:{}};new Function('require','module','exports',bundle.outputFiles.find(f=>f.path.endsWith(name+'.js')).text)(createRequire(import.meta.url),m,m.exports);return m.exports}
const {StockEvidence}=load('StockEvidence'),{SignalCard}=load('ScannerDashboard')
const signal={id:7,ticker:'TEST',company:'Synthetic',status:'ENTRY_POLICY_REJECTED',action:'BUY',confidence:.91,
  planned_entry:100,current_stop:97.75,original_stop:97.75,weighted_rr:2,
  policy_version:'single_breakout_v1',tp1:104.5,tp2:null,tp3:null,tp1_pct:1,tp2_pct:0,tp3_pct:0,
  entry_rejection_reason:'fill_rr_below_2',technical_json:{target_plan:{policy_version:'single_breakout_v1',
    active_target:104.5,completed_high:99,source_data_at:'2026-10-05T20:05:00Z',rr:[2]}}}
const render=(s=signal,orders=[])=>renderToStaticMarkup(createElement(StockEvidence,{he:true,
  item:{id:'signal:7',ticker:'TEST',state:'blocked',station:'order',signal:s,record:{orders}},
  levels:{},records:[],onClose:()=>{}}))
assert.ok(render().includes('יחס הסיכוי־סיכון במחיר הביצוע נמוך מ־2R'))
const absent={...signal,entry_rejection_reason:null}
assert.ok(render(absent).includes('פירוט הסיבה לא נשמר'))
assert.ok(render(absent,[{id:1,signal_id:7,purpose:'entry',status:'invalid',entry_rejection_reason:'fill_stop_distance_invalid'}]).includes('מרחק הסטופ במחיר הביצוע אינו עומד בהגנות'))
assert.ok(!render(absent,[{id:2,signal_id:8,purpose:'entry',status:'invalid',entry_rejection_reason:'fill_no_longer_above_completed_high'}]).includes('מחיר הביצוע אינו מעל שיא'))
assert.ok(!render({...signal,status:'PENDING_ENTRY'}).includes('יחס הסיכוי־סיכון במחיר הביצוע נמוך'))
assert.ok(!render({...signal,entry_rejection_reason:'<script>private</script>'}).includes('private'))
for(const he of [true,false]) {
  const card=renderToStaticMarkup(createElement(SignalCard,{signal,he}))
  assert.ok(card.includes(he?'יחס הסיכוי־סיכון במחיר הביצוע נמוך מ־2R':'Execution-price reward/risk is below 2R'))
  assert.ok(!card.includes('NaN')&&!card.includes('Infinity'))
  const warning=card.match(/class="scanner-warning">(.*?)<\/p>/s)[1]
  assert.ok(!warning.includes('$')) // Existing quote-price formatting is not changed.
}
console.log('Entry rejection: exact reasons, missing evidence, signal linkage and Hebrew/English rendering PASS')
