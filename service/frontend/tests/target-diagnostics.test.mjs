// Exact retained target-check projection; no DOM/network/model calls.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
const bundle=await build({entryPoints:['src/targetDiagnostics.ts'],bundle:true,write:false,platform:'node',format:'cjs'})
const m={exports:{}}
new Function('require','module','exports',bundle.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
const {targetFacts,targetReasonCode}=m.exports
let count=0
const ok=value=>{assert.ok(value);count++}
const check={policy_version:'single_target_v2',decided_at:'2026-10-07T14:00:00Z',quote:{price:100},minimum_rr:2,
 rejection_reason:'invalid_rounded_levels',rejection_detail:['target_buffer_reaches_entry'],
 geometry:{stop_rounded:98.5,target_rounded:99.95,rr_unrounded:-.033333,rr_rounded:-.033333,
  risk_breakdown:{version:'single_target_risk_v1',selected_distance:1.5,raw_reward_distance:-.05,
    raw_reward_shortfall:3.05,binding_constraints:['atr_floor']}},
 discovery_context:{status:'RECORDED',version:'entry_discovery_v1',strategy_ids:['BASELINE','VCP_BASE_CONTRACTION'],
  primary_strategy_id:'BASELINE',detected_at:'2026-10-07T13:59:00Z'}}
const original=JSON.stringify(check)
for(const he of [true,false]){
 const facts=targetFacts(check,he),text=JSON.stringify(facts)
 ok(text.includes('3.05')&&text.includes('1.50')&&text.includes('99.95'))
 ok(text.includes(he?'מרחק הגנה לפי ATR':'ATR risk floor'))
 ok(text.includes(he?'עשויים לחפוף':'may overlap'))
 ok(targetReasonCode(check)==='target_buffer_reaches_entry')
 const bad={...check,quote:{price:[]},geometry:{stop_rounded:false,target_rounded:'',rr_rounded:{},
  risk_breakdown:{version:'single_target_risk_v1',selected_distance:[],raw_reward_distance:true,raw_reward_shortfall:{}}}}
 ok(!JSON.stringify(targetFacts(bad,he)).includes('0.00'))
 ok(!targetFacts({...check,evidence_gap:'oversize'},he).some(f=>f.value==='99.95'))
 ok(targetReasonCode({...check,evidence_gap:'oversize'})==='invalid_rounded_levels')
 for(const context of [null,{...check.discovery_context,detected_at:'2026-10-07T15:00:00Z'},
    {...check.discovery_context,strategy_ids:['__proto__']},{...check.discovery_context,strategy_ids:['BASELINE','BASELINE']}])
  ok(!JSON.stringify(targetFacts({...check,discovery_context:context},he)).includes(he?'מסלולים מזהים':'Detecting routes'))
 const unknownRisk={...check,geometry:{...check.geometry,risk_breakdown:{...check.geometry.risk_breakdown,version:'future'}}}
 ok(!JSON.stringify(targetFacts(unknownRisk,he)).includes('3.05'))
 const multi=targetFacts({policy_version:'confirmed_daily_swing_zones_v1',minimum_rr:2,accepted_levels:{rr:[1,2,3]}},he)
 ok(multi.some(f=>f.value==='1.00R')&&multi.some(f=>f.value==='3.00R'))
 ok(multi.some(f=>f.label.includes(he?'האמצעי':'middle-target')))
}
ok(JSON.stringify(check)===original)
ok(targetReasonCode({...check,rejection_reason:'entry_inside_unresolved_price_zone'})==='entry_inside_unresolved_price_zone')
ok(targetReasonCode({...check,rejection_detail:['unknown_future_code']})==='invalid_rounded_levels')
console.log(`Target diagnostics: ${count} assertions passed; frozen geometry, routes, unknowns and no decision changes`)
