/** Read-only explanations of one frozen target check, never a replacement plan. */
import { type Row } from './systemActivityModel'
import { reasonKey } from './activityReasons'

const levelDetails = new Set(['target_buffer_reaches_entry','target_rounds_to_or_below_entry',
  'non_positive_stop','stop_not_below_entry','rounded_target_not_before_resistance'])

export function targetReasonCode(check:Row):string {
  const code=reasonKey(check.rejection_reason)
  if(code!=='invalid_rounded_levels'||check.evidence_gap)return code
  // Only an explicit retained subtype can refine the general reason. Never
  // guess a cause from a live quote, another phase, missing values or defaults.
  return (Array.isArray(check.rejection_detail)?check.rejection_detail:[])
    .find((detail:unknown)=>typeof detail==='string'&&levelDetails.has(detail))||code
}

export function targetFacts(check:Row,he:boolean):{label:string;value:string}[] {
  const t=(a:string,b:string)=>he?a:b, facts:{label:string;value:string}[]=[]
  const fact=(label:string,value:unknown,suffix='')=>{
    if(typeof value==='number'&&Number.isFinite(value))facts.push({label,value:value.toFixed(2)+suffix})
  }
  const g=check.geometry||{}, accepted=check.accepted_levels||{}
  const context=check.discovery_context, ids=context?.strategy_ids
  const strategyNames:Record<string,[string,string]>={BASELINE:['מסלול הבסיס','Baseline'],
    VCP_BASE_CONTRACTION:['התכווצות בסיס ופריצה','VCP base contraction'],
    STOCKBEE_MOMENTUM_BURST:['התפרצות מומנטום','Momentum burst'],PEAD:['המשכיות אחרי דוחות','PEAD'],
    TREND_PULLBACK_RECLAIM:['תיקון וחזרה למגמה','Trend pullback reclaim'],
    RELATIVE_STRENGTH_LEADER:['מובילת חוזק יחסי','Relative-strength leader']}
  const detected=typeof context?.detected_at==='string'?Date.parse(context.detected_at):NaN
  const decided=typeof check.decided_at==='string'?Date.parse(check.decided_at):NaN
  if(context?.status==='RECORDED'&&context.version==='entry_discovery_v1'&&Number.isFinite(detected)&&Number.isFinite(decided)&&detected<=decided&&Array.isArray(ids)&&
    ids.length>0&&ids.length<=6&&new Set(ids).size===ids.length&&context.primary_strategy_id===ids[0]&&
    ids.every((id:unknown)=>typeof id==='string'&&Object.prototype.hasOwnProperty.call(strategyNames,id)))
    facts.push({label:t('מסלולים מזהים, עשויים לחפוף','Detecting routes, may overlap'),value:ids.map((id:string)=>strategyNames[id][he?0:1]).join(' + ')})
  fact(t('מחיר ייחוס בבדיקה','Reference price at check'),check.quote?.price)
  if(check.evidence_gap)return facts
  fact(t('סטופ שנבדק','Checked stop'),accepted.stop??g.stop_rounded)
  fact(t('יעד שנבדק','Checked target'),accepted.active_target??g.target_rounded)
  fact(t('RR ברוטו לפני עיגול','Gross RR before rounding'),g.rr_unrounded,'R')
  if(Array.isArray(accepted.rr)&&accepted.rr.length>1)
    accepted.rr.slice(0,3).forEach((rr:unknown,index:number)=>fact(t(`RR יעד ${index+1} שנשמר`,`Retained target ${index+1} RR`),rr,'R'))
  else fact(t('RR שנבדק לאחר עיגול','Checked RR after rounding'),accepted.rr?.[0]??g.rr_rounded,'R')
  fact(check.policy_version==='confirmed_daily_swing_zones_v1'?t('סף RR ליעד האמצעי ולממוצע שנשמר','Retained middle-target and mean RR threshold'):t('RR מינימלי שנשמר','Retained minimum RR'),check.minimum_rr,'R')
  fact(t('התנגדות קרובה שנשמרה','Retained nearest resistance'),g.nearest_resistance?.low)
  const risk=g.risk_breakdown
  if(check.policy_version==='single_target_v2'&&risk?.version==='single_target_risk_v1'){
    fact(t('מרחק סטופ לפני עיגול, למניה','Raw stop distance per share'),risk.selected_distance)
    fact(t('מרווח יעד לפני עיגול, למניה','Raw reward distance per share'),risk.raw_reward_distance)
    fact(t('מרווח יעד חסר לפני עיגול, למניה','Raw reward distance shortfall per share'),risk.raw_reward_shortfall)
    const names:Record<string,string>={structural:t('עוגן המבנה','Structural anchor'),
      atr_floor:t('מרחק הגנה לפי ATR','ATR risk floor'),price_floor:t('מרחק הגנה יחסי למחיר','Price-relative risk floor')}
    const constraints=Array.isArray(risk.binding_constraints)?risk.binding_constraints:[]
    const labels=constraints.filter((v:unknown)=>typeof v==='string'&&Object.prototype.hasOwnProperty.call(names,v)).map((v:string)=>names[v])
    if(labels.length)facts.push({label:t('מה קבע את מרחק הסטופ בבדיקה','Binding stop-distance constraint'),value:labels.join(' + ')})
  }
  return facts
}
