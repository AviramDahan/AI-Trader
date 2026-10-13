// Retained synthetic evidence only. No providers, model calls or Telegram.
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {readFileSync} from 'node:fs'
import {candidate,fixtureResearch,fixtureDashboard} from './system-activity-fixtures.mjs'
const bundle=await build({entryPoints:['src/activityExplanation.ts','src/activityReasons.ts','src/systemActivityModel.ts','src/BlockerExplanation.tsx','src/MiniAppActivity.tsx'],
 outdir:'unused',bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react/jsx-runtime','react-router-dom'],
 plugins:[{name:'isolated',setup(b){
  b.onResolve({filter:/^\.\/appChrome$/},()=>({path:'chrome',namespace:'stub'}))
  b.onResolve({filter:/\.css$/},()=>({path:'css',namespace:'stub'}))
  b.onLoad({filter:/.*/,namespace:'stub'},()=>({contents:'export const TopbarControls=()=>null'}))
 }}]})
const load=name=>{const m={exports:{}};new Function('require','module','exports',bundle.outputFiles.find(f=>f.path.endsWith(name+'.js')).text)(createRequire(import.meta.url),m,m.exports);return m.exports}
const {explainActivity,itemReasonCodes,linkedItemOrders,STATION_GUIDES,activityStatusLabel}=load('activityExplanation')
const {REASON_DETAILS,reasonDefinition}=load('activityReasons')
const {buildActivity,candidateItem,STATIONS}=load('systemActivityModel')
const {ActivityExplanation}=load('BlockerExplanation'),{MiniStockList}=load('MiniAppActivity')
let assertions=0
const ok=v=>{assert.ok(v);assertions++},eq=(a,b)=>{assert.deepEqual(a,b);assertions++}
const item=changes=>candidateItem(candidate('TEST',changes))
const markup=(i,he)=>renderToStaticMarkup(createElement(ActivityExplanation,{item:i,he}))
const check={phase:'pre_ai',outcome:'REJECT',rejection_reason:'nearest_resistance_below_2r',minimum_rr:2,
 quote:{price:100,as_of:'2026-10-09T15:00:00Z'},geometry:{rr_rounded:1.72,nearest_resistance:{low:105.3}}}
const blocked=item({rejection:'pre_nearest_resistance_below_2r',rejection_stage:'targets',target_checks:[check]})
const original=JSON.stringify(blocked)
for(const he of [true,false]){
 const e=explainActivity(blocked,he),html=markup(blocked,he)
 ok(e.title.includes(he?'התנגדות':'resistance'));ok(e.detail.includes(he?'לא מדלגים':'not substituted'))
 ok(html.includes('1.72R')&&html.includes('2.00R')&&html.includes('100.00'))
 const list=renderToStaticMarkup(createElement(MiniStockList,{he,rows:[blocked],known:true,onOpen:()=>{}}))
 ok(list.includes(e.title));ok(list.includes('mini-stock-reason'))
 ok(!list.includes('pre_nearest_resistance_below_2r'));ok(!html.includes('$'))
}
eq(JSON.stringify(blocked),original)
// Matching reason in the same retained scan only; never borrow newer geometry.
const mismatched=item({rejection:'pre_nearest_resistance_below_2r',target_checks:[{...check,rejection_reason:'no_forward_zone',geometry:{rr_rounded:99}}]})
eq(explainActivity(mismatched,true).facts,[])
const rounded=item({rejection:'pre_invalid_rounded_levels',target_checks:[{...check,rejection_reason:'invalid_rounded_levels',rejection_detail:['target_buffer_reaches_entry','non_positive_stop']}]})
eq(itemReasonCodes(rounded),['pre_invalid_rounded_levels','target_buffer_reaches_entry','non_positive_stop'])
ok(markup(rounded,true).includes('מחיר הסטופ אינו חיובי'))
const ai=item({rejection:'ai_hold',rejection_stage:'ai_filter',ai_decision:{action:'HOLD',confidence:.77,confidence_threshold:.8,
 news_relevance:.42,relevance_threshold:.6,filter_failures:['ai_hold','ai_confidence_below_threshold','ai_news_relevance_below_threshold'],reason:'<script>synthetic</script> Original retained reason.'}})
eq(itemReasonCodes(ai).length,3)
const aiHtml=markup(ai,true)
for(const number of ['0.77','0.80','0.42','0.60'])ok(aiHtml.includes(number))
ok(aiHtml.includes('לא מכויל')&&aiHtml.includes('בשפת המקור'))
ok(aiHtml.includes('&lt;script&gt;synthetic')&&!aiHtml.includes('<script>synthetic'))
ok(aiHtml.includes('dir="auto"'))
const missing=item({rejection:'ai_confidence_below_threshold',rejection_stage:'ai_filter',ai_decision:{action:'BUY',confidence:.77}})
ok(!markup(missing,true).includes('0.80'));ok(!markup(missing,true).includes('0.00'))
const high=item({rejection:'pre_entry_not_above_completed_high',rejection_stage:'targets',target_checks:[{...check,
 rejection_reason:'entry_not_above_completed_high',source_inputs:{completed_high:101.5}}]})
ok(markup(high,true).includes('101.50'))
for(const code of ['pre_waiting_regular_session','post_waiting_regular_session','pre_duplicate_cooldown','candidate_cap','outside_shortlist','pre_refill_deferred']){
 const i=item({rejection:code});eq(i.state,'waiting');ok(activityStatusLabel(i,true).includes('לא פסילת איכות'))
}
const failure=item({rejection:'timeout_fail_closed'})
ok(activityStatusLabel(failure,true).includes('העיבוד לא הושלם'));ok(explainActivity(failure,true).detail.includes('לא פורסם סיגנל'))
ok(reasonDefinition('ValueError_fail_closed').detail[0].includes('הסיבה המדויקת'))
const unknown=item({rejection:'UNKNOWN_NEW_RULE'})
ok(explainActivity(unknown,true).title.includes('אינה זמינה'));ok(!markup(unknown,true).includes('UNKNOWN_NEW_RULE'))
for(const code of ['__proto__','constructor','toString']){
 eq(reasonDefinition(code).kind,'unknown');ok(markup(item({rejection:code}),true).includes('אינה זמינה'))
}
ok(!markup(item({target_checks:[]}),true).includes('הבדיקה עברה'))
// A second signal in the same scan must not contribute its order/status/reason.
const mixed=candidate('PAIR',{signals:[{id:901,status:'PENDING_ENTRY'},{id:902,status:'RECOVERY_UNCERTAIN'}],
 orders:[{id:1,signal_id:901,purpose:'entry',status:'pending'},
 {id:2,signal_id:902,purpose:'entry',status:'recovery_uncertain'},
 {id:3,purpose:'entry',status:'filled'}]})
const pair=buildActivity({records:[mixed]},null)
eq(pair.find(i=>i.signal.id===901).state,'waiting');eq(pair.find(i=>i.signal.id===902).state,'uncertain')
eq(linkedItemOrders(pair.find(i=>i.signal.id===901)).map(o=>o.id),[1])
eq(linkedItemOrders(pair.find(i=>i.signal.id===902)).map(o=>o.id),[2])
const pending=pair.find(i=>i.signal.id===901)
ok(explainActivity(pending,true).detail.includes('אין להסיק שמחיר הכניסה לא נגע'))
ok(!explainActivity(pending,true).title.includes('פוזיציה פעילה'))
const risk=buildActivity(null,{signals:[{id:3,ticker:'TEST',status:'RISK_BLOCKED'}]})[0]
ok(explainActivity(risk,true).detail.includes('אין להסיק שחסר מזומן'))
const invalid=buildActivity({records:[candidate('TEST',{signals:[{id:4,status:'ENTRY_POLICY_REJECTED'}],orders:[
 {id:4,signal_id:4,purpose:'entry',status:'invalid',entry_rejection_reason:'fill_rr_below_2'},
 {id:5,signal_id:5,purpose:'entry',status:'invalid',entry_rejection_reason:'fill_inside_unresolved_zone'}]})]},null)[0]
ok(markup(invalid,true).includes('במחיר הביצוע נמוך מ־2R'));ok(!markup(invalid,true).includes('בתוך אזור מחיר לא פתור'))
const unlinked=buildActivity(null,{signals:[{id:1,ticker:'TEST',status:'ENTERED',actual_entry:100}]})[0]
eq(unlinked.state,'uncertain');ok(explainActivity(unlinked,true).detail.includes('פוזיציה מקושרת'))
const close=buildActivity(null,{signals:[{id:1,ticker:'TEST',status:'PENDING_CLOSE'}]})[0]
ok(explainActivity(close,true).detail.includes('בקשת יציאה'))
for(const status of ['EXPIRED','CANCELLED','CLOSED','COMPLETED','REJECTED']){
 const i=buildActivity(null,{signals:[{id:1,ticker:'TEST',status}]})[0]
 eq(i.state,'closed');ok(explainActivity(i,true).next.includes('אין החייאה'))
}
const existing=buildActivity(fixtureResearch,fixtureDashboard)
for(const i of existing)for(const he of [true,false]){
 const e=explainActivity(i,he);ok(e.title&&e.detail&&e.next);ok(!JSON.stringify(e).includes('NaN'))
}
for(const s of STATIONS)for(const he of [0,1])ok(STATION_GUIDES[s].what[he]&&STATION_GUIDES[s].next[he])
// Every known target/policy and execution code has a meaningful explanation.
for(const code of Object.keys(REASON_DETAILS))for(const prefix of ['', 'pre_'])for(const he of [0,1]){
 const e=reasonDefinition(prefix+code);ok(e.title[he]&&e.detail[he]);ok(e.kind!=='unknown'||code==='unlinked_fill')
}
const pathological=item({rejection:'ai_hold',rejection_stage:'ai_filter',ai_decision:{filter_failures:'not an array'},target_checks:[{rejection_detail:'not an array'}]})
eq(itemReasonCodes(pathological),['ai_hold'])
for(const file of ['src/activityExplanation.ts','src/activityReasons.ts','src/BlockerExplanation.tsx']){
 const source=readFileSync(file,'utf8')
 for(const forbidden of ['fetch(','localStorage','sendMessage','dangerouslySetInnerHTML'])ok(!source.includes(forbidden))
}
// Readable retained-state labels in the light theme; not only color/shape cues.
const css=readFileSync('src/systemActivity.css','utf8')
const luminance=hex=>hex.match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0)
for(const hex of ['50677a','aa253b','755006','086549']){
 ok(css.includes('color:#'+hex));ok(1.05/(luminance(hex)+.05)>=4.5)
}
console.log(`Activity explanations: ${assertions} assertions passed; all stations, retained reasons, numeric gates, linkage and unknowns`)
