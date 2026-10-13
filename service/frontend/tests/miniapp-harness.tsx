// Development-only synthetic renderer. Not an entry in the production build.
import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { SystemActivityView } from '../src/SystemActivity'
import { LanguageContext, ThemeContext } from '../src/appShared'
import { getT } from '../src/i18n'
import '../src/index.css'
import { candidate, fixtureResearch, fixtureDashboard } from './system-activity-fixtures.mjs'
import { buildActivity } from '../src/systemActivityModel'
const check={phase:'pre_ai',outcome:'REJECT',observed_at:'2026-10-09T15:00:00Z',minimum_rr:2,quote:{price:100,as_of:'2026-10-09T15:00:00Z'},geometry:{rr_rounded:1.72,nearest_resistance:{low:105.3}}}
const explanationResearch={...fixtureResearch,records:[...fixtureResearch.records,
  candidate('RRLOW',{rejection:'pre_nearest_resistance_below_2r',rejection_stage:'targets',target_checks:[{...check,rejection_reason:'nearest_resistance_below_2r'}]}),
  candidate('ROUND',{rejection:'pre_invalid_rounded_levels',rejection_stage:'targets',target_checks:[{...check,rejection_reason:'invalid_rounded_levels',rejection_detail:['target_buffer_reaches_entry']}]}),
  candidate('NOHIGH',{rejection:'pre_entry_not_above_completed_high',rejection_stage:'targets',target_checks:[{...check,rejection_reason:'entry_not_above_completed_high',source_inputs:{completed_high:101.5}}]}),
  candidate('WAIT',{rejection:'pre_waiting_regular_session',rejection_stage:'session_wait'}),
  candidate('SCORE',{rejection:'ai_confidence_below_threshold',rejection_stage:'ai_filter',ai_decision:{action:'BUY',confidence:.77,confidence_threshold:.8,filter_failures:['ai_confidence_below_threshold'],reason:'Synthetic score fixture: confirmation is insufficient.'}}),
  candidate('MULTI',{rejection:'ai_hold',rejection_stage:'ai_filter',ai_decision:{action:'HOLD',confidence:.6,confidence_threshold:.8,news_relevance:.42,relevance_threshold:.6,filter_failures:['ai_hold','ai_confidence_below_threshold','ai_news_relevance_below_threshold'],reason:'Synthetic fixture only. Waiting for price and volume confirmation.'}}),
  candidate('FAIL',{rejection:'timeout_fail_closed',rejection_stage:'ai_filter',reviews:[{result:'rejected',attempts:1}]}),
  candidate('UNKNOWN',{rejection:'UNKNOWN_NEW_RULE'}),
]}
function Harness() {
  const [mode,setMode]=useState('full'),[ticker,setTicker]=useState(''),[hours,setHours]=useState(24)
  const [miniApp,setMiniApp]=useState(true),[selected,setSelected]=useState<string|null>(null)
  const [language,setLanguage]=useState<any>('he'),[theme,setTheme]=useState<any>('dark')
  const [width,setWidth]=useState(390),[height,setHeight]=useState(666)
  const [updates,setUpdates]=useState<any[]>([])
  React.useEffect(()=>{document.documentElement.dataset.theme=theme},[theme])
  const research=mode==='loading'?null:mode==='empty'?{records:[],generated_at:new Date().toISOString()}:{...(mode==='reasons'?explanationResearch:fixtureResearch),generated_at:mode==='stale'?fixtureResearch.generated_at:new Date().toISOString()}
  const dashboard=mode==='loading'?null:mode==='empty'?{signals:[],trades:[],market:{is_open:false}}:fixtureDashboard
  return <LanguageContext.Provider value={{language,setLanguage,t:getT(language)}}><ThemeContext.Provider value={{theme,setTheme}}><MemoryRouter initialEntries={['/market?miniapp=1']}>
    <div className={miniApp?'miniapp-shell':'desktop-fixture'} style={{width:miniApp?width:'100%',maxWidth:'100%',margin:'auto','--miniapp-height':`${height}px`} as React.CSSProperties}><SystemActivityView he={language==='he'} miniApp={miniApp} selected={selected} setSelected={setSelected} research={research} dashboard={dashboard} updates={updates} error={mode==='error'?'Synthetic timeout':''} ticker={ticker} setTicker={setTicker} hours={hours} setHours={setHours} /></div>
    <div aria-label="Synthetic fixture controls" style={{display:'flex',gap:4,background:'#fff',color:'#000',flexWrap:'wrap'}}>{['full','reasons','loading','empty','error','stale'].map(v=><button key={v} onClick={()=>setMode(v)}>{v}</button>)}<button onClick={()=>setMiniApp(v=>!v)}>{miniApp?'Desktop fixture':'Mobile fixture'}</button><button onClick={()=>setLanguage(language==='he'?'en':'he')}>Fixture language</button><button onClick={()=>setUpdates([{key:`synthetic:${Date.now()}`,item:buildActivity(research,dashboard)[0]}])}>observed update</button><select aria-label="Fixture width" value={width} onChange={e=>setWidth(Number(e.target.value))}>{[360,390,430].map(v=><option key={v}>{v}</option>)}</select><select aria-label="Fixture height" value={height} onChange={e=>setHeight(Number(e.target.value))}>{[500,666,844].map(v=><option key={v}>{v}</option>)}</select></div>
  </MemoryRouter></ThemeContext.Provider></LanguageContext.Provider>
}
const root=createRoot(document.getElementById('root')!)
root.render(<Harness />)
if(import.meta.hot)import.meta.hot.dispose(()=>root.unmount())
