// Development-only synthetic renderer. Not an entry in the production build.
import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { SystemActivityView } from '../src/SystemActivity'
import { LanguageContext, ThemeContext } from '../src/appShared'
import { getT } from '../src/i18n'
import '../src/index.css'
import { fixtureResearch, fixtureDashboard } from './system-activity-fixtures.mjs'
import { buildActivity } from '../src/systemActivityModel'
function Harness() {
  const [mode,setMode]=useState('full'),[ticker,setTicker]=useState(''),[hours,setHours]=useState(24)
  const [miniApp,setMiniApp]=useState(true),[selected,setSelected]=useState<string|null>(null)
  const [language,setLanguage]=useState<any>('he'),[theme,setTheme]=useState<any>('dark')
  const [width,setWidth]=useState(390),[height,setHeight]=useState(666)
  const [updates,setUpdates]=useState<any[]>([])
  React.useEffect(()=>{document.documentElement.dataset.theme=theme},[theme])
  const research=mode==='loading'?null:mode==='empty'?{records:[],generated_at:new Date().toISOString()}:{...fixtureResearch,generated_at:mode==='stale'?fixtureResearch.generated_at:new Date().toISOString()}
  const dashboard=mode==='loading'?null:mode==='empty'?{signals:[],trades:[],market:{is_open:false}}:fixtureDashboard
  return <LanguageContext.Provider value={{language,setLanguage,t:getT(language)}}><ThemeContext.Provider value={{theme,setTheme}}><MemoryRouter initialEntries={['/market?miniapp=1']}>
    <div className={miniApp?'miniapp-shell':'desktop-fixture'} style={{width:miniApp?width:'100%',maxWidth:'100%',margin:'auto','--miniapp-height':`${height}px`} as React.CSSProperties}><SystemActivityView he={language==='he'} miniApp={miniApp} selected={selected} setSelected={setSelected} research={research} dashboard={dashboard} updates={updates} error={mode==='error'?'Synthetic timeout':''} ticker={ticker} setTicker={setTicker} hours={hours} setHours={setHours} /></div>
    <div aria-label="Synthetic fixture controls" style={{display:'flex',gap:4,background:'#fff',color:'#000',flexWrap:'wrap'}}>{['full','loading','empty','error','stale'].map(v=><button key={v} onClick={()=>setMode(v)}>{v}</button>)}<button onClick={()=>setMiniApp(v=>!v)}>{miniApp?'Desktop fixture':'Mobile fixture'}</button><button onClick={()=>setLanguage(language==='he'?'en':'he')}>Fixture language</button><button onClick={()=>setUpdates([{key:`synthetic:${Date.now()}`,item:buildActivity(research,dashboard)[0]}])}>observed update</button><select aria-label="Fixture width" value={width} onChange={e=>setWidth(Number(e.target.value))}>{[360,390,430].map(v=><option key={v}>{v}</option>)}</select><select aria-label="Fixture height" value={height} onChange={e=>setHeight(Number(e.target.value))}>{[500,666,844].map(v=><option key={v}>{v}</option>)}</select></div>
  </MemoryRouter></ThemeContext.Provider></LanguageContext.Provider>
}
createRoot(document.getElementById('root')!).render(<Harness />)
