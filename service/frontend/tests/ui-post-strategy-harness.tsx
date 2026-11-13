// Development only. All application fetches are synthetic; unknown requests fail.
import React,{useState} from 'react'
import {createRoot} from 'react-dom/client'
import {MemoryRouter,useLocation,useNavigate} from 'react-router-dom'
import {ScannerDashboard} from '../src/ScannerDashboard'
import {LanguageContext,ThemeContext} from '../src/appShared'
import {getT} from '../src/i18n'
import {candidate,fixtureDashboard,fixtureResearch} from './system-activity-fixtures.mjs'
import '../src/index.css'
import '../src/miniAppActivity.css'
let failResearch=false
const now=()=>new Date().toISOString()
const check={phase:'pre_ai',outcome:'REJECT',decided_at:'2026-10-09T15:00:00Z',policy_version:'single_target_v2',
  quote:{price:74.94},minimum_rr:2,rejection_reason:'invalid_rounded_levels',rejection_detail:['target_buffer_reaches_entry'],
  geometry:{stop_rounded:73.05,target_rounded:74.8,rr_rounded:-.07},
  discovery_context:{status:'RECORDED',version:'entry_discovery_v1',strategy_ids:['BASELINE','VCP_BASE_CONTRACTION'],
    primary_strategy_id:'BASELINE',detected_at:'2026-10-09T14:59:00Z'}}
const rejected=candidate('CHECK',{rejection:'pre_invalid_rounded_levels',rejection_stage:'targets',
  target_checks:[check],reviews:[{result:'early_skip',attempts:0,at:check.decided_at}]})
const dashboard={...fixtureDashboard,paper_only:true,primary_user:{},main_portfolio:{},settings:{active_strategy:'single'},
  signals:fixtureDashboard.signals.map(s=>({...s,valid_until:'2099-10-09T15:00:00Z'})),
  trades:fixtureDashboard.trades.map(t=>({...t,last_bar_at:'2026-10-09T15:00:00Z'})),
  news_meta:{screen_generated_at:now()},news_watchlist:[],news_schedules:[],
  news_providers:Array.from({length:12},(_,i)=>({provider:`synthetic-${i}`,status:'ok',last_success_at:now()})),
  news:Array.from({length:91},(_,i)=>({id:i+1,ticker:'CHECK',title:`Synthetic article ${i+1}`,title_he:`ידיעת בדיקה ${i+1}`,
    publisher:'Synthetic source',provider:'synthetic',scope:'universe',published_at:now(),analysis_status:'analyzed',
    sentiment:'positive',materiality:'medium',url:'https://example.invalid/synthetic',
    ...(i===0?{signal_id:2}:i===1?{trade_ids:[40]}:i===2?{trade_ids:[50]}:{})}))}
const counts={signals:0,pending_entry_orders:0,actual_entries:0,open_trades:1,fully_closed_trades:0,partial_exit_trades:0}
const performance={version:1,as_of:now(),window_since:'2026-10-09T00:00:00Z',
  coverage:{status:'PARTIAL',clipped:['discovery'],evidence_gaps:{trade_entry_attribution_unavailable_or_mismatch:1}},
  overall:{counts},exact_set_groups:[],strategy_rows:['BASELINE','VCP_BASE_CONTRACTION','STOCKBEE_MOMENTUM_BURST','PEAD','TREND_PULLBACK_RECLAIM','RELATIVE_STRENGTH_LEADER','UNATTRIBUTED'].map(strategy_id=>({
    strategy_id,enabled:strategy_id==='UNATTRIBUTED'?null:strategy_id!=='PEAD',counts,metrics:{verified_closed:0,status:'PARTIAL_ATTRIBUTION'},
    detector_states:strategy_id==='VCP_BASE_CONTRACTION'?{DETECTED:2,FORMING:3}:{} }))}
window.fetch=async(input,options)=>{
  if((options?.method||'GET')!=='GET')throw new Error('Synthetic UI is read-only')
  const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.origin)
  if(url.pathname.endsWith('/scanner/dashboard'))return Response.json(dashboard)
  if(url.pathname.endsWith('/scanner/quotes'))return Response.json({quotes:[]})
  if(url.pathname.endsWith('/scanner/research')){
    if(failResearch)throw new Error('Synthetic research unavailable')
    return Response.json({...fixtureResearch,generated_at:now(),window_hours:Number(url.searchParams.get('hours')||48),
      counts:{},rejection_reasons:{},rejection_stages:{},outcome_groups:[],
      outcomes:fixtureResearch.outcomes.map(o=>({...o,side:'long',status:o.remaining_pct?'open':'closed'})),
      records:[rejected,...fixtureResearch.records]})
  }
  if(url.pathname.endsWith('/scanner/strategy-performance'))return Response.json({...performance,as_of:now()})
  throw new Error('Unexpected application request blocked by synthetic harness')
}
function Controls(){
  const navigate=useNavigate(),location=useLocation()
  return <div aria-label="Synthetic fixture controls" style={{position:'sticky',top:0,zIndex:50,background:'#fff',color:'#000',padding:8,display:'flex',flexWrap:'wrap',gap:8}}>
    <strong>נתונים סינתטיים בלבד. אין חיבור ל־Production.</strong>
    {['live','news','results','signals'].map(tab=><button key={tab} onClick={()=>navigate(`/market?tab=${tab}&miniapp=1`)}>fixture {tab}</button>)}
    <button onClick={()=>{failResearch=true;navigate('/market?tab=signals');navigate('/market?tab=live&miniapp=1')}}>fixture research failure</button>
    <code>{location.pathname}{location.search}{location.hash}</code>
  </div>
}
function Harness(){
  const [language,setLanguage]=useState<any>('he'),[theme,setTheme]=useState<any>('dark')
  React.useEffect(()=>{document.documentElement.dataset.theme=theme},[theme])
  return <LanguageContext.Provider value={{language,setLanguage,t:getT(language)}}><ThemeContext.Provider value={{theme,setTheme}}>
    <MemoryRouter basename="/AI-Trader" initialEntries={['/AI-Trader/market?tab=live&miniapp=1']}>
      <Controls/><div className="app-container miniapp-shell" style={{'--miniapp-height':'calc(100dvh - 100px)'} as React.CSSProperties}><main className="main-content"><ScannerDashboard token={null}/></main></div>
    </MemoryRouter>
  </ThemeContext.Provider></LanguageContext.Provider>
}
const root=createRoot(document.getElementById('root')!)
root.render(<Harness/>)
if(import.meta.hot)import.meta.hot.dispose(()=>root.unmount())
